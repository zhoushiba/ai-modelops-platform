"""训练框架的公共抽象：训练上下文、取消信号、训练结果。"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Any, Callable


class JobCanceled(Exception):
    """任务被用户取消（协作式取消：训练循环每轮检查一次）。"""


class TrainingError(Exception):
    """可预期的训练失败（数据不合法等），错误信息直接回显给前端。"""


@dataclass
class TrainResult:
    """训练产物：可序列化的模型包 + 指标 + 附加信息。"""

    bundle: Any
    metrics: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    artifact_filename: str = "model.joblib"


class TrainingContext:
    """训练过程中的回调集合：日志、指标、进度、取消检查。"""

    def __init__(
        self,
        job_id: int,
        hyperparams: dict[str, Any],
        *,
        on_log: Callable[[str, str], None],
        on_metric: Callable[[int, str, float], None],
        on_progress: Callable[[int, str], None],
        should_cancel: Callable[[], bool],
    ) -> None:
        self.job_id = job_id
        self.hyperparams = hyperparams
        self._on_log = on_log
        self._on_metric = on_metric
        self._on_progress = on_progress
        self._should_cancel = should_cancel

    def log(self, message: str, level: str = "INFO") -> None:
        self._on_log(level, message)

    def metric(self, epoch: int, name: str, value: float) -> None:
        self._on_metric(epoch, name, float(value))

    def progress(self, percent: int, message: str = "") -> None:
        self._on_progress(max(0, min(100, int(percent))), message)

    def check_cancel(self) -> None:
        if self._should_cancel():
            raise JobCanceled("任务已被用户取消")

    def fail(self, message: str, exc: BaseException | None = None) -> None:
        """记录失败详情（含堆栈），再抛出 TrainingError。"""
        if exc is not None:
            self.log(traceback.format_exc(), level="ERROR")
        raise TrainingError(message)


class BaseTrainer:
    """所有任务类型的训练器基类。新增任务类型只需继承并实现 ``train``。"""

    task_type: str = ""
    display_name: str = ""
    description: str = ""
    base_models: tuple[str, ...] = ()

    def validate(self, rows: list, hyperparams: dict[str, Any]) -> None:
        """训练前的数据校验，失败抛 ``TrainingError``。"""

    def validate_hparams(self, hyperparams: dict[str, Any]) -> None:
        """超参合法性校验（提交任务时调用），失败抛 ``TrainingError``。"""
        epochs = int(hyperparams.get("epochs", 1) or 1)
        if not 1 <= epochs <= 50:
            raise TrainingError("epochs 必须在 1-50 之间")
        if float(hyperparams.get("lr", 1.0) or 1.0) <= 0:
            raise TrainingError("lr 必须大于 0")
        chunk_size = int(hyperparams.get("chunk_size", 220) or 220)
        chunk_overlap = int(hyperparams.get("chunk_overlap", 40) or 0)
        if chunk_size < 20:
            raise TrainingError("chunk_size 不能小于 20")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise TrainingError("chunk_overlap 必须大于等于 0 且小于 chunk_size")

    def train(self, rows: list, hyperparams: dict[str, Any], ctx: TrainingContext) -> TrainResult:
        raise NotImplementedError

    def persist(self, db, job, result: TrainResult) -> None:  # noqa: ANN001
        """任务成功后的额外持久化（例如 RAG 向量表）。默认无需处理。"""
