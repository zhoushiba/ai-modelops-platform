"""评测接口：评测集上传、发起评测、结果明细、多版本对比。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import serializers
from app.crud import evals as eval_crud
from app.crud import models as model_crud
from app.database import get_db
from app.deps import get_current_user
from app.errors import NotFoundError, envelope
from app.models import EvalRun, User
from app.schemas import EvalRunCreate
from app.services import eval_service

router = APIRouter(prefix="/evals", tags=["评测"])


class CompareRequest(BaseModel):
    """多版本对比请求。"""

    run_ids: list[int] = Field(min_length=2, max_length=8)


@router.get("/datasets")
def list_eval_datasets(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """列出评测集。"""
    items = eval_crud.list_eval_datasets(db)
    return envelope({"items": [serializers.eval_dataset(item) for item in items]})


@router.post("/datasets")
async def create_eval_dataset(
    name: str = Form(...),
    description: str = Form(""),
    task_type: str = Form("text_classification"),
    text_field: str = Form("text"),
    label_field: str = Form("label"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """上传带标注的 CSV/JSONL 作为评测集（不会进入训练集）。"""
    raw = await file.read()
    dataset = eval_service.create_eval_dataset(
        db,
        name=name.strip(),
        description=description,
        task_type=task_type,
        text_field=text_field,
        label_field=label_field,
        filename=file.filename or "eval.csv",
        raw=raw,
    )
    return envelope(serializers.eval_dataset(dataset))


@router.get("/runs")
def list_runs(
    model_version_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """列出评测记录（可按模型版本过滤）。"""
    items = eval_crud.list_runs(db, model_version_id=model_version_id)
    return envelope({"items": [serializers.eval_run(item) for item in items]})


@router.post("/runs")
def create_run(
    payload: EvalRunCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """对指定模型版本跑一次离线评测（同步执行，样本量受限）。"""
    version = model_crud.get_version(db, payload.model_version_id)
    if version is None:
        raise NotFoundError("模型版本不存在")
    dataset = eval_crud.get_eval_dataset(db, payload.eval_dataset_id)
    if dataset is None:
        raise NotFoundError("评测集不存在")
    run = EvalRun(
        name=payload.name or f"{version.registry.name if version.registry else 'model'}-v{version.version} 评测",
        model_version_id=version.id,
        eval_dataset_id=dataset.id,
        status="pending",
        config_json={"max_samples": payload.max_samples},
        created_by=user.username,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run = eval_service.run_evaluation(db, run)
    return envelope(serializers.eval_run(run))


@router.get("/runs/{run_id}")
def get_run(
    run_id: int,
    include_results: bool = Query(True),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """评测详情（含逐条预测结果）。"""
    run = eval_crud.get_run_detail(db, run_id)
    if run is None:
        raise NotFoundError("评测记录不存在")
    data = serializers.eval_run(run)
    if include_results:
        results = eval_crud.list_results(db, run_id)
        data["results"] = [serializers.eval_result(item) for item in results]
    return envelope(data)


@router.post("/compare")
def compare(
    payload: CompareRequest, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """多版本指标对比（表格 + 差值）。"""
    result = eval_service.compare_runs(db, payload.run_ids)
    result["runs"] = [serializers.eval_run(run) for run in result["runs"]]
    return envelope(result)
