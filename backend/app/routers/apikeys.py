"""API Key 与用量接口：创建（明文只返回一次）、启停、删除、用量汇总、调用日志。"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import serializers
from app.crud import keys as key_crud
from app.database import get_db
from app.deps import get_current_user
from app.errors import NotFoundError, envelope
from app.models import ApiKey, Deployment, UsageRecord, User, utcnow
from app.schemas import ApiKeyCreate

router = APIRouter(tags=["API Key 与用量"])


class ApiKeyUpdate(BaseModel):
    """API Key 的可更新字段（配额/限流/启停）。"""

    active: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=128)
    rate_limit_per_min: int | None = Field(default=None, ge=1, le=100_000)
    burst: int | None = Field(default=None, ge=1, le=10_000)
    token_quota: int | None = Field(default=None, ge=1)


@router.get("/api-keys")
def list_keys(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    """列出所有 API Key（只返回前缀，不返回明文与哈希）。"""
    items = key_crud.list_keys(db)
    return envelope({"items": [serializers.api_key(item) for item in items]})


@router.post("/api-keys")
def create_key(
    payload: ApiKeyCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """创建 API Key：数据库只保存 SHA-256 哈希，明文仅在本次响应中返回一次。"""
    from app.security import generate_api_key

    raw, prefix, key_hash = generate_api_key()
    key = ApiKey(
        name=payload.name.strip(),
        prefix=prefix,
        key_hash=key_hash,
        scopes_json=payload.scopes,
        rate_limit_per_min=payload.rate_limit_per_min,
        burst=payload.burst,
        token_quota=payload.token_quota,
        active=True,
        owner_id=user.id,
        created_at=utcnow(),
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return envelope(serializers.api_key(key, plain_key=raw))


@router.patch("/api-keys/{key_id}")
def update_key(
    key_id: int,
    payload: ApiKeyUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """更新配额、限流参数或启停 Key。"""
    key = key_crud.get_key(db, key_id)
    if key is None:
        raise NotFoundError("API Key 不存在")
    for field in ("active", "name", "rate_limit_per_min", "burst", "token_quota"):
        value = getattr(payload, field)
        if value is not None:
            setattr(key, field, value)
    db.commit()
    db.refresh(key)
    return envelope(serializers.api_key(key))


@router.delete("/api-keys/{key_id}")
def delete_key(
    key_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """删除 API Key（历史用量记录保留，仅解除引用）。"""
    key = key_crud.get_key(db, key_id)
    if key is None:
        raise NotFoundError("API Key 不存在")
    db.query(UsageRecord).filter(UsageRecord.api_key_id == key.id).update({"api_key_id": None})
    db.delete(key)
    db.commit()
    return envelope({"deleted": key_id})


@router.get("/usage/summary")
def usage_summary(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """按天/接口/Key/模型聚合的用量汇总。"""
    return envelope(key_crud.usage_summary(db, days=days))


@router.get("/usage/logs")
def usage_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    endpoint: str = Query(""),
    status_code: int | None = Query(None),
    q: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """调用日志（分页，可按接口/状态码/关键字过滤）。"""
    items, total = key_crud.list_inference_logs(
        db, page=page, size=size, status_code=status_code, endpoint=endpoint, q=q
    )
    deployment_names = {item.deployment_id for item in items if item.deployment_id}
    key_ids = {item.api_key_id for item in items if item.api_key_id}
    deployments = (
        {dep.id: dep.name for dep in db.query(Deployment).filter(Deployment.id.in_(deployment_names)).all()}
        if deployment_names
        else {}
    )
    keys = {key.id: key.name for key in db.query(ApiKey).filter(ApiKey.id.in_(key_ids)).all()} if key_ids else {}
    payload = [
        serializers.inference_log(
            item, key_name=keys.get(item.api_key_id, ""), deployment_name=deployments.get(item.deployment_id, "")
        )
        for item in items
    ]
    return envelope({"items": payload, "total": total, "page": page, "size": size})


@router.get("/usage/recent")
def usage_recent(
    limit: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """最近调用（看板用）。"""
    items = key_crud.recent_logs(db, limit=limit)
    return envelope({"items": [serializers.inference_log(item) for item in items]})


@router.get("/usage/today")
def usage_today(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    """今日调用量/Token/错误率/平均延迟。"""
    requests, tokens, error_rate, avg_latency = key_crud.usage_today(db)
    return envelope(
        {
            "requests": requests,
            "tokens": tokens,
            "error_rate": error_rate,
            "avg_latency_ms": avg_latency,
            "generated_at": (utcnow() + timedelta(seconds=0)).isoformat(),
        }
    )
