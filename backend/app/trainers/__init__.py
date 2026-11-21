"""训练器注册表。

新增任务类型：在 ``app/trainers/`` 下实现 ``BaseTrainer`` 子类并加入 ``TRAINERS``，
无需改动 API / 前端（详见 docs/training.md）。
"""

from __future__ import annotations

from app.trainers.base import (
    BaseTrainer,
    JobCanceled,
    TrainResult,
    TrainingContext,
    TrainingError,
)
from app.trainers.classification import TextClassificationTrainer
from app.trainers.rag import RagIndexTrainer

_TRAINER_CLASSES = (TextClassificationTrainer, RagIndexTrainer)

# 训练器无状态，注册为单例实例即可被并发复用
TRAINERS: dict[str, BaseTrainer] = {trainer.task_type: trainer for trainer in (cls() for cls in _TRAINER_CLASSES)}


def get_trainer(task_type: str) -> BaseTrainer:
    trainer = TRAINERS.get(task_type)
    if trainer is None:
        raise TrainingError(f"不支持的任务类型：{task_type}")
    return trainer


def supported_tasks() -> list[dict]:
    """给前端下拉框用的任务类型清单。"""
    return [
        {
            "task_type": trainer.task_type,
            "display_name": trainer.display_name,
            "description": trainer.description,
            "base_models": list(trainer.base_models),
        }
        for trainer in TRAINERS.values()
    ]


__all__ = [
    "BaseTrainer",
    "JobCanceled",
    "TrainResult",
    "TrainingContext",
    "TrainingError",
    "TRAINERS",
    "get_trainer",
    "supported_tasks",
]
