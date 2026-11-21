"""评测集与评测执行查询。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import EvalDataset, EvalResult, EvalRun


def list_eval_datasets(db: Session) -> list[EvalDataset]:
    return list(db.scalars(select(EvalDataset).order_by(EvalDataset.id.desc())).all())


def get_eval_dataset(db: Session, dataset_id: int) -> EvalDataset | None:
    return db.get(EvalDataset, dataset_id)


def get_by_name(db: Session, name: str) -> EvalDataset | None:
    return db.scalars(select(EvalDataset).where(EvalDataset.name == name)).first()


def list_runs(db: Session, model_version_id: int | None = None) -> list[EvalRun]:
    stmt = select(EvalRun).order_by(EvalRun.id.desc()).options(selectinload(EvalRun.model_version))
    if model_version_id:
        stmt = stmt.where(EvalRun.model_version_id == model_version_id)
    return list(db.scalars(stmt).all())


def get_run(db: Session, run_id: int) -> EvalRun | None:
    return db.get(EvalRun, run_id)


def get_run_detail(db: Session, run_id: int) -> EvalRun | None:
    stmt = (
        select(EvalRun)
        .where(EvalRun.id == run_id)
        .options(
            selectinload(EvalRun.results),
            selectinload(EvalRun.model_version),
            selectinload(EvalRun.eval_dataset),
        )
    )
    return db.scalars(stmt).first()


def list_results(db: Session, run_id: int, only_errors: bool = False, limit: int = 500) -> list[EvalResult]:
    stmt = select(EvalResult).where(EvalResult.run_id == run_id).order_by(EvalResult.sample_index)
    if only_errors:
        stmt = stmt.where(EvalResult.correct.is_(False))
    return list(db.scalars(stmt.limit(limit)).all())


def count_runs(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(EvalRun)) or 0
