"""模型注册表查询。"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Deployment, ModelRegistry, ModelVersion


def get_registry(db: Session, registry_id: int) -> ModelRegistry | None:
    return db.get(ModelRegistry, registry_id)


def get_registry_detail(db: Session, registry_id: int) -> ModelRegistry | None:
    stmt = (
        select(ModelRegistry)
        .where(ModelRegistry.id == registry_id)
        .options(selectinload(ModelRegistry.versions))
    )
    return db.scalars(stmt).first()


def get_registry_by_name(db: Session, name: str) -> ModelRegistry | None:
    return db.scalars(select(ModelRegistry).where(ModelRegistry.name == name)).first()


def list_registries(
    db: Session, q: str = "", task_type: str = "", page: int = 1, size: int = 20
) -> tuple[list[ModelRegistry], int]:
    """分页列出模型注册表（带名称/任务类型过滤，按 id 倒序）。"""
    stmt = select(ModelRegistry).order_by(ModelRegistry.id.desc())
    if q:
        stmt = stmt.where(
            or_(ModelRegistry.name.like(f"%{q}%"), ModelRegistry.description.like(f"%{q}%"))
        )
    if task_type:
        stmt = stmt.where(ModelRegistry.task_type == task_type)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    stmt = stmt.options(selectinload(ModelRegistry.versions))
    items = list(db.scalars(stmt.offset((page - 1) * size).limit(size)).all())
    return items, int(total)


def next_version_no(db: Session, registry_id: int) -> int:
    current = db.scalar(
        select(func.max(ModelVersion.version)).where(ModelVersion.registry_id == registry_id)
    )
    return int(current or 0) + 1


def get_version(db: Session, version_id: int) -> ModelVersion | None:
    return db.get(ModelVersion, version_id)


def get_version_detail(db: Session, version_id: int) -> ModelVersion | None:
    stmt = (
        select(ModelVersion)
        .where(ModelVersion.id == version_id)
        .options(selectinload(ModelVersion.registry))
    )
    return db.scalars(stmt).first()


def get_version_by_number(db: Session, registry_id: int, version: int) -> ModelVersion | None:
    stmt = select(ModelVersion).where(
        ModelVersion.registry_id == registry_id, ModelVersion.version == version
    )
    return db.scalars(stmt).first()


def list_versions(db: Session, registry_id: int) -> list[ModelVersion]:
    stmt = (
        select(ModelVersion)
        .where(ModelVersion.registry_id == registry_id)
        .order_by(ModelVersion.version.desc())
    )
    return list(db.scalars(stmt).all())


def count_models(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(ModelRegistry)) or 0


def count_production(db: Session) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(ModelVersion).where(ModelVersion.status == "production")
        )
        or 0
    )


def deployment_count(db: Session, version_id: int) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(Deployment).where(Deployment.model_version_id == version_id)
        )
        or 0
    )
