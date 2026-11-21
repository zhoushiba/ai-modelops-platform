"""部署（在线服务）查询。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Deployment


def get_deployment(db: Session, deployment_id: int) -> Deployment | None:
    return db.get(Deployment, deployment_id)


def get_deployment_detail(db: Session, deployment_id: int) -> Deployment | None:
    stmt = (
        select(Deployment)
        .where(Deployment.id == deployment_id)
        .options(selectinload(Deployment.model_version))
    )
    return db.scalars(stmt).first()


def get_by_name(db: Session, name: str) -> Deployment | None:
    return db.scalars(select(Deployment).where(Deployment.name == name)).first()


def get_by_alias(db: Session, alias: str) -> Deployment | None:
    stmt = select(Deployment).where(Deployment.alias == alias, Deployment.status == "running").limit(1)
    return db.scalars(stmt).first()


def list_deployments(db: Session, status: str = "") -> list[Deployment]:
    stmt = select(Deployment).order_by(Deployment.id.desc())
    if status:
        stmt = stmt.where(Deployment.status == status)
    return list(db.scalars(stmt).all())


def list_running(db: Session) -> list[Deployment]:
    return list(db.scalars(select(Deployment).where(Deployment.status == "running")).all())


def count_deployments(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Deployment)) or 0


def count_running(db: Session) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(Deployment).where(Deployment.status == "running")
        )
        or 0
    )
