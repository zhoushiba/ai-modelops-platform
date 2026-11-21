"""部署（在线推理服务）业务逻辑：创建、启停、统计。"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.crud import deployments as deployment_crud
from app.crud import models as model_crud
from app.errors import AppError, ConflictError, NotFoundError
from app.models import Deployment, InferenceLog, UsageRecord, utcnow
from app.services import registry_service
from app.services.runtime import ModelRuntime, runtime_manager

logger = logging.getLogger(__name__)


def create_deployment(
    db: Session,
    *,
    model_version_id: int,
    name: str,
    alias: str,
    qps_limit: int,
    description: str,
    created_by: str,
) -> Deployment:
    version = model_crud.get_version_detail(db, model_version_id)
    if version is None:
        raise NotFoundError("模型版本不存在")
    registry_service.ensure_artifact(version)
    if deployment_crud.get_by_name(db, name) is not None:
        raise ConflictError(f"部署名称 '{name}' 已存在")
    if alias and deployment_crud.get_by_alias(db, alias) is not None:
        raise ConflictError(f"模型别名 '{alias}' 已被其他运行中的部署占用")

    deployment = Deployment(
        name=name,
        model_version_id=version.id,
        alias=alias or "",
        status="starting",
        qps_limit=max(1, qps_limit),
        description=description,
        created_by=created_by,
        created_at=utcnow(),
    )
    db.add(deployment)
    db.commit()
    db.refresh(deployment)

    try:
        runtime = ModelRuntime(version).load(db)
    except Exception as exc:  # noqa: BLE001
        deployment.status = "failed"
        deployment.last_error = f"加载模型失败：{exc}"
        db.commit()
        logger.warning("部署启动失败 deployment=%s：%s", deployment.id, exc)
        raise AppError(f"加载模型失败：{exc}", code=50010, status_code=500) from exc

    runtime_manager.put(deployment.id, runtime)
    deployment.status = "running"
    deployment.started_at = utcnow()
    deployment.stopped_at = None
    deployment.last_error = ""
    db.commit()
    db.refresh(deployment)
    logger.info("部署已启动 id=%s name=%s version=%s", deployment.id, deployment.name, version.id)
    return deployment


def start_deployment(db: Session, deployment: Deployment) -> Deployment:
    if deployment.status == "running":
        return deployment
    version = model_crud.get_version_detail(db, deployment.model_version_id)
    if version is None:
        raise NotFoundError("模型版本不存在")
    registry_service.ensure_artifact(version)
    try:
        runtime_manager.put(deployment.id, ModelRuntime(version).load(db))
    except Exception as exc:  # noqa: BLE001
        deployment.status = "failed"
        deployment.last_error = f"加载模型失败：{exc}"
        db.commit()
        raise AppError(f"启动失败：{exc}", code=50010, status_code=500) from exc
    deployment.status = "running"
    deployment.started_at = utcnow()
    deployment.stopped_at = None
    deployment.last_error = ""
    db.commit()
    db.refresh(deployment)
    return deployment


def stop_deployment(db: Session, deployment: Deployment) -> Deployment:
    if deployment.status == "stopped":
        return deployment
    runtime_manager.evict(deployment.id)
    deployment.status = "stopped"
    deployment.stopped_at = utcnow()
    db.commit()
    db.refresh(deployment)
    return deployment


def delete_deployment(db: Session, deployment: Deployment) -> None:
    runtime_manager.evict(deployment.id)
    db.delete(deployment)
    db.commit()


def stats(db: Session, deployment: Deployment) -> dict:
    """QPS / 平均延迟 / 24 小时调用量统计。"""
    since = utcnow() - timedelta(minutes=1)
    qps = db.scalar(
        select(func.count())
        .select_from(UsageRecord)
        .where(UsageRecord.deployment_id == deployment.id, UsageRecord.created_at >= since)
    ) or 0
    avg_latency = (
        round(deployment.total_latency_ms / deployment.request_count, 2)
        if deployment.request_count
        else 0.0
    )
    errors_24h = db.scalar(
        select(func.count())
        .select_from(InferenceLog)
        .where(
            InferenceLog.deployment_id == deployment.id,
            InferenceLog.status_code >= 400,
            InferenceLog.created_at >= utcnow() - timedelta(hours=24),
        )
    ) or 0
    total_24h = db.scalar(
        select(func.count())
        .select_from(InferenceLog)
        .where(
            InferenceLog.deployment_id == deployment.id,
            InferenceLog.created_at >= utcnow() - timedelta(hours=24),
        )
    ) or 0
    return {
        "deployment_id": deployment.id,
        "status": deployment.status,
        "qps_last_minute": qps / 60.0,
        "requests_last_minute": int(qps),
        "request_count": deployment.request_count,
        "error_count": deployment.error_count,
        "avg_latency_ms": avg_latency,
        "requests_24h": int(total_24h),
        "errors_24h": int(errors_24h),
        "error_rate_24h": round(errors_24h / total_24h, 4) if total_24h else 0.0,
        "runtime_loaded": runtime_manager.is_loaded(deployment.id),
        "started_at": deployment.started_at,
        "stopped_at": deployment.stopped_at,
        "last_error": deployment.last_error,
    }
