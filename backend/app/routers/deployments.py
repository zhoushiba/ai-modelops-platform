"""推理部署接口：一键部署、启停、删除、QPS/延迟统计与调用示例。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import serializers
from app.crud import deployments as deployment_crud
from app.crud import keys as key_crud
from app.database import get_db
from app.deps import get_current_user
from app.errors import NotFoundError, envelope
from app.models import Deployment, User
from app.schemas import DeploymentCreate
from app.services import deployment_service

router = APIRouter(prefix="/deployments", tags=["推理部署"])


def _curl_snippet(deployment: Deployment) -> str:
    """生成可直接复制的调用示例（脱敏，不含真实 Key）。"""
    model = deployment.alias or deployment.name
    return (
        f"curl -X POST http://127.0.0.1:8000/v1/chat/completions "
        f'-H "Content-Type: application/json" -H "Authorization: Bearer $MOPS_API_KEY" '
        f"-d '{{\"model\": \"{model}\", \"messages\": [{{\"role\": \"user\", \"content\": \"你好\"}}]}}'"
    )


@router.get("")
def list_deployments(
    status: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """列出推理服务（可按状态过滤）。"""
    items = deployment_crud.list_deployments(db, status=status)
    return envelope({"items": [serializers.deployment(db, item) for item in items]})


@router.post("")
def create_deployment(
    payload: DeploymentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """一键部署：加载模型产物到进程内运行时可立即对外提供 OpenAI 兼容接口。"""
    deployment = deployment_service.create_deployment(
        db,
        model_version_id=payload.model_version_id,
        name=payload.name.strip(),
        alias=payload.alias.strip(),
        qps_limit=payload.qps_limit,
        description=payload.description.strip(),
        created_by=user.username,
    )
    data = serializers.deployment(db, deployment)
    data["curl"] = _curl_snippet(deployment)
    return envelope(data)


@router.get("/{deployment_id}")
def get_deployment(
    deployment_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """部署详情（含调用示例）。"""
    deployment = deployment_crud.get_deployment_detail(db, deployment_id)
    if deployment is None:
        raise NotFoundError("推理服务不存在")
    data = serializers.deployment(db, deployment)
    data["curl"] = _curl_snippet(deployment)
    return envelope(data)


@router.post("/{deployment_id}/start")
def start_deployment(
    deployment_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """启动/重启推理服务。"""
    deployment = deployment_crud.get_deployment_detail(db, deployment_id)
    if deployment is None:
        raise NotFoundError("推理服务不存在")
    deployment = deployment_service.start_deployment(db, deployment)
    return envelope(serializers.deployment(db, deployment))


@router.post("/{deployment_id}/stop")
def stop_deployment(
    deployment_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """停止推理服务并释放运行时内存。"""
    deployment = deployment_crud.get_deployment_detail(db, deployment_id)
    if deployment is None:
        raise NotFoundError("推理服务不存在")
    deployment = deployment_service.stop_deployment(db, deployment)
    return envelope(serializers.deployment(db, deployment))


@router.delete("/{deployment_id}")
def delete_deployment(
    deployment_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """删除推理服务（先停止再删除记录）。"""
    deployment = deployment_crud.get_deployment_detail(db, deployment_id)
    if deployment is None:
        raise NotFoundError("推理服务不存在")
    deployment_service.delete_deployment(db, deployment)
    return envelope({"deleted": deployment_id})


@router.get("/{deployment_id}/stats")
def deployment_stats(
    deployment_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """QPS、错误率、平均/95 分位延迟与 24 小时序列。"""
    deployment = deployment_crud.get_deployment_detail(db, deployment_id)
    if deployment is None:
        raise NotFoundError("推理服务不存在")
    data = deployment_service.stats(db, deployment)
    data["series"] = key_crud.deployment_timeseries(db, deployment_id, hours=24)
    return envelope(data)


@router.get("/{deployment_id}/timeseries")
def deployment_timeseries(
    deployment_id: int,
    hours: int = Query(24, ge=1, le=168),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """按小时聚合的调用量/延迟/错误数（前端图表）。"""
    deployment = deployment_crud.get_deployment(db, deployment_id)
    if deployment is None:
        raise NotFoundError("推理服务不存在")
    return envelope({"items": key_crud.deployment_timeseries(db, deployment_id, hours=hours)})
