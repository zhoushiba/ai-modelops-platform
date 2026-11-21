"""训练任务 / 日志 / 指标查询。"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Dataset,
    DatasetVersion,
    TrainingJob,
    TrainingLog,
    TrainingMetric,
    utcnow,
)

TERMINAL_STATUSES = ("succeeded", "failed", "canceled")


def get_job(db: Session, job_id: int) -> TrainingJob | None:
    return db.get(TrainingJob, job_id)


def get_job_detail(db: Session, job_id: int) -> TrainingJob | None:
    stmt = (
        select(TrainingJob)
        .where(TrainingJob.id == job_id)
        .options(selectinload(TrainingJob.logs), selectinload(TrainingJob.metrics))
    )
    return db.scalars(stmt).first()


def list_jobs(
    db: Session, status: str = "", q: str = "", page: int = 1, size: int = 20
) -> tuple[list[TrainingJob], int]:
    stmt = select(TrainingJob).order_by(TrainingJob.id.desc())
    if status:
        stmt = stmt.where(TrainingJob.status == status)
    if q:
        stmt = stmt.where(or_(TrainingJob.name.like(f"%{q}%"), TrainingJob.task_type.like(f"%{q}%")))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = list(db.scalars(stmt.offset((page - 1) * size).limit(size)).all())
    return items, int(total)


def dataset_of_job(db: Session, job: TrainingJob) -> tuple[str, int]:
    row = db.execute(
        select(Dataset.name, DatasetVersion.version)
        .join(DatasetVersion, DatasetVersion.dataset_id == Dataset.id)
        .where(DatasetVersion.id == job.dataset_version_id)
    ).first()
    return (row[0], row[1]) if row else ("", 0)


def create_job(
    db: Session,
    *,
    name: str,
    dataset_version_id: int,
    task_type: str,
    base_model: str,
    hyperparams: dict,
    created_by: str,
    auto_register: bool = True,
    register_as: str = "",
) -> TrainingJob:
    job = TrainingJob(
        name=name,
        dataset_version_id=dataset_version_id,
        task_type=task_type,
        base_model=base_model,
        hyperparams_json=hyperparams,
        status="queued",
        progress=0,
        status_message="已进入队列",
        created_by=created_by,
        auto_register=auto_register,
        register_as=register_as,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def set_status(db: Session, job: TrainingJob, status: str, message: str = "") -> None:
    job.status = status
    if message:
        job.status_message = message
    db.commit()


def append_log(db: Session, job: TrainingJob, level: str, message: str) -> TrainingLog:
    log = TrainingLog(job_id=job.id, level=level.upper(), message=message, ts=utcnow())
    db.add(log)
    db.commit()
    return log


def add_metric(db: Session, job: TrainingJob, epoch: int, name: str, value: float) -> None:
    db.add(TrainingMetric(job_id=job.id, epoch=epoch, name=name, value=float(value)))
    db.commit()


def list_logs(db: Session, job_id: int, after_id: int = 0, limit: int = 500) -> list[TrainingLog]:
    stmt = (
        select(TrainingLog)
        .where(TrainingLog.job_id == job_id, TrainingLog.id > after_id)
        .order_by(TrainingLog.id)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def list_metrics(db: Session, job_id: int) -> list[TrainingMetric]:
    stmt = select(TrainingMetric).where(TrainingMetric.job_id == job_id).order_by(TrainingMetric.id)
    return list(db.scalars(stmt).all())


def count_jobs(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(TrainingJob)) or 0


def count_running(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(TrainingJob)
            .where(TrainingJob.status.in_(["queued", "running"]))
        )
        or 0
    )


def success_rate(db: Session) -> float:
    total = db.scalar(
        select(func.count()).select_from(TrainingJob).where(TrainingJob.status.in_(TERMINAL_STATUSES))
    ) or 0
    if not total:
        return 0.0
    ok = db.scalar(
        select(func.count()).select_from(TrainingJob).where(TrainingJob.status == "succeeded")
    ) or 0
    return round(ok / total, 4)


def recent_jobs(db: Session, limit: int = 5) -> list[TrainingJob]:
    stmt = select(TrainingJob).order_by(TrainingJob.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())
