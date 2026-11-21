"""Prompt 模板与 A/B 实验查询。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import PromptExperiment, PromptTemplate


def list_templates(db: Session, q: str = "") -> list[PromptTemplate]:
    stmt = select(PromptTemplate).order_by(PromptTemplate.id.desc())
    if q:
        stmt = stmt.where(PromptTemplate.name.like(f"%{q}%"))
    return list(db.scalars(stmt).all())


def get_template(db: Session, template_id: int) -> PromptTemplate | None:
    return db.get(PromptTemplate, template_id)


def get_by_name(db: Session, name: str) -> PromptTemplate | None:
    return db.scalars(select(PromptTemplate).where(PromptTemplate.name == name)).first()


def list_experiments(db: Session, template_id: int | None = None) -> list[PromptExperiment]:
    stmt = (
        select(PromptExperiment)
        .order_by(PromptExperiment.id.desc())
        .options(
            selectinload(PromptExperiment.template_a), selectinload(PromptExperiment.template_b)
        )
    )
    if template_id:
        stmt = stmt.where(
            (PromptExperiment.template_a_id == template_id)
            | (PromptExperiment.template_b_id == template_id)
        )
    return list(db.scalars(stmt).all())


def get_experiment(db: Session, experiment_id: int) -> PromptExperiment | None:
    stmt = (
        select(PromptExperiment)
        .where(PromptExperiment.id == experiment_id)
        .options(
            selectinload(PromptExperiment.template_a), selectinload(PromptExperiment.template_b)
        )
    )
    return db.scalars(stmt).first()
