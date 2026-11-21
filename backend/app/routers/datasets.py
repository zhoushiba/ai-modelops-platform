"""数据集接口：上传、版本、样本预览、质量报告、版本 diff、导出。

路由约定：
* ``/datasets/**``：数据集维度操作；
* ``/dataset-versions/**``：版本维度操作（避免 ``/datasets/{id}`` 与 ``/datasets/versions`` 冲突）。
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import serializers
from app.crud import datasets as dataset_crud
from app.database import get_db
from app.deps import get_current_user
from app.errors import AppError, NotFoundError, envelope
from app.models import DatasetSample, User
from app.services import dataset_service

router = APIRouter(prefix="/datasets", tags=["数据集"])
version_router = APIRouter(prefix="/dataset-versions", tags=["数据集版本"])


def _page_payload(items: list, total: int, page: int, size: int) -> dict:
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("")
def list_datasets(
    q: str = Query("", description="名称模糊搜索"),
    task_type: str = Query("", description="任务类型过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """分页列出数据集。"""
    items, total = dataset_crud.list_datasets(db, q=q, task_type=task_type, page=page, size=size)
    return envelope(_page_payload([serializers.dataset(db, item) for item in items], total, page, size))


@router.post("")
async def create_dataset(
    name: str = Form(..., description="数据集名称，全局唯一"),
    description: str = Form(""),
    task_type: str = Form("text_classification"),
    text_field: str = Form("text"),
    label_field: str = Form("label"),
    split_field: str = Form(""),
    val_ratio: float = Form(0.2, ge=0.0, le=0.5),
    file: UploadFile = File(..., description="CSV / JSONL / JSON 文件"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """上传文件创建数据集（同时生成 v1 版本，含质量报告）。"""
    raw = await file.read()
    dataset, version = dataset_service.create_dataset(
        db,
        name=name.strip(),
        description=description,
        task_type=task_type,
        owner_id=user.id,
        filename=file.filename or "upload.csv",
        raw=raw,
        text_field=text_field,
        label_field=label_field,
        split_field=split_field,
        val_ratio=val_ratio,
        created_by=user.username,
    )
    return envelope(
        {
            "dataset": serializers.dataset(db, dataset),
            "version": serializers.dataset_version(version),
        }
    )


@router.get("/{dataset_id}")
def get_dataset(
    dataset_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """数据集详情（含全部版本）。"""
    dataset = dataset_crud.get_dataset_detail(db, dataset_id)
    if dataset is None:
        raise NotFoundError("数据集不存在")
    return envelope(serializers.dataset_detail(db, dataset))


@router.delete("/{dataset_id}")
def delete_dataset(
    dataset_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """删除数据集；已被训练任务引用时拒绝，避免破坏血缘。"""
    dataset = dataset_crud.get_dataset(db, dataset_id)
    if dataset is None:
        raise NotFoundError("数据集不存在")
    version_ids = [version.id for version in dataset.versions]
    if version_ids:
        from app.models import TrainingJob

        used = (
            db.query(TrainingJob)
            .filter(TrainingJob.dataset_version_id.in_(version_ids))
            .count()
        )
        if used:
            raise AppError(f"该数据集被 {used} 个训练任务引用，无法删除", code=40910, status_code=409)
    db.delete(dataset)
    db.commit()
    return envelope({"deleted": dataset_id})


@router.post("/{dataset_id}/versions")
async def add_version(
    dataset_id: int,
    note: str = Form(""),
    text_field: str = Form("text"),
    label_field: str = Form("label"),
    split_field: str = Form(""),
    val_ratio: float = Form(0.2, ge=0.0, le=0.5),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """追加新版本：新文件 -> 新版本号，自动与上一版做 diff。"""
    dataset = dataset_crud.get_dataset(db, dataset_id)
    if dataset is None:
        raise NotFoundError("数据集不存在")
    raw = await file.read()
    version = dataset_service.append_version(
        db,
        dataset=dataset,
        filename=file.filename or "upload.csv",
        raw=raw,
        text_field=text_field,
        label_field=label_field,
        split_field=split_field,
        val_ratio=val_ratio,
        created_by=user.username,
    )
    if note:
        version.diff_json = {**(version.diff_json or {}), "note": note}
        db.commit()
        db.refresh(version)
    return envelope(
        {
            "dataset": serializers.dataset(db, dataset),
            "version": serializers.dataset_version(version),
        }
    )


@router.get("/{dataset_id}/versions")
def list_versions(
    dataset_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """列出数据集的所有版本（倒序）。"""
    dataset = dataset_crud.get_dataset(db, dataset_id)
    if dataset is None:
        raise NotFoundError("数据集不存在")
    versions = dataset_crud.list_versions(db, dataset_id)
    return envelope({"items": [serializers.dataset_version(item) for item in versions]})


# --------------------------------------------------------------------------
# 版本维度
# --------------------------------------------------------------------------
@version_router.get("/{version_id}")
def get_version(
    version_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """版本详情：行数、切分、质量报告、diff。"""
    version = dataset_crud.get_version_detail(db, version_id)
    if version is None:
        raise NotFoundError("数据集版本不存在")
    data = serializers.dataset_version(version)
    data["dataset_name"] = version.dataset.name if version.dataset else ""
    data["task_type"] = version.dataset.task_type if version.dataset else ""
    return envelope(data)


@version_router.get("/{version_id}/samples")
def list_samples(
    version_id: int,
    split: str = Query("", description="train / val，留空表示全部"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """分页预览版本样本。"""
    version = dataset_crud.get_version(db, version_id)
    if version is None:
        raise NotFoundError("数据集版本不存在")
    items, total = dataset_crud.list_samples(db, version_id, split=split, page=page, size=size)
    return envelope(
        _page_payload([serializers.dataset_sample(item) for item in items], total, page, size)
    )


@version_router.get("/{version_id}/quality")
def quality(
    version_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """重新计算并返回质量报告（空值/超长/重复率/标签分布）。"""
    version = dataset_crud.get_version(db, version_id)
    if version is None:
        raise NotFoundError("数据集版本不存在")
    rows = dataset_service.load_samples_as_rows(db, version_id)
    report = dataset_service.quality_report(rows)
    report["checksum"] = version.checksum
    report["row_count"] = version.row_count
    return envelope(report)


@version_router.get("/{version_id}/diff")
def diff(
    version_id: int,
    against: int = Query(..., description="对比的基线版本 id"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """对比两个版本：新增/删除/标签变更。"""
    current = dataset_crud.get_version(db, version_id)
    base = dataset_crud.get_version(db, against)
    if current is None or base is None:
        raise NotFoundError("版本不存在")
    old_samples = dataset_crud.all_samples(db, base.id)
    new_rows = [
        dataset_service.ParsedRow(text=item.text, label=item.label, split=item.split, meta={})
        for item in dataset_crud.all_samples(db, current.id)
    ]
    result = dataset_service.diff_versions(old_samples, new_rows)
    result["base_version"] = base.version
    result["target_version"] = current.version
    return envelope(result)


@version_router.get("/{version_id}/download")
def download_version(
    version_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> Response:
    """把版本样本导出为 CSV（UTF-8 BOM，Excel 可直接打开）。"""
    version = dataset_crud.get_version(db, version_id)
    if version is None:
        raise NotFoundError("数据集版本不存在")
    rows = dataset_crud.all_samples(db, version_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["row_index", "text", "label", "split"])
    for item in rows:
        writer.writerow([item.row_index, item.text, item.label, item.split])
    filename = f"dataset-{version.dataset_id}-v{version.version}.csv"
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
