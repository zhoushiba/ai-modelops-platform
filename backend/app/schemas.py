"""Pydantic v2 请求/响应模型（OpenAPI 文档的数据契约）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")


# --------------------------------------------------------------------------
# 通用
# --------------------------------------------------------------------------
class ApiResponse(BaseModel, Generic[T]):
    """统一响应信封。"""

    code: int = 0
    message: str = "ok"
    data: T | None = None
    trace_id: str = ""


class Page(BaseModel, Generic[T]):
    items: list[T] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    size: int = 20


class OkData(BaseModel):
    ok: bool = True


# --------------------------------------------------------------------------
# 认证
# --------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str = ""
    role: str = "admin"
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# --------------------------------------------------------------------------
# 数据集
# --------------------------------------------------------------------------
TaskType = Literal["text_classification", "rag_corpus"]


class DatasetCreateForm(BaseModel):
    """上传数据集时随文件提交的表单字段（multipart form 复用校验）。"""

    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    task_type: TaskType = "text_classification"
    text_field: str = "text"
    label_field: str = "label"
    val_ratio: float = Field(default=0.2, ge=0.0, le=0.5)
    split_field: str = ""


class DatasetVersionOut(BaseModel):
    id: int
    dataset_id: int
    version: int
    row_count: int = 0
    train_count: int = 0
    val_count: int = 0
    label_count: int = 0
    checksum: str = ""
    stats: dict[str, Any] = Field(default_factory=dict)
    diff: dict[str, Any] = Field(default_factory=dict)
    file_path: str = ""
    created_by: str = "system"
    created_at: datetime


class DatasetOut(BaseModel):
    id: int
    name: str
    description: str = ""
    task_type: str
    owner: str = ""
    version_count: int = 0
    latest_version: DatasetVersionOut | None = None
    created_at: datetime
    updated_at: datetime


class DatasetDetailOut(DatasetOut):
    versions: list[DatasetVersionOut] = Field(default_factory=list)


class DatasetSampleOut(BaseModel):
    id: int
    row_index: int
    text: str
    label: str
    split: str
    meta: dict[str, Any] = Field(default_factory=dict)


class QualityReportOut(BaseModel):
    version_id: int
    row_count: int
    label_count: int
    duplicate_count: int = 0
    duplicate_ratio: float = 0.0
    empty_count: int = 0
    too_long_count: int = 0
    label_distribution: dict[str, int] = Field(default_factory=dict)
    length_stats: dict[str, float] = Field(default_factory=dict)
    split_distribution: dict[str, int] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 训练任务
# --------------------------------------------------------------------------
class HyperParams(BaseModel):
    """训练超参；不同任务类型只使用其中一部分（见 docs/training.md）。

    注意：``epochs`` / ``lr`` / ``chunk_size`` / ``chunk_overlap`` 只在这里做类型约束，
    数值区间由 ``BaseTrainer.validate_hparams`` 统一校验，这样越界时返回业务错误码
    ``40031``（而不是 pydantic 的 422），前端可按同一套错误码提示。
    """

    model_config = ConfigDict(extra="forbid")

    epochs: int = 6
    lr: float = 1.0  # LogisticRegression 的 C
    batch_size: int = Field(default=32, ge=1, le=1024)
    max_len: int = Field(default=256, ge=16, le=4096)
    max_features: int = Field(default=8000, ge=100, le=200_000)
    ngram_max: int = Field(default=2, ge=1, le=3)
    # RAG 专用
    embedding_dim: int = Field(default=384, ge=64, le=4096)
    chunk_size: int = 220
    chunk_overlap: int = 40


class TrainingJobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    dataset_version_id: int
    task_type: TaskType
    base_model: str = "tfidf-logreg"
    hyperparams: HyperParams = Field(default_factory=HyperParams)
    auto_register: bool = True
    register_as: str = ""


class TrainingJobOut(BaseModel):
    id: int
    name: str
    dataset_version_id: int
    dataset_name: str = ""
    dataset_version: int = 0
    task_type: str
    base_model: str = ""
    hyperparams: dict[str, Any] = Field(default_factory=dict)
    status: str
    progress: int = 0
    status_message: str = ""
    error: str = ""
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int = 0
    artifact_path: str = ""
    artifact_size: int = 0
    artifact_sha256: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    model_version_id: int | None = None
    created_by: str = "system"


class TrainingLogOut(BaseModel):
    id: int
    ts: datetime
    level: str
    message: str


class TrainingMetricOut(BaseModel):
    id: int
    epoch: int
    name: str
    value: float


class TrainingJobDetailOut(TrainingJobOut):
    logs: list[TrainingLogOut] = Field(default_factory=list)
    metrics_series: list[TrainingMetricOut] = Field(default_factory=list)


class RegisterJobRequest(BaseModel):
    # model_name 留空时回落到任务名 / register_as，便于前端"一键补注册"
    model_name: str = Field(default="", max_length=128)
    description: str = ""


# --------------------------------------------------------------------------
# 模型注册表
# --------------------------------------------------------------------------
class ModelVersionOut(BaseModel):
    id: int
    registry_id: int
    registry_name: str = ""
    task_type: str = ""
    version: int
    status: str
    framework: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    hyperparams: dict[str, Any] = Field(default_factory=dict)
    labels: list[Any] = Field(default_factory=list)
    artifact_size: int = 0
    artifact_sha256: str = ""
    training_job_id: int | None = None
    training_job_name: str = ""
    model_card_md: str = ""
    created_by: str = "system"
    created_at: datetime
    deployment_count: int = 0


class ModelRegistryOut(BaseModel):
    id: int
    name: str
    task_type: str
    description: str = ""
    version_count: int = 0
    production_version: int | None = None
    best_accuracy: float | None = None
    latest_version: ModelVersionOut | None = None
    created_at: datetime


class ModelVersionStatusUpdate(BaseModel):
    status: Literal["staging", "production", "archived"]
    note: str = ""


class ModelCardOut(BaseModel):
    model_version_id: int
    model_card: str
    markdown: str = ""


# --------------------------------------------------------------------------
# 部署与推理服务
# --------------------------------------------------------------------------
class DeploymentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    model_version_id: int
    qps_limit: int = Field(default=50, ge=1, le=10_000)
    alias: str = ""
    description: str = ""


class DeploymentOut(BaseModel):
    id: int
    name: str
    alias: str = ""
    description: str = ""
    status: str
    model_version_id: int
    model_name: str = ""
    model_version: int = 0
    task_type: str = ""
    qps_limit: int = 50
    request_count: int = 0
    error_count: int = 0
    avg_latency_ms: float = 0.0
    last_error: str = ""
    last_request_at: datetime | None = None
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    created_at: datetime


class DeploymentStatsOut(BaseModel):
    deployment_id: int
    total_requests: int = 0
    error_count: int = 0
    error_rate: float = 0.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    qps_last_minute: float = 0.0
    tokens_total: int = 0
    series: list[dict[str, Any]] = Field(default_factory=list)
    top_errors: list[dict[str, Any]] = Field(default_factory=list)


# --------------------------------------------------------------------------
# API Key 与用量
# --------------------------------------------------------------------------
class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    rate_limit_per_min: int = Field(default=60, ge=1, le=100_000)
    burst: int = Field(default=10, ge=1, le=10_000)
    token_quota: int = Field(default=200_000, ge=1)
    scopes: list[str] = Field(default_factory=lambda: ["chat", "embeddings"])


class ApiKeyOut(BaseModel):
    id: int
    name: str
    prefix: str
    scopes: list[str] = Field(default_factory=list)
    rate_limit_per_min: int = 60
    burst: int = 10
    token_quota: int = 0
    tokens_used: int = 0
    requests_used: int = 0
    quota_used_ratio: float = 0.0
    active: bool = True
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime


class ApiKeyCreatedOut(ApiKeyOut):
    plain_key: str


class UsageSummaryOut(BaseModel):
    total_requests: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error_requests: int = 0
    error_rate: float = 0.0
    avg_latency_ms: float = 0.0
    by_day: list[dict[str, Any]] = Field(default_factory=list)
    by_endpoint: list[dict[str, Any]] = Field(default_factory=list)
    by_key: list[dict[str, Any]] = Field(default_factory=list)
    by_model: list[dict[str, Any]] = Field(default_factory=list)


class InferenceLogOut(BaseModel):
    id: int
    trace_id: str
    endpoint: str
    model_name: str = ""
    status_code: int
    latency_ms: float
    prompt_preview: str = ""
    response_preview: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str = ""
    key_name: str = ""
    deployment_name: str = ""
    created_at: datetime


# --------------------------------------------------------------------------
# 评测
# --------------------------------------------------------------------------
class EvalDatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    task_type: TaskType = "text_classification"
    text_field: str = "text"
    label_field: str = "label"


class EvalDatasetOut(BaseModel):
    id: int
    name: str
    description: str = ""
    task_type: str
    sample_count: int = 0
    created_at: datetime


class EvalRunCreate(BaseModel):
    model_version_id: int
    eval_dataset_id: int
    name: str = ""
    max_samples: int = Field(default=500, ge=1, le=20_000)


class EvalResultOut(BaseModel):
    id: int
    sample_index: int
    input_text: str
    expected: str
    predicted: str
    correct: bool
    score: float
    latency_ms: float


class EvalRunOut(BaseModel):
    id: int
    name: str = ""
    model_version_id: int
    model_name: str = ""
    model_version_number: int = 0
    eval_dataset_id: int
    eval_dataset_name: str = ""
    status: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class EvalRunDetailOut(EvalRunOut):
    results: list[EvalResultOut] = Field(default_factory=list)


class EvalCompareOut(BaseModel):
    runs: list[EvalRunOut] = Field(default_factory=list)
    metric_names: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Prompt 实验
# --------------------------------------------------------------------------
class PromptTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    content: str = Field(min_length=1)
    tags: str = ""
    variables: list[str] = Field(default_factory=list)


class PromptTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    content: str | None = None
    tags: str | None = None
    variables: list[str] | None = None


class PromptTemplateOut(BaseModel):
    id: int
    name: str
    description: str = ""
    content: str = ""
    variables: list[str] = Field(default_factory=list)
    tags: str = ""
    version: int = 1
    created_at: datetime
    updated_at: datetime


class RenderRequest(BaseModel):
    variables: dict[str, str] = Field(default_factory=dict)


class RenderOut(BaseModel):
    rendered: str
    missing_variables: list[str] = Field(default_factory=list)


class ExperimentCreate(BaseModel):
    name: str = ""
    template_a_id: int
    template_b_id: int
    input_text: str = Field(min_length=1)
    variables: dict[str, str] = Field(default_factory=dict)


class ExperimentScore(BaseModel):
    score_a: int = Field(ge=1, le=5)
    score_b: int = Field(ge=1, le=5)
    notes: str = ""


class ExperimentOut(BaseModel):
    id: int
    name: str = ""
    template_a_id: int
    template_b_id: int
    template_a_name: str = ""
    template_b_name: str = ""
    input_text: str
    variables: dict[str, Any] = Field(default_factory=dict)
    output_a: str = ""
    output_b: str = ""
    latency_a_ms: float = 0.0
    latency_b_ms: float = 0.0
    engine: str = ""
    score_a: int | None = None
    score_b: int | None = None
    notes: str = ""
    status: str = "pending"
    created_at: datetime


# --------------------------------------------------------------------------
# 看板
# --------------------------------------------------------------------------
class DashboardSummaryOut(BaseModel):
    dataset_count: int = 0
    training_job_count: int = 0
    running_job_count: int = 0
    job_success_rate: float = 0.0
    model_count: int = 0
    production_model_count: int = 0
    deployment_count: int = 0
    running_deployment_count: int = 0
    api_key_count: int = 0
    calls_today: int = 0
    tokens_today: int = 0
    error_rate_today: float = 0.0
    avg_latency_ms_today: float = 0.0
    recent_jobs: list[TrainingJobOut] = Field(default_factory=list)
    recent_calls: list[InferenceLogOut] = Field(default_factory=list)


class TimeseriesPoint(BaseModel):
    date: str
    requests: int = 0
    tokens: int = 0
    errors: int = 0


# --------------------------------------------------------------------------
# OpenAI 兼容接口
# --------------------------------------------------------------------------
class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: Literal["system", "user", "assistant", "tool"] = "user"
    content: str | list[dict[str, Any]] | None = None
    name: str | None = None

    @field_validator("content")
    @classmethod
    def _check_content(cls, value):  # noqa: ANN001, ANN206
        return value


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = Field(default=0.2, ge=0, le=2)
    top_p: float = Field(default=1.0, gt=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1, le=8192)
    stream: bool = False
    n: int = Field(default=1, ge=1, le=4)
    user: str | None = None
    response_format: dict[str, Any] | None = None


class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    input: str | list[str]
    encoding_format: Literal["float", "base64"] = "float"
    dimensions: int | None = Field(default=None, ge=8, le=4096)
