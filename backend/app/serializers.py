"""ORM -> 响应字典的转换（供 ``response_model`` 校验）。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.crud import datasets as dataset_crud
from app.crud import models as model_crud
from app.models import (
    ApiKey,
    Dataset,
    DatasetSample,
    DatasetVersion,
    Deployment,
    EvalDataset,
    EvalResult,
    EvalRun,
    InferenceLog,
    ModelRegistry,
    ModelVersion,
    PromptExperiment,
    PromptTemplate,
    TrainingJob,
    TrainingLog,
    TrainingMetric,
    User,
)


def user(obj: User) -> dict:
    return {
        "id": obj.id,
        "username": obj.username,
        "display_name": obj.display_name,
        "role": obj.role,
        "created_at": obj.created_at,
    }


def dataset_version(obj: DatasetVersion) -> dict:
    return {
        "id": obj.id,
        "dataset_id": obj.dataset_id,
        "version": obj.version,
        "row_count": obj.row_count,
        "train_count": obj.train_count,
        "val_count": obj.val_count,
        "label_count": obj.label_count,
        "checksum": obj.checksum,
        "stats": obj.stats_json or {},
        "diff": obj.diff_json or {},
        "file_path": obj.file_path,
        "created_by": obj.created_by,
        "created_at": obj.created_at,
    }


def dataset(db: Session, obj: Dataset) -> dict:
    versions = dataset_crud.list_versions(db, obj.id)
    latest = versions[0] if versions else None
    owner = db.get(User, obj.owner_id) if obj.owner_id else None
    return {
        "id": obj.id,
        "name": obj.name,
        "description": obj.description,
        "task_type": obj.task_type,
        "owner": owner.username if owner else "",
        "version_count": len(versions),
        "latest_version": dataset_version(latest) if latest else None,
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


def dataset_detail(db: Session, obj: Dataset) -> dict:
    versions = dataset_crud.list_versions(db, obj.id)
    data = dataset(db, obj)
    data["versions"] = [dataset_version(v) for v in versions]
    return data


def dataset_sample(obj: DatasetSample) -> dict:
    return {
        "id": obj.id,
        "row_index": obj.row_index,
        "text": obj.text,
        "label": obj.label,
        "split": obj.split,
        "meta": obj.meta_json or {},
    }


def job(db: Session, obj: TrainingJob) -> dict:
    dataset_name, dataset_version = "", 0
    version = dataset_crud.get_version_detail(db, obj.dataset_version_id)
    if version is not None:
        dataset_version = version.version
        dataset_name = version.dataset.name if version.dataset else ""
    # 运行结束时已由执行器写入 duration_ms；历史数据兜底按起止时间推算
    duration_ms = obj.duration_ms
    if not duration_ms and obj.started_at and obj.finished_at:
        duration_ms = max(0, int((obj.finished_at - obj.started_at).total_seconds() * 1000))
    return {
        "id": obj.id,
        "name": obj.name,
        "dataset_version_id": obj.dataset_version_id,
        "dataset_name": dataset_name,
        "dataset_version": dataset_version,
        "task_type": obj.task_type,
        "base_model": obj.base_model,
        "hyperparams": obj.hyperparams_json or {},
        "status": obj.status,
        "progress": obj.progress,
        "status_message": obj.status_message,
        "error": obj.error,
        "queued_at": obj.queued_at,
        "started_at": obj.started_at,
        "finished_at": obj.finished_at,
        "duration_ms": duration_ms,
        "artifact_path": obj.artifact_path or "",
        "artifact_size": obj.artifact_size,
        "artifact_sha256": obj.artifact_sha256,
        "metrics": obj.metrics_json or {},
        "model_version_id": obj.model_version_id,
        "created_by": obj.created_by,
    }


def job_detail(db: Session, obj: TrainingJob) -> dict:
    data = job(db, obj)
    data["logs"] = [training_log(item) for item in obj.logs]
    data["metrics_series"] = [training_metric(item) for item in obj.metrics]
    return data


def training_log(obj: TrainingLog) -> dict:
    return {"id": obj.id, "ts": obj.ts, "level": obj.level, "message": obj.message}


def training_metric(obj: TrainingMetric) -> dict:
    return {"id": obj.id, "epoch": obj.epoch, "name": obj.name, "value": obj.value}


def model_version(db: Session, obj: ModelVersion) -> dict:
    registry = obj.registry
    training_job = obj.training_job
    return {
        "id": obj.id,
        "registry_id": obj.registry_id,
        "registry_name": registry.name if registry else "",
        "task_type": registry.task_type if registry else "",
        "version": obj.version,
        "status": obj.status,
        "framework": obj.framework,
        "metrics": obj.metrics_json or {},
        "hyperparams": obj.hyperparams_json or {},
        "labels": obj.labels_json or [],
        "artifact_size": obj.artifact_size,
        "artifact_sha256": obj.artifact_sha256,
        "training_job_id": obj.training_job_id,
        "training_job_name": training_job.name if training_job else "",
        "model_card_md": obj.model_card_md,
        "created_by": obj.created_by,
        "created_at": obj.created_at,
        "deployment_count": model_crud.deployment_count(db, obj.id),
    }


def registry(db: Session, obj: ModelRegistry) -> dict:
    versions = sorted(obj.versions, key=lambda item: item.version, reverse=True)
    production = next((item for item in versions if item.status == "production"), None)
    accuracies = [
        float(item.metrics_json.get("accuracy"))
        for item in versions
        if isinstance(item.metrics_json, dict) and item.metrics_json.get("accuracy") is not None
    ]
    return {
        "id": obj.id,
        "name": obj.name,
        "task_type": obj.task_type,
        "description": obj.description,
        "version_count": len(versions),
        "production_version": production.version if production else None,
        "best_accuracy": round(max(accuracies), 4) if accuracies else None,
        "latest_version": model_version(db, versions[0]) if versions else None,
        "created_at": obj.created_at,
    }


def deployment(db: Session, obj: Deployment) -> dict:
    version = obj.model_version
    registry = version.registry if version is not None else None
    return {
        "id": obj.id,
        "name": obj.name,
        "alias": obj.alias,
        "description": obj.description,
        "status": obj.status,
        "model_version_id": obj.model_version_id,
        "model_name": registry.name if registry else "",
        "model_version": version.version if version else 0,
        "task_type": registry.task_type if registry else "",
        "qps_limit": obj.qps_limit,
        "request_count": obj.request_count,
        "error_count": obj.error_count,
        "avg_latency_ms": round(obj.total_latency_ms / obj.request_count, 2) if obj.request_count else 0.0,
        "last_error": obj.last_error,
        "last_request_at": obj.last_request_at,
        "started_at": obj.started_at,
        "stopped_at": obj.stopped_at,
        "created_at": obj.created_at,
    }


def api_key(obj: ApiKey, plain_key: str | None = None) -> dict:
    ratio = round(obj.tokens_used / obj.token_quota, 4) if obj.token_quota else 0.0
    data = {
        "id": obj.id,
        "name": obj.name,
        "prefix": obj.prefix,
        "scopes": obj.scopes_json or [],
        "rate_limit_per_min": obj.rate_limit_per_min,
        "burst": obj.burst,
        "token_quota": obj.token_quota,
        "tokens_used": obj.tokens_used,
        "requests_used": obj.requests_used,
        "quota_used_ratio": ratio,
        "active": obj.active,
        "expires_at": obj.expires_at,
        "last_used_at": obj.last_used_at,
        "created_at": obj.created_at,
    }
    if plain_key is not None:
        data["plain_key"] = plain_key
    return data


def inference_log(obj: InferenceLog, key_name: str = "", deployment_name: str = "") -> dict:
    return {
        "id": obj.id,
        "trace_id": obj.trace_id,
        "endpoint": obj.endpoint,
        "model_name": obj.model_name,
        "status_code": obj.status_code,
        "latency_ms": obj.latency_ms,
        "prompt_preview": obj.prompt_preview,
        "response_preview": obj.response_preview,
        "prompt_tokens": obj.prompt_tokens,
        "completion_tokens": obj.completion_tokens,
        "error": obj.error,
        "key_name": key_name,
        "deployment_name": deployment_name,
        "created_at": obj.created_at,
    }


def eval_dataset(obj: EvalDataset) -> dict:
    return {
        "id": obj.id,
        "name": obj.name,
        "description": obj.description,
        "task_type": obj.task_type,
        "sample_count": obj.sample_count,
        "created_at": obj.created_at,
    }


def eval_run(obj: EvalRun) -> dict:
    version = obj.model_version
    registry = version.registry if version is not None else None
    return {
        "id": obj.id,
        "name": obj.name,
        "model_version_id": obj.model_version_id,
        "model_name": registry.name if registry else "",
        "model_version_number": version.version if version else 0,
        "eval_dataset_id": obj.eval_dataset_id,
        "eval_dataset_name": obj.eval_dataset.name if obj.eval_dataset else "",
        "status": obj.status,
        "metrics": obj.metrics_json or {},
        "error": obj.error,
        "started_at": obj.started_at,
        "finished_at": obj.finished_at,
        "created_at": obj.created_at,
    }


def eval_result(obj: EvalResult) -> dict:
    return {
        "id": obj.id,
        "sample_index": obj.sample_index,
        "input_text": obj.input_text,
        "expected": obj.expected,
        "predicted": obj.predicted,
        "correct": obj.correct,
        "score": obj.score,
        "latency_ms": obj.latency_ms,
    }


def prompt_template(obj: PromptTemplate) -> dict:
    return {
        "id": obj.id,
        "name": obj.name,
        "description": obj.description,
        "content": obj.content,
        "variables": obj.variables_json or [],
        "tags": obj.tags,
        "version": obj.version,
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


def experiment(obj: PromptExperiment) -> dict:
    return {
        "id": obj.id,
        "name": obj.name,
        "template_a_id": obj.template_a_id,
        "template_b_id": obj.template_b_id,
        "template_a_name": obj.template_a.name if obj.template_a else "",
        "template_b_name": obj.template_b.name if obj.template_b else "",
        "input_text": obj.input_text,
        "variables": obj.variables_json or {},
        "output_a": obj.output_a,
        "output_b": obj.output_b,
        "latency_a_ms": obj.latency_a_ms,
        "latency_b_ms": obj.latency_b_ms,
        "engine": obj.engine,
        "score_a": obj.score_a,
        "score_b": obj.score_b,
        "notes": obj.notes,
        "status": obj.status,
        "created_at": obj.created_at,
    }
