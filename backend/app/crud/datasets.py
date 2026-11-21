"""数据集相关查询。"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Dataset, DatasetSample, DatasetVersion


def get_dataset(db: Session, dataset_id: int) -> Dataset | None:
    return db.get(Dataset, dataset_id)


def get_dataset_detail(db: Session, dataset_id: int) -> Dataset | None:
    stmt = select(Dataset).where(Dataset.id == dataset_id).options(selectinload(Dataset.versions))
    return db.scalars(stmt).first()


def get_dataset_by_name(db: Session, name: str) -> Dataset | None:
    return db.scalars(select(Dataset).where(Dataset.name == name)).first()


def list_datasets(
    db: Session, q: str = "", task_type: str = "", page: int = 1, size: int = 20
) -> tuple[list[Dataset], int]:
    stmt = select(Dataset).order_by(Dataset.id.desc())
    if q:
        stmt = stmt.where(or_(Dataset.name.like(f"%{q}%"), Dataset.description.like(f"%{q}%")))
    if task_type:
        stmt = stmt.where(Dataset.task_type == task_type)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = list(db.scalars(stmt.offset((page - 1) * size).limit(size)).all())
    return items, int(total)


def count_versions(db: Session, dataset_id: int) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id)
        )
        or 0
    )


def list_versions(db: Session, dataset_id: int) -> list[DatasetVersion]:
    stmt = (
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset_id)
        .order_by(DatasetVersion.version.desc())
    )
    return list(db.scalars(stmt).all())


def latest_version(db: Session, dataset_id: int) -> DatasetVersion | None:
    stmt = (
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset_id)
        .order_by(DatasetVersion.version.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def get_version(db: Session, version_id: int) -> DatasetVersion | None:
    return db.get(DatasetVersion, version_id)


def get_version_detail(db: Session, version_id: int) -> DatasetVersion | None:
    stmt = (
        select(DatasetVersion)
        .where(DatasetVersion.id == version_id)
        .options(selectinload(DatasetVersion.dataset))
    )
    return db.scalars(stmt).first()


def next_version_no(db: Session, dataset_id: int) -> int:
    current = db.scalar(
        select(func.max(DatasetVersion.version)).where(DatasetVersion.dataset_id == dataset_id)
    )
    return int(current or 0) + 1


def list_samples(
    db: Session, version_id: int, split: str = "", page: int = 1, size: int = 20
) -> tuple[list[DatasetSample], int]:
    stmt = (
        select(DatasetSample)
        .where(DatasetSample.version_id == version_id)
        .order_by(DatasetSample.row_index)
    )
    if split:
        stmt = stmt.where(DatasetSample.split == split)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = list(db.scalars(stmt.offset((page - 1) * size).limit(size)).all())
    return items, int(total)


def all_samples(db: Session, version_id: int, split: str = "") -> list[DatasetSample]:
    stmt = (
        select(DatasetSample)
        .where(DatasetSample.version_id == version_id)
        .order_by(DatasetSample.row_index)
    )
    if split:
        stmt = stmt.where(DatasetSample.split == split)
    return list(db.scalars(stmt).all())


def count_by_split(db: Session, version_id: int) -> dict[str, int]:
    rows = db.execute(
        select(DatasetSample.split, func.count())
        .where(DatasetSample.version_id == version_id)
        .group_by(DatasetSample.split)
    ).all()
    return {split: int(count) for split, count in rows}


def count_datasets(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Dataset)) or 0
