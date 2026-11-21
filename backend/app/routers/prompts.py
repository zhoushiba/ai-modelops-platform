"""Prompt 模板与 A/B 实验接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import serializers
from app.crud import prompts as prompt_crud
from app.database import get_db
from app.deps import get_current_user
from app.errors import ConflictError, NotFoundError, envelope
from app.models import PromptTemplate, User
from app.schemas import (
    ExperimentCreate,
    ExperimentScore,
    PromptTemplateCreate,
    PromptTemplateUpdate,
    RenderRequest,
)
from app.services import prompt_engine

router = APIRouter(prefix="/prompts", tags=["Prompt 实验"])


def _apply_variables(template: PromptTemplate, explicit: list[str] | None) -> None:
    """变量集合：优先使用前端显式传入，否则从模板内容自动抽取。"""
    if explicit:
        template.variables_json = list(dict.fromkeys(explicit))
    else:
        template.variables_json = prompt_engine.extract_variables(template.content)


@router.get("")
def list_templates(
    q: str = Query(""), db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """列出 Prompt 模板。"""
    items = prompt_crud.list_templates(db, q=q)
    return envelope({"items": [serializers.prompt_template(item) for item in items]})


@router.post("")
def create_template(
    payload: PromptTemplateCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """新建模板（变量自动从 ``{{name}}`` 抽取）。"""
    if prompt_crud.get_by_name(db, payload.name.strip()) is not None:
        raise ConflictError(f"Prompt 模板 '{payload.name}' 已存在")
    template = PromptTemplate(
        name=payload.name.strip(),
        description=payload.description,
        content=payload.content,
        tags=payload.tags,
        version=1,
    )
    _apply_variables(template, payload.variables)
    db.add(template)
    db.commit()
    db.refresh(template)
    return envelope(serializers.prompt_template(template))


# 实验相关路由必须声明在 /{template_id} 之前
@router.get("/experiments")
def list_experiments(
    template_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """列出 A/B 实验记录。"""
    items = prompt_crud.list_experiments(db, template_id=template_id)
    return envelope({"items": [serializers.experiment(item) for item in items]})


@router.post("/experiments")
def create_experiment(
    payload: ExperimentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """运行一次 A/B：两个模板分别渲染并生成，记录耗时与输出。"""
    template_a = prompt_engine.get_template_or_404(db, payload.template_a_id)
    template_b = prompt_engine.get_template_or_404(db, payload.template_b_id)
    experiment = prompt_engine.run_experiment(
        db,
        name=payload.name,
        template_a=template_a,
        template_b=template_b,
        input_text=payload.input_text,
        variables=payload.variables,
        created_by=user.username,
    )
    return envelope(serializers.experiment(experiment))


@router.get("/experiments/{experiment_id}")
def get_experiment(
    experiment_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """实验详情。"""
    experiment = prompt_crud.get_experiment(db, experiment_id)
    if experiment is None:
        raise NotFoundError("实验记录不存在")
    return envelope(serializers.experiment(experiment))


@router.post("/experiments/{experiment_id}/score")
def score_experiment(
    experiment_id: int,
    payload: ExperimentScore,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """人工打分（1-5 分）。"""
    experiment = prompt_crud.get_experiment(db, experiment_id)
    if experiment is None:
        raise NotFoundError("实验记录不存在")
    experiment = prompt_engine.score_experiment(
        db, experiment, payload.score_a, payload.score_b, payload.notes
    )
    return envelope(serializers.experiment(experiment))


@router.get("/{template_id}")
def get_template(
    template_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """模板详情。"""
    template = prompt_crud.get_template(db, template_id)
    if template is None:
        raise NotFoundError("Prompt 模板不存在")
    return envelope(serializers.prompt_template(template))


@router.put("/{template_id}")
def update_template(
    template_id: int,
    payload: PromptTemplateUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """更新模板（内容变更时 version+1 并重新抽取变量）。"""
    template = prompt_crud.get_template(db, template_id)
    if template is None:
        raise NotFoundError("Prompt 模板不存在")
    if payload.name and payload.name != template.name:
        if prompt_crud.get_by_name(db, payload.name.strip()) is not None:
            raise ConflictError(f"Prompt 模板 '{payload.name}' 已存在")
        template.name = payload.name.strip()
    content_changed = payload.content is not None and payload.content != template.content
    if payload.description is not None:
        template.description = payload.description
    if payload.tags is not None:
        template.tags = payload.tags
    if payload.content is not None:
        template.content = payload.content
    if payload.variables is not None:
        _apply_variables(template, payload.variables)
    elif content_changed:
        _apply_variables(template, None)
    if content_changed:
        template.version = (template.version or 1) + 1
    db.commit()
    db.refresh(template)
    return envelope(serializers.prompt_template(template))


@router.delete("/{template_id}")
def delete_template(
    template_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """删除模板。"""
    template = prompt_crud.get_template(db, template_id)
    if template is None:
        raise NotFoundError("Prompt 模板不存在")
    db.delete(template)
    db.commit()
    return envelope({"deleted": template_id})


@router.post("/{template_id}/render")
def render_template(
    template_id: int,
    payload: RenderRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """渲染模板并返回缺失变量（前端实时预览用）。"""
    template = prompt_crud.get_template(db, template_id)
    if template is None:
        raise NotFoundError("Prompt 模板不存在")
    rendered, missing = prompt_engine.render(template.content, payload.variables)
    return envelope({"rendered": rendered, "missing_variables": missing})
