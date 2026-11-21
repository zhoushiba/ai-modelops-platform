"""看板接口：全局统计、近 7 天调用趋势。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import serializers
from app.crud import datasets as dataset_crud
from app.crud import deployments as deployment_crud
from app.crud import jobs as job_crud
from app.crud import keys as key_crud
from app.crud import models as model_crud
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.errors import envelope

router = APIRouter(prefix="/dashboard", tags=["看板"])


@router.get("/summary")
def summary(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    """看板核心指标：数据集/任务/模型/部署/调用量。"""
    calls_today, tokens_today, error_rate_today, avg_latency_today = key_crud.usage_today(db)
    payload = {
        "dataset_count": dataset_crud.count_datasets(db),
        "training_job_count": job_crud.count_jobs(db),
        "running_job_count": job_crud.count_running(db),
        "job_success_rate": job_crud.success_rate(db),
        "model_count": model_crud.count_models(db),
        "production_model_count": model_crud.count_production(db),
        "deployment_count": deployment_crud.count_deployments(db),
        "running_deployment_count": deployment_crud.count_running(db),
        "api_key_count": key_crud.count_keys(db),
        "calls_today": calls_today,
        "tokens_today": tokens_today,
        "error_rate_today": error_rate_today,
        "avg_latency_ms_today": avg_latency_today,
        "recent_jobs": [serializers.job(db, item) for item in job_crud.recent_jobs(db, limit=5)],
        "recent_calls": [serializers.inference_log(item) for item in key_crud.recent_logs(db, limit=5)],
    }
    return envelope(payload)


@router.get("/timeseries")
def timeseries(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """近 N 天调用量/Token/错误数（前端折线图）。"""
    summary_data = key_crud.usage_summary(db, days=days)
    points = [
        {
            "date": row.get("date", ""),
            "requests": int(row.get("requests") or 0),
            "tokens": int(row.get("tokens") or 0),
            "errors": int(row.get("errors") or 0),
        }
        for row in summary_data.get("by_day", [])
    ]
    return envelope({"items": points})
