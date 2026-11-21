"""ORM 模型定义（18 张表）。

表名与字段说明见 ``docs/database.md``。约定：
* 所有时间字段保存 **UTC naive datetime**，前端按需转换成本地时间；
* 结构化杂项字段统一用 ``*_json`` 命名并映射到 JSON 列，便于 SQLite/MySQL 双端兼容。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    """当前 UTC 时间（naive，避免 SQLite 时区丢失）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """平台用户（演示项目仅一个 admin 角色，字段预留扩展）。"""

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str] = mapped_column(String(64), default="")
    role: Mapped[str] = mapped_column(String(16), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Dataset(Base):
    """数据集（逻辑实体，含多个版本）。"""

    __tablename__ = "dataset"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # text_classification | rag_corpus
    task_type: Mapped[str] = mapped_column(String(32), index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    versions: Mapped[list[DatasetVersion]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="DatasetVersion.version.desc()"
    )


class DatasetVersion(Base):
    """数据集版本：每次上传产生一个不可变版本，附带质量统计与 diff。"""

    __tablename__ = "dataset_version"
    __table_args__ = (UniqueConstraint("dataset_id", "version", name="uq_dataset_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    file_path: Mapped[str] = mapped_column(String(512), default="")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    train_count: Mapped[int] = mapped_column(Integer, default=0)
    val_count: Mapped[int] = mapped_column(Integer, default=0)
    label_count: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    stats_json: Mapped[dict] = mapped_column(JSON, default=dict)
    diff_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    dataset: Mapped[Dataset] = relationship(back_populates="versions")
    samples: Mapped[list[DatasetSample]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class DatasetSample(Base):
    """数据集样本（文本 + 标签 + 归属切分）。"""

    __tablename__ = "dataset_sample"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), index=True
    )
    row_index: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    label: Mapped[str] = mapped_column(String(128), default="", index=True)
    split: Mapped[str] = mapped_column(String(16), default="train", index=True)
    meta_json: Mapped[dict] = mapped_column(JSON, default=dict)

    version: Mapped[DatasetVersion] = relationship(back_populates="samples")


class TrainingJob(Base):
    """训练任务（状态机：queued -> running -> succeeded / failed / canceled）。"""

    __tablename__ = "training_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_version.id"), index=True)
    task_type: Mapped[str] = mapped_column(String(32), index=True)
    base_model: Mapped[str] = mapped_column(String(64), default="")
    hyperparams_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    status_message: Mapped[str] = mapped_column(String(256), default="")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(Text, default="")
    queued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    artifact_path: Mapped[str] = mapped_column(String(512), default="")
    artifact_size: Mapped[int] = mapped_column(Integer, default=0)
    artifact_sha256: Mapped[str] = mapped_column(String(64), default="")
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_version.id"), nullable=True)
    auto_register: Mapped[bool] = mapped_column(Boolean, default=True)
    register_as: Mapped[str] = mapped_column(String(128), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="system")

    logs: Mapped[list[TrainingLog]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="TrainingLog.id"
    )
    metrics: Mapped[list[TrainingMetric]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="TrainingMetric.id"
    )


class TrainingLog(Base):
    """训练日志（按行写入，支持轮询增量拉取与 SSE 推送）。"""

    __tablename__ = "training_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("training_job.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    message: Mapped[str] = mapped_column(Text, default="")

    job: Mapped[TrainingJob] = relationship(back_populates="logs")


class TrainingMetric(Base):
    """训练指标（逐 epoch 落库，前端画 loss/acc 曲线）。"""

    __tablename__ = "training_metric"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("training_job.id", ondelete="CASCADE"), index=True)
    epoch: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(32), default="loss", index=True)
    value: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    job: Mapped[TrainingJob] = relationship(back_populates="metrics")


class ModelRegistry(Base):
    """模型注册表（逻辑模型，含多个版本）。"""

    __tablename__ = "model_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    task_type: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    versions: Mapped[list[ModelVersion]] = relationship(
        back_populates="registry", cascade="all, delete-orphan", order_by="ModelVersion.version.desc()"
    )


class ModelVersion(Base):
    """模型版本：训练产物 + 指标 + 血缘 + 发布状态。"""

    __tablename__ = "model_version"
    __table_args__ = (UniqueConstraint("registry_id", "version", name="uq_model_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    registry_id: Mapped[int] = mapped_column(ForeignKey("model_registry.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    training_job_id: Mapped[int | None] = mapped_column(ForeignKey("training_job.id"), nullable=True, index=True)
    framework: Mapped[str] = mapped_column(String(64), default="scikit-learn")
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    hyperparams_json: Mapped[dict] = mapped_column(JSON, default=dict)
    labels_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="staging", index=True)
    artifact_path: Mapped[str] = mapped_column(String(512), default="")
    artifact_size: Mapped[int] = mapped_column(Integer, default=0)
    artifact_sha256: Mapped[str] = mapped_column(String(64), default="")
    model_card_md: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    registry: Mapped[ModelRegistry] = relationship(back_populates="versions")
    training_job: Mapped[TrainingJob | None] = relationship(foreign_keys=[training_job_id])


class Deployment(Base):
    """在线推理服务（starting / running / stopped / failed）。"""

    __tablename__ = "deployment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_version.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="starting", index=True)
    qps_limit: Mapped[int] = mapped_column(Integer, default=50)
    alias: Mapped[str] = mapped_column(String(128), default="", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    total_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_request_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str] = mapped_column(String(64), default="system")

    model_version: Mapped[ModelVersion] = relationship()


class ApiKey(Base):
    """API Key（仅存 SHA-256 哈希与前缀，明文只在创建时返回一次）。"""

    __tablename__ = "api_key"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    prefix: Mapped[str] = mapped_column(String(24), default="")
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scopes_json: Mapped[list] = mapped_column(JSON, default=list)
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=60)
    burst: Mapped[int] = mapped_column(Integer, default=10)
    token_quota: Mapped[int] = mapped_column(Integer, default=200_000)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    requests_used: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), nullable=True)


class UsageRecord(Base):
    """用量流水（tokens / 次数 / 延迟 / 状态码），用于计费与看板。"""

    __tablename__ = "usage_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    api_key_id: Mapped[int | None] = mapped_column(ForeignKey("api_key.id"), nullable=True, index=True)
    deployment_id: Mapped[int | None] = mapped_column(ForeignKey("deployment.id"), nullable=True, index=True)
    endpoint: Mapped[str] = mapped_column(String(64), default="")
    model_name: Mapped[str] = mapped_column(String(128), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class InferenceLog(Base):
    """调用日志（请求/响应摘要、trace id、错误信息），支持检索。"""

    __tablename__ = "inference_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    api_key_id: Mapped[int | None] = mapped_column(ForeignKey("api_key.id"), nullable=True, index=True)
    deployment_id: Mapped[int | None] = mapped_column(ForeignKey("deployment.id"), nullable=True, index=True)
    endpoint: Mapped[str] = mapped_column(String(64), default="", index=True)
    model_name: Mapped[str] = mapped_column(String(128), default="")
    status_code: Mapped[int] = mapped_column(Integer, default=200, index=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    prompt_preview: Mapped[str] = mapped_column(Text, default="")
    response_preview: Mapped[str] = mapped_column(Text, default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class EvalDataset(Base):
    """评测集（有标准答案的标注数据）。"""

    __tablename__ = "eval_dataset"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    task_type: Mapped[str] = mapped_column(String(32), default="text_classification")
    file_path: Mapped[str] = mapped_column(String(512), default="")
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EvalRun(Base):
    """一次评测执行记录。"""

    __tablename__ = "eval_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_version.id"), index=True)
    eval_dataset_id: Mapped[int] = mapped_column(ForeignKey("eval_dataset.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str] = mapped_column(String(64), default="system")

    model_version: Mapped[ModelVersion] = relationship()
    eval_dataset: Mapped[EvalDataset] = relationship()
    results: Mapped[list[EvalResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="EvalResult.sample_index"
    )


class EvalResult(Base):
    """评测样本级结果（用于错误样例分析）。"""

    __tablename__ = "eval_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("eval_run.id", ondelete="CASCADE"), index=True)
    sample_index: Mapped[int] = mapped_column(Integer, default=0)
    input_text: Mapped[str] = mapped_column(Text, default="")
    expected: Mapped[str] = mapped_column(String(128), default="")
    predicted: Mapped[str] = mapped_column(String(128), default="")
    correct: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict)

    run: Mapped[EvalRun] = relationship(back_populates="results")


class PromptTemplate(Base):
    """Prompt 模板（``{{variable}}`` 占位符 + 变量声明）。"""

    __tablename__ = "prompt_template"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    variables_json: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[str] = mapped_column(String(128), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PromptExperiment(Base):
    """Prompt A/B 实验：同输入分别渲染 A/B 模板，记录输出与人工评分。"""

    __tablename__ = "prompt_experiment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    template_a_id: Mapped[int] = mapped_column(ForeignKey("prompt_template.id"), index=True)
    template_b_id: Mapped[int] = mapped_column(ForeignKey("prompt_template.id"), index=True)
    input_text: Mapped[str] = mapped_column(Text, default="")
    variables_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_a: Mapped[str] = mapped_column(Text, default="")
    output_b: Mapped[str] = mapped_column(Text, default="")
    latency_a_ms: Mapped[float] = mapped_column(Float, default=0.0)
    latency_b_ms: Mapped[float] = mapped_column(Float, default=0.0)
    engine: Mapped[str] = mapped_column(String(64), default="local-extractive-v1")
    score_a: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_b: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    template_a: Mapped[PromptTemplate] = relationship(foreign_keys=[template_a_id])
    template_b: Mapped[PromptTemplate] = relationship(foreign_keys=[template_b_id])


class RagChunk(Base):
    """RAG 向量表：切片文本 + float32 归一化向量（BLOB）。"""

    __tablename__ = "rag_chunk"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    training_job_id: Mapped[int] = mapped_column(ForeignKey("training_job.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    doc_title: Mapped[str] = mapped_column(String(256), default="")
    source: Mapped[str] = mapped_column(String(256), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    dim: Mapped[int] = mapped_column(Integer, default=0)
    vector: Mapped[bytes] = mapped_column(LargeBinary, default=b"")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
