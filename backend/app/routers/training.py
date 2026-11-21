"""训练任务接口：提交、列表、详情、实时日志、指标曲线、取消、手动注册。"""

from __future__ import annotations

import json
import time
from typing import Iterator

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import serializers
from app.crud import datasets as dataset_crud
from app.crud import jobs as job_crud
from app.database import SessionLocal, get_db
from app.deps import get_current_user
from app.errors import AppError, NotFoundError, envelope
from app.models import TrainingJob, User
from app.schemas import RegisterJobRequest, TrainingJobCreate
from app.services import registry_service
from app.services.training_runner import training_runner
from app.trainers import supported_tasks
from app.trainers.base import TrainingError

router = APIRouter(prefix="/training", tags=["训练任务"])

TASK_LABELS = {
    "text_classification": "文本分类（TF-IDF + LogisticRegression）",
    "rag_corpus": "RAG 索引构建（切片 + 向量化）",
}


@router.get("/trainers")
def list_trainers(_: User = Depends(get_current_user)) -> dict:
    """列出当前可用的训练任务类型（供前端新建任务下拉框）。"""
    return envelope(supported_tasks())


@router.get("/jobs")
def list_jobs(
    status: str = Query(""),
    q: str = Query(""),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """分页列出训练任务（按创建时间倒序）。"""
    items, total = job_crud.list_jobs(db, status=status, q=q, page=page, size=size)
    return envelope(
        {
            "items": [serializers.job(db, item) for item in items],
            "total": total,
            "page": page,
            "size": size,
        }
    )


@router.post("/jobs")
def create_job(
    payload: TrainingJobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """提交训练任务：校验数据集与超参后入队，由后台线程池异步执行。"""
    version = dataset_crud.get_version_detail(db, payload.dataset_version_id)
    if version is None:
        raise NotFoundError("数据集版本不存在")
    dataset_task = version.dataset.task_type if version.dataset else ""
    if dataset_task and dataset_task != payload.task_type:
        raise AppError(
            f"数据集任务类型为 {dataset_task}，与提交的 {payload.task_type} 不一致", code=40030
        )
    hyperparams = payload.hyperparams.model_dump()
    try:
        from app.trainers import get_trainer

        trainer = get_trainer(payload.task_type)
        trainer.validate_hparams(hyperparams)
    except TrainingError as exc:
        raise AppError(str(exc), code=40031) from exc

    job = job_crud.create_job(
        db,
        name=payload.name.strip(),
        dataset_version_id=payload.dataset_version_id,
        task_type=payload.task_type,
        base_model=payload.base_model,
        hyperparams=hyperparams,
        created_by=user.username,
        auto_register=payload.auto_register,
        register_as=payload.register_as,
    )
    job_crud.append_log(db, job, "INFO", f"任务已入队：{job.name}（{payload.task_type}）")
    training_runner.enqueue(job.id)
    return envelope(serializers.job(db, job))


@router.get("/jobs/{job_id}")
def get_job(
    job_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """任务详情：状态、进度、指标、日志、产物哈希。"""
    job = job_crud.get_job_detail(db, job_id)
    if job is None:
        raise NotFoundError("训练任务不存在")
    return envelope(serializers.job_detail(db, job))


@router.get("/jobs/{job_id}/logs")
def get_logs(
    job_id: int,
    after_id: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """增量拉取日志（前端轮询 ``after_id``）。"""
    job = job_crud.get_job(db, job_id)
    if job is None:
        raise NotFoundError("训练任务不存在")
    logs = job_crud.list_logs(db, job_id, after_id=after_id, limit=limit)
    return envelope(
        {
            "items": [serializers.training_log(item) for item in logs],
            "status": job.status,
            "progress": job.progress,
        }
    )


@router.get("/jobs/{job_id}/metrics")
def get_metrics(
    job_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """拉取逐 epoch 指标（画 loss/acc 曲线）。"""
    job = job_crud.get_job(db, job_id)
    if job is None:
        raise NotFoundError("训练任务不存在")
    metrics = job_crud.list_metrics(db, job_id)
    return envelope({"items": [serializers.training_metric(item) for item in metrics]})


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """取消任务：排队中直接置为 canceled，运行中设置协作取消标记。"""
    job = job_crud.get_job(db, job_id)
    if job is None:
        raise NotFoundError("训练任务不存在")
    if job.status in job_crud.TERMINAL_STATUSES:
        raise AppError(f"任务已结束（{job.status}），无法取消", code=40920, status_code=409)
    job.cancel_requested = True
    if job.status == "queued":
        job_crud.set_status(db, job, "canceled", "排队阶段被取消")
        training_runner.forget(job_id)
    else:
        training_runner.cancel(job_id)
        job_crud.append_log(db, job, "WARNING", "收到取消请求，将在当前步骤结束后停止")
    db.commit()
    return envelope(serializers.job(db, job))


@router.post("/jobs/{job_id}/register")
def register_job(
    job_id: int,
    payload: RegisterJobRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """把已完成任务的产物手动注册为模型版本（默认已自动注册，此处用于补注册/改别名）。"""
    job = job_crud.get_job(db, job_id)
    if job is None:
        raise NotFoundError("训练任务不存在")
    if job.status != "succeeded":
        raise AppError("只有 succeeded 的任务可以注册模型", code=40921, status_code=409)
    if job.model_version_id:
        from app.crud import models as model_crud

        existing = model_crud.get_version_detail(db, job.model_version_id)
        if existing is not None:
            return envelope({"model_version": serializers.model_version(db, existing), "already": True})
    if not job.artifact_path or not job.artifact_sha256:
        raise AppError("任务缺少模型产物，无法注册", code=40922, status_code=409)
    payload = payload or RegisterJobRequest()
    model_name = (payload.model_name or job.register_as or job.name).strip()
    version = registry_service.register_model(
        db,
        task_type=job.task_type,
        model_name=model_name,
        description=payload.description or "",
        job=job,
        metrics=job.metrics_json or {},
        hyperparams=job.hyperparams_json or {},
        labels=(job.metrics_json or {}).get("labels", []),
        artifact_path=job.artifact_path,
        artifact_size=job.artifact_size,
        artifact_sha256=job.artifact_sha256,
        framework="scikit-learn",
        created_by=user.username,
    )
    return envelope({"model_version": serializers.model_version(db, version), "already": False})


@router.get("/jobs/{job_id}/stream")
def stream_job(job_id: int) -> StreamingResponse:
    """SSE 实时推送任务状态与新增日志（前端也可用轮询，两种都支持）。"""

    def event_source() -> Iterator[str]:
        last_log_id = 0
        while True:
            with SessionLocal() as session:
                job = session.get(TrainingJob, job_id)
                if job is None:
                    yield 'data: {"error": "not_found"}\n\n'
                    return
                status = job.status
                progress = job.progress
                logs = job_crud.list_logs(session, job_id, after_id=last_log_id, limit=200)
                if logs:
                    last_log_id = logs[-1].id
                payload = {
                    "status": status,
                    "progress": progress,
                    "logs": [serializers.training_log(item) for item in logs],
                }
            yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
            if status in job_crud.TERMINAL_STATUSES:
                yield "data: [DONE]\n\n"
                return
            time.sleep(1.0)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
