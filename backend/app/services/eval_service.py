"""评测服务：评测集管理、离线指标计算、多版本对比。"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sqlalchemy.orm import Session

from app.config import settings
from app.crud import evals as eval_crud
from app.crud import models as model_crud
from app.errors import AppError, ConflictError, NotFoundError
from app.models import EvalDataset, EvalResult, EvalRun, utcnow
from app.services import dataset_service
from app.services.runtime import ModelRuntime

logger = logging.getLogger(__name__)


def create_eval_dataset(
    db: Session,
    *,
    name: str,
    description: str,
    task_type: str,
    text_field: str,
    label_field: str,
    filename: str,
    raw: bytes,
) -> EvalDataset:
    if eval_crud.get_by_name(db, name) is not None:
        raise ConflictError(f"评测集 '{name}' 已存在")
    rows = dataset_service.parse_dataset(
        filename,
        raw,
        text_field=text_field,
        label_field=label_field,
        split_field="",
        val_ratio=0.0,
        task_type=task_type,
    )
    if task_type != "text_classification":
        raise AppError("当前只支持文本分类评测集", code=40010)

    settings.eval_path.mkdir(parents=True, exist_ok=True)
    stored = settings.eval_path / f"{uuid.uuid4().hex[:8]}-{Path(filename).name}"
    with stored.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps({"text": row.text, "label": row.label}, ensure_ascii=False) + "\n")

    dataset = EvalDataset(
        name=name,
        description=description,
        task_type=task_type,
        file_path=settings.relative_path(stored),
        sample_count=len(rows),
        created_at=utcnow(),
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    logger.info("评测集已创建 id=%s name=%s rows=%s", dataset.id, name, len(rows))
    return dataset


def load_eval_rows(dataset: EvalDataset) -> list[dict]:
    path = settings.absolute_path(dataset.file_path)
    if not path.exists():
        raise NotFoundError("评测集文件已丢失，请重新上传")
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            rows.append({"text": str(record.get("text", "")), "label": str(record.get("label", ""))})
    return rows


def classification_metrics(y_true: list[str], y_pred: list[str]) -> dict:
    labels = sorted(set(y_true) | set(y_pred))
    accuracy = float(accuracy_score(y_true, y_pred)) if y_true else 0.0
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average=None, zero_division=0
    )
    macro_p, macro_r, macro_f1, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average="macro", zero_division=0
    )
    weighted_f1 = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average="weighted", zero_division=0
    )[2]
    matrix = confusion_matrix(y_true, y_pred, labels=labels).tolist() if labels else []
    return {
        "accuracy": round(accuracy, 4),
        "precision_macro": round(float(macro_p), 4),
        "recall_macro": round(float(macro_r), 4),
        "f1_macro": round(float(macro_f1), 4),
        "f1_weighted": round(float(weighted_f1), 4),
        "sample_count": len(y_true),
        "label_count": len(labels),
        "labels": labels,
        "per_label": [
            {
                "label": label,
                "precision": round(float(precision[index]), 4),
                "recall": round(float(recall[index]), 4),
                "f1": round(float(f1[index]), 4),
                "support": int(support[index]),
            }
            for index, label in enumerate(labels)
        ],
        "confusion_matrix": matrix,
    }


def run_evaluation(db: Session, run: EvalRun) -> EvalRun:
    """同步执行评测：逐条推理 → 计算准确率/精确率/召回率/F1 → 写入报告。"""
    version = model_crud.get_version_detail(db, run.model_version_id)
    if version is None:
        raise NotFoundError("模型版本不存在")
    dataset = eval_crud.get_eval_dataset(db, run.eval_dataset_id)
    if dataset is None:
        raise NotFoundError("评测集不存在")
    if version.registry is None or version.registry.task_type != "text_classification":
        raise AppError("当前仅支持对文本分类模型做离线评测", code=40011)

    run.status = "running"
    run.started_at = utcnow()
    db.commit()

    try:
        rows = load_eval_rows(dataset)
        limit = int((run.config_json or {}).get("max_samples", 500))
        rows = rows[:limit]
        if not rows:
            raise AppError("评测集为空", code=40012)
        runtime = ModelRuntime(version).load(db)
        y_true: list[str] = []
        y_pred: list[str] = []
        scores: list[float] = []
        latencies: list[float] = []
        started = time.perf_counter()
        for index, row in enumerate(rows):
            tick = time.perf_counter()
            result = runtime.classify(row["text"])
            latencies.append((time.perf_counter() - tick) * 1000)
            predicted = result["label"]
            y_true.append(row["label"])
            y_pred.append(predicted)
            scores.append(float(result["confidence"]))
            db.add(
                EvalResult(
                    run_id=run.id,
                    sample_index=index,
                    input_text=row["text"],
                    expected=row["label"],
                    predicted=predicted,
                    correct=predicted == row["label"],
                    score=round(float(result["confidence"]), 4),
                    latency_ms=round(latencies[-1], 2),
                    detail_json={"scores": result["scores"]},
                )
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        metrics = classification_metrics(y_true, y_pred)
        metrics.update(
            {
                "avg_latency_ms": round(float(np.mean(latencies)) if latencies else 0.0, 2),
                "p95_latency_ms": round(float(np.percentile(latencies, 95)) if latencies else 0.0, 2),
                "total_ms": round(elapsed_ms, 2),
                "avg_confidence": round(float(np.mean(scores)) if scores else 0.0, 4),
                "engine": "in-process joblib runtime",
            }
        )
        run.metrics_json = metrics
        run.status = "succeeded"
        run.finished_at = utcnow()
        run.error = ""
        db.commit()
        db.refresh(run)
        logger.info("评测完成 run=%s accuracy=%s", run.id, metrics["accuracy"])
        return run
    except Exception as exc:  # noqa: BLE001 - 失败也要留下可读原因
        db.rollback()
        run = db.get(EvalRun, run.id)
        run.status = "failed"
        run.error = str(exc)[:500]
        run.finished_at = utcnow()
        db.commit()
        logger.warning("评测失败 run=%s：%s", run.id, exc)
        return run


def compare_runs(db: Session, run_ids: list[int]) -> dict:
    runs = [eval_crud.get_run_detail(db, run_id) for run_id in run_ids]
    runs = [run for run in runs if run is not None]
    if not runs:
        raise NotFoundError("没有找到评测记录")
    metric_names = [
        "accuracy",
        "precision_macro",
        "recall_macro",
        "f1_macro",
        "f1_weighted",
        "avg_latency_ms",
        "sample_count",
    ]
    rows = []
    for name in metric_names:
        row = {"metric": name, "values": []}
        for run in runs:
            row["values"].append({"run_id": run.id, "value": (run.metrics_json or {}).get(name)})
        rows.append(row)
    return {"runs": runs, "metric_names": metric_names, "rows": rows}
