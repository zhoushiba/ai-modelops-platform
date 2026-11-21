"""模型注册表接口：模型列表、版本详情、状态流转（发布/回滚）、Model Card。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import serializers
from app.crud import models as model_crud
from app.database import get_db
from app.deps import get_current_user
from app.errors import NotFoundError, envelope
from app.models import User
from app.schemas import ModelVersionStatusUpdate
from app.services import registry_service

router = APIRouter(prefix="/models", tags=["模型注册表"])


class RollbackRequest(BaseModel):
    """回滚请求体。"""

    to_version: int | None = None


@router.get("")
def list_models(
    q: str = Query(""),
    task_type: str = Query(""),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """分页列出模型注册表（含生产版本与最佳指标）。"""
    items, total = model_crud.list_registries(db, q=q, task_type=task_type, page=page, size=size)
    return envelope(
        {
            "items": [serializers.registry(db, item) for item in items],
            "total": total,
            "page": page,
            "size": size,
        }
    )


# 注意：静态前缀路由必须声明在 /{registry_id} 之前
@router.get("/versions/{version_id}")
def get_version(
    version_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """模型版本详情（指标、超参、血缘、产物哈希）。"""
    version = model_crud.get_version_detail(db, version_id)
    if version is None:
        raise NotFoundError("模型版本不存在")
    data = serializers.model_version(db, version)
    data["training_job"] = None
    if version.training_job is not None:
        data["training_job"] = serializers.job(db, version.training_job)
    return envelope(data)


@router.patch("/versions/{version_id}/status")
def update_status(
    version_id: int,
    payload: ModelVersionStatusUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """切换版本状态：staging / production / archived（production 唯一）。"""
    version = model_crud.get_version_detail(db, version_id)
    if version is None:
        raise NotFoundError("模型版本不存在")
    version = registry_service.set_status(db, version, payload.status, payload.note)
    return envelope(serializers.model_version(db, version))


@router.get("/versions/{version_id}/card")
def get_model_card(
    version_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """返回 Model Card（Markdown 原文）。"""
    version = model_crud.get_version_detail(db, version_id)
    if version is None:
        raise NotFoundError("模型版本不存在")
    return envelope(
        {
            "model_version_id": version.id,
            "model_card": version.model_card_md or "（该版本暂未生成 Model Card）",
            "markdown": version.model_card_md or "（该版本暂未生成 Model Card）",
        }
    )


@router.get("/{registry_id}")
def get_registry(
    registry_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """模型详情：注册表信息 + 全部版本（倒序）。"""
    registry = model_crud.get_registry_detail(db, registry_id)
    if registry is None:
        raise NotFoundError("模型不存在")
    data = serializers.registry(db, registry)
    versions = model_crud.list_versions(db, registry_id)
    data["versions"] = [serializers.model_version(db, item) for item in versions]
    return envelope(data)


@router.post("/{registry_id}/rollback")
def rollback(
    registry_id: int,
    payload: RollbackRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """回滚：把指定版本（或上一个 production 版本）重新置为 production。"""
    registry = model_crud.get_registry_detail(db, registry_id)
    if registry is None:
        raise NotFoundError("模型不存在")
    to_version = payload.to_version if payload else None
    version = registry_service.rollback(db, registry, to_version)
    return envelope(
        {
            "registry": serializers.registry(db, registry),
            "model_version": serializers.model_version(db, version),
        }
    )


@router.get("/versions/{version_id}/metrics.json")
def metrics_json(
    version_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """以纯 JSON 返回版本指标（便于外部系统消费）。"""
    version = model_crud.get_version(db, version_id)
    if version is None:
        raise NotFoundError("模型版本不存在")
    payload = {
        "model": version.registry.name if version.registry else "",
        "version": version.version,
        "status": version.status,
        "metrics": version.metrics_json or {},
        "hyperparams": version.hyperparams_json or {},
        "artifact_sha256": version.artifact_sha256,
    }
    return envelope(json.loads(json.dumps(payload, ensure_ascii=False, default=str)))
