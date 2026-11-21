"""训练任务执行器：内存队列 + 工作线程池 + 协作式取消。

设计要点：
1. 任务入队后由工作线程从数据库读取任务，状态机 ``queued → running → succeeded/failed/canceled``；
2. 训练循环内部通过 ``TrainingContext.check_cancel()`` 主动检查取消信号，做到"可取消"；
3. 产物用 ``joblib`` 落盘到 ``storage/models/job-<id>/``，并计算 SHA-256 指纹；
4. 训练成功后按需自动注册模型版本（含自动生成的 Model Card）；
5. 进程重启时 ``recover()`` 把中断的 running 任务标记失败、把 queued 任务重新入队。
"""

from __future__ import annotations

import hashlib
import logging
import queue
import threading
import traceback
from pathlib import Path

import joblib
import sklearn

from app.config import settings
from app.crud import jobs as job_crud
from app.database import session_scope
from app.models import TrainingJob, utcnow
from app.services import dataset_service, registry_service
from app.trainers import get_trainer
from app.trainers.base import JobCanceled, TrainingContext, TrainingError

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"succeeded", "failed", "canceled"}
_SENTINEL = -1


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TrainingRunner:
    """极简但真实的任务执行器（不依赖 Celery/Redis，便于单机演示）。"""

    def __init__(self, concurrency: int = 2) -> None:
        self._queue: "queue.Queue[int]" = queue.Queue()
        self._events: dict[int, threading.Event] = {}
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._concurrency = max(1, concurrency)
        self._running = False

    # ------------------------------------------------------------------ 生命周期
    def start(self, concurrency: int | None = None) -> None:
        if self._running:
            return
        if concurrency:
            self._concurrency = max(1, concurrency)
        self._running = True
        for index in range(self._concurrency):
            thread = threading.Thread(
                target=self._worker_loop, name=f"trainer-{index + 1}", daemon=True
            )
            thread.start()
            self._threads.append(thread)
        logger.info("训练执行器已启动，工作线程数=%s", self._concurrency)

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for _ in self._threads:
            self._queue.put(_SENTINEL)
        for thread in self._threads:
            thread.join(timeout=3)
        self._threads.clear()
        logger.info("训练执行器已停止")

    @property
    def running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------ 对外接口
    def enqueue(self, job_id: int) -> None:
        self._queue.put(job_id)

    def cancel(self, job_id: int) -> None:
        """登记取消信号；训练循环会在下一个检查点退出。"""
        with self._lock:
            self._events.setdefault(job_id, threading.Event()).set()

    def is_cancel_requested(self, job_id: int) -> bool:
        with self._lock:
            event = self._events.get(job_id)
        return bool(event and event.is_set())

    def forget(self, job_id: int) -> None:
        with self._lock:
            self._events.pop(job_id, None)

    def recover(self) -> dict[str, int]:
        """服务启动时恢复队列：中断的 running 任务置失败，queued 任务重新入队。"""
        stats = {"failed": 0, "requeued": 0}
        with session_scope() as db:
            rows = (
                db.query(TrainingJob)
                .filter(TrainingJob.status.in_(["queued", "running"]))
                .order_by(TrainingJob.id)
                .all()
            )
            for job in rows:
                if job.status == "running":
                    job.status = "failed"
                    job.status_message = "服务重启导致任务中断，请重新提交"
                    job.finished_at = utcnow()
                    stats["failed"] += 1
                else:
                    stats["requeued"] += 1
                    self.enqueue(job.id)
            db.commit()
        if stats["failed"] or stats["requeued"]:
            logger.warning("训练队列恢复：%s", stats)
        return stats

    # ------------------------------------------------------------------ 内部执行
    def _worker_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                if job_id == _SENTINEL or not self._running:
                    return
                self.run_job(job_id)
            except Exception:  # noqa: BLE001 - 工作线程绝不能退出
                logger.exception("训练线程异常 job_id=%s", job_id)
            finally:
                self._queue.task_done()

    def run_job(self, job_id: int) -> None:
        """同步执行一个训练任务；工作线程与内联模式共用。"""
        with session_scope() as db:
            job = db.get(TrainingJob, job_id)
            if job is None:
                logger.warning("训练任务不存在 job_id=%s", job_id)
                return
            if job.status in TERMINAL_STATUSES:
                return
            if job.cancel_requested or self.is_cancel_requested(job_id):
                job.status = "canceled"
                job.status_message = "排队期间被取消"
                job.progress = 0
                job.finished_at = utcnow()
                db.commit()
                self.forget(job_id)
                return
            job.status = "running"
            job.started_at = utcnow()
            job.progress = 1
            job.status_message = "任务开始执行"
            task_type = job.task_type
            dataset_version_id = job.dataset_version_id
            hyperparams = dict(job.hyperparams_json or {})
            job_crud.append_log(
                db, job, "INFO", f"任务开始：type={task_type} dataset_version={dataset_version_id}"
            )
            db.commit()

        event = self._event_for(job_id)
        with session_scope() as db:
            job = db.get(TrainingJob, job_id)
            rows = dataset_service.load_samples_as_rows(db, dataset_version_id)

            def on_log(level: str, message: str) -> None:
                job_crud.append_log(db, job, level, message)

            def on_metric(epoch: int, name: str, value: float) -> None:
                job_crud.add_metric(db, job, epoch, name, value)

            def on_progress(percent: int, message: str = "") -> None:
                job.progress = max(0, min(99, int(percent)))
                if message:
                    job.status_message = message
                db.commit()

            def should_cancel() -> bool:
                return event.is_set()

            trainer = get_trainer(task_type)
            context = TrainingContext(
                job_id=job_id,
                hyperparams=hyperparams,
                on_log=on_log,
                on_metric=on_metric,
                on_progress=on_progress,
                should_cancel=should_cancel,
            )
            try:
                if not rows:
                    raise TrainingError("数据集版本没有可用样本")
                context.log(f"样本载入完成：{len(rows)} 条，开始校验超参数与标签")
                trainer.validate(rows, hyperparams)
                context.progress(5, "数据校验通过，开始训练")
                result = trainer.train(rows, hyperparams, context)
                context.check_cancel()
                context.progress(95, "训练完成，正在保存模型产物")

                artifact_dir = settings.models_path / f"job-{job_id}"
                artifact_dir.mkdir(parents=True, exist_ok=True)
                artifact_path = artifact_dir / result.artifact_filename
                joblib.dump(result.bundle, artifact_path, compress=3)
                size = artifact_path.stat().st_size
                digest = sha256_file(artifact_path)
                context.log(
                    f"模型产物已写入 {settings.relative_path(artifact_path)}，"
                    f"大小 {round(size / 1024, 1)} KB，sha256={digest[:16]}…"
                )

                trainer.persist(db, job, result)
                job.artifact_path = settings.relative_path(artifact_path)
                job.artifact_size = size
                job.artifact_sha256 = digest
                job.metrics_json = result.metrics
                job.status = "succeeded"
                job.progress = 100
                job.status_message = "训练成功"
                job.finished_at = utcnow()
                db.commit()
                context.log("训练任务成功完成")

                if job.auto_register:
                    model_name = (job.register_as or job.name or f"{task_type}-{job_id}").strip()
                    try:
                        version = registry_service.register_model(
                            db,
                            task_type=task_type,
                            model_name=model_name,
                            description=trainer.description,
                            job=job,
                            metrics=result.metrics,
                            hyperparams=dict(hyperparams),
                            labels=list(result.metrics.get("labels", [])),
                            artifact_path=job.artifact_path,
                            artifact_size=size,
                            artifact_sha256=digest,
                            framework=f"scikit-learn {sklearn.__version__}",
                            created_by=job.created_by,
                        )
                        context.log(
                            f"已自动注册模型 {model_name} v{version.version}（状态 staging）"
                        )
                    except Exception as exc:  # noqa: BLE001 - 注册失败不应改变训练结果
                        logger.exception("自动注册模型失败 job_id=%s", job_id)
                        context.log(f"自动注册模型失败：{exc}", level="WARNING")

            except JobCanceled:
                db.rollback()
                job = db.get(TrainingJob, job_id)
                job.status = "canceled"
                job.status_message = "任务被用户取消"
                job.finished_at = utcnow()
                db.commit()
                job_crud.append_log(db, job, "WARNING", "收到取消信号，训练已停止")
                logger.info("训练任务已取消 job_id=%s", job_id)

            except TrainingError as exc:
                db.rollback()
                job = db.get(TrainingJob, job_id)
                job.status = "failed"
                job.status_message = str(exc)
                job.finished_at = utcnow()
                db.commit()
                job_crud.append_log(db, job, "ERROR", f"训练失败：{exc}")
                logger.warning("训练任务失败 job_id=%s：%s", job_id, exc)

            except Exception as exc:  # noqa: BLE001 - 兜底记录堆栈
                db.rollback()
                job = db.get(TrainingJob, job_id)
                job.status = "failed"
                job.status_message = f"内部错误：{exc}"
                job.finished_at = utcnow()
                db.commit()
                job_crud.append_log(db, job, "ERROR", traceback.format_exc()[-4000:])
                logger.exception("训练任务异常 job_id=%s", job_id)

            finally:
                self.forget(job_id)

    def _event_for(self, job_id: int) -> threading.Event:
        with self._lock:
            return self._events.setdefault(job_id, threading.Event())


training_runner = TrainingRunner()
