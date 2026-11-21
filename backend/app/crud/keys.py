"""API Key、用量与调用日志查询。"""

from __future__ import annotations

from datetime import datetime, timedelta

from collections import defaultdict

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import ApiKey, InferenceLog, UsageRecord, utcnow


def get_key(db: Session, key_id: int) -> ApiKey | None:
    return db.get(ApiKey, key_id)


def get_key_by_hash(db: Session, key_hash: str) -> ApiKey | None:
    return db.scalars(select(ApiKey).where(ApiKey.key_hash == key_hash)).first()


def list_keys(db: Session) -> list[ApiKey]:
    return list(db.scalars(select(ApiKey).order_by(ApiKey.id.desc())).all())


def count_keys(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.active.is_(True))) or 0


def record_usage(
    db: Session,
    *,
    key: ApiKey | None,
    deployment_id: int | None,
    endpoint: str,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    status_code: int,
    latency_ms: float,
) -> UsageRecord:
    """写入一条用量流水，并累加 Key 计数（同一个事务）。"""
    record = UsageRecord(
        api_key_id=key.id if key else None,
        deployment_id=deployment_id,
        endpoint=endpoint,
        model_name=model_name,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        status_code=status_code,
        latency_ms=round(latency_ms, 2),
    )
    db.add(record)
    if key is not None:
        key.tokens_used += prompt_tokens + completion_tokens
        key.requests_used += 1
        key.last_used_at = utcnow()
    db.commit()
    return record


def write_inference_log(
    db: Session,
    *,
    trace_id: str,
    key: ApiKey | None,
    deployment_id: int | None,
    endpoint: str,
    model_name: str,
    status_code: int,
    latency_ms: float,
    prompt_preview: str,
    response_preview: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    error: str = "",
) -> InferenceLog:
    log = InferenceLog(
        trace_id=trace_id,
        api_key_id=key.id if key else None,
        deployment_id=deployment_id,
        endpoint=endpoint,
        model_name=model_name,
        status_code=status_code,
        latency_ms=round(latency_ms, 2),
        prompt_preview=prompt_preview[:500],
        response_preview=response_preview[:500],
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        error=error[:1000],
    )
    db.add(log)
    db.commit()
    return log


def usage_summary(db: Session, days: int = 7) -> dict:
    """按天/接口/Key/模型聚合用量，供看板与用量页使用。"""
    since = utcnow() - timedelta(days=days)
    totals = db.execute(
        select(
            func.count(UsageRecord.id),
            func.coalesce(func.sum(UsageRecord.total_tokens), 0),
            func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
            func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
            func.coalesce(func.sum(UsageRecord.latency_ms), 0.0),
        ).where(UsageRecord.created_at >= since)
    ).one()
    errors = db.scalar(
        select(func.count())
        .select_from(UsageRecord)
        .where(UsageRecord.created_at >= since, UsageRecord.status_code >= 400)
    ) or 0
    total_requests = int(totals[0] or 0)

    day_rows = db.execute(
        select(
            func.date(UsageRecord.created_at),
            func.count(UsageRecord.id),
            func.coalesce(func.sum(UsageRecord.total_tokens), 0),
            func.coalesce(func.sum(UsageRecord.latency_ms), 0.0),
        )
        .where(UsageRecord.created_at >= since)
        .group_by(func.date(UsageRecord.created_at))
        .order_by(func.date(UsageRecord.created_at))
    ).all()

    endpoint_rows = db.execute(
        select(UsageRecord.endpoint, func.count(UsageRecord.id))
        .where(UsageRecord.created_at >= since)
        .group_by(UsageRecord.endpoint)
    ).all()

    key_rows = db.execute(
        select(ApiKey.name, func.count(UsageRecord.id), func.coalesce(func.sum(UsageRecord.total_tokens), 0))
        .join(ApiKey, ApiKey.id == UsageRecord.api_key_id)
        .where(UsageRecord.created_at >= since)
        .group_by(ApiKey.name)
    ).all()

    model_rows = db.execute(
        select(UsageRecord.model_name, func.count(UsageRecord.id), func.coalesce(func.sum(UsageRecord.total_tokens), 0))
        .where(UsageRecord.created_at >= since)
        .group_by(UsageRecord.model_name)
    ).all()

    return {
        "total_requests": total_requests,
        "total_tokens": int(totals[1] or 0),
        "prompt_tokens": int(totals[2] or 0),
        "completion_tokens": int(totals[3] or 0),
        "error_requests": errors,
        "error_rate": round(errors / total_requests, 4) if total_requests else 0.0,
        "avg_latency_ms": round(float(totals[4] or 0) / total_requests, 2) if total_requests else 0.0,
        "by_day": [
            {"date": str(row[0]), "requests": int(row[1]), "tokens": int(row[2]), "avg_latency_ms": round(float(row[3]) / max(int(row[1]), 1), 2)}
            for row in day_rows
        ],
        "by_endpoint": [{"endpoint": row[0], "requests": int(row[1])} for row in endpoint_rows],
        "by_key": [{"name": row[0], "requests": int(row[1]), "tokens": int(row[2])} for row in key_rows],
        "by_model": [{"model": row[0], "requests": int(row[1]), "tokens": int(row[2])} for row in model_rows],
    }


def usage_today(db: Session) -> tuple[int, int, float, float]:
    """返回今天（UTC 日期）的 (调用数, tokens, 错误率, 平均延迟)。"""
    start = datetime(utcnow().year, utcnow().month, utcnow().day)
    rows = db.execute(
        select(
            func.count(UsageRecord.id),
            func.coalesce(func.sum(UsageRecord.total_tokens), 0),
            func.coalesce(func.sum(UsageRecord.latency_ms), 0.0),
            func.coalesce(func.sum(case((UsageRecord.status_code >= 400, 1), else_=0)), 0),
        ).where(UsageRecord.created_at >= start)
    ).one()
    total = int(rows[0] or 0)
    errors = int(rows[3] or 0)
    return (
        total,
        int(rows[1] or 0),
        round(errors / total, 4) if total else 0.0,
        round(float(rows[2] or 0) / total, 2) if total else 0.0,
    )


def list_inference_logs(
    db: Session,
    *,
    page: int = 1,
    size: int = 20,
    status_code: int | None = None,
    endpoint: str = "",
    q: str = "",
) -> tuple[list[InferenceLog], int]:
    stmt = select(InferenceLog).order_by(InferenceLog.id.desc())
    if status_code is not None:
        stmt = stmt.where(InferenceLog.status_code == status_code)
    if endpoint:
        stmt = stmt.where(InferenceLog.endpoint == endpoint)
    if q:
        stmt = stmt.where(
            InferenceLog.prompt_preview.like(f"%{q}%")
            | InferenceLog.trace_id.like(f"%{q}%")
            | InferenceLog.model_name.like(f"%{q}%")
        )
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = list(db.scalars(stmt.offset((page - 1) * size).limit(size)).all())
    return items, int(total)


def recent_logs(db: Session, limit: int = 5) -> list[InferenceLog]:
    return list(db.scalars(select(InferenceLog).order_by(InferenceLog.id.desc()).limit(limit)).all())


def deployment_timeseries(db: Session, deployment_id: int, hours: int = 24) -> list[dict]:
    """按小时聚合某个部署的调用量与延迟（最近 N 小时）。

    为了同时兼容 SQLite / MySQL / PostgreSQL，这里把按小时分桶放在
    Python 侧完成（数据量：单部署 24 小时内的调用流水）。
    """
    since = utcnow() - timedelta(hours=hours)
    rows = db.execute(
        select(UsageRecord.created_at, UsageRecord.latency_ms, UsageRecord.status_code).where(
            UsageRecord.deployment_id == deployment_id, UsageRecord.created_at >= since
        )
    ).all()
    buckets: dict[str, dict] = defaultdict(lambda: {"requests": 0, "latency": 0.0, "errors": 0})
    for created_at, latency, status_code in rows:
        key = created_at.strftime("%Y-%m-%d %H:00")
        bucket = buckets[key]
        bucket["requests"] += 1
        bucket["latency"] += float(latency or 0.0)
        if status_code >= 400:
            bucket["errors"] += 1
    return [
        {
            "hour": hour,
            "requests": data["requests"],
            "avg_latency_ms": round(data["latency"] / max(data["requests"], 1), 2),
            "errors": data["errors"],
        }
        for hour, data in sorted(buckets.items())
    ]
