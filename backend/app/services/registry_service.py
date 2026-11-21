"""模型注册表业务逻辑：注册、状态流转（staging/production/archived）、回滚、Model Card。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.crud import datasets as dataset_crud
from app.crud import models as model_crud
from app.errors import AppError, ConflictError, NotFoundError
from app.models import DatasetVersion, ModelRegistry, ModelVersion, TrainingJob, utcnow
from app.trainers import get_trainer


def build_model_card(
    registry: ModelRegistry,
    version: ModelVersion,
    job: TrainingJob | None,
    dataset_name: str,
    dataset_version_no: int,
) -> str:
    """根据训练产物元数据自动生成 Model Card（Markdown）。"""
    metrics = version.metrics_json or {}
    hyper = version.hyperparams_json or {}
    trainer = None
    try:
        trainer = get_trainer(registry.task_type)
    except Exception:  # noqa: BLE001 - 自定义任务类型缺失时仍能生成卡片
        trainer = None

    def metric_rows() -> str:
        if not metrics:
            return "| - | - |\n"
        keys = [
            ("accuracy", "准确率 accuracy"),
            ("f1_macro", "宏平均 F1"),
            ("precision_macro", "宏平均精确率"),
            ("recall_macro", "宏平均召回率"),
            ("self_hit_rate", "检索自命中率"),
            ("chunk_count", "切片数量"),
            ("doc_count", "文档数量"),
            ("embedding_dim", "向量维度"),
        ]
        lines = [f"| {label} | `{metrics[key]}` |" for key, label in keys if key in metrics]
        return "\n".join(lines) if lines else "| - | - |\n"

    labels = version.labels_json or []
    artifact_kb = round((version.artifact_size or 0) / 1024, 1)
    return f"""# Model Card · {registry.name} v{version.version}

## 1. 模型概览

| 项目 | 内容 |
| --- | --- |
| 模型名称 | `{registry.name}` |
| 版本 | `v{version.version}` |
| 任务类型 | `{registry.task_type}`（{trainer.display_name if trainer else "自定义"}） |
| 框架 | `{version.framework}` |
| 发布状态 | `{version.status}` |
| 产物大小 | {artifact_kb} KB |
| 产物 SHA-256 | `{version.artifact_sha256 or "-"}` |
| 训练任务 | `#{job.id if job else "-"} {job.name if job else "-"}` |
| 训练数据 | `{dataset_name} v{dataset_version_no}` |
| 创建人 / 时间 | `{version.created_by}` / {version.created_at.isoformat(sep=" ", timespec="seconds")} UTC |

## 2. 预期用途

用于贵州本地客服/工单场景的**意图识别**与**知识库问答**原型：
{registry.description or "按数据集标签体系对用户输入做分类，或从知识库中检索相关片段。"}

## 3. 训练配置

| 超参 | 值 |
| --- | --- |
""" + "\n".join(f"| `{key}` | `{value}` |" for key, value in hyper.items()) + f"""

## 4. 评估指标

| 指标 | 值 |
| --- | --- |
{metric_rows()}

标签集合（{len(labels)}）：{", ".join(f"`{item}`" for item in labels) if labels else "-"}

## 5. 局限与风险

- 训练数据来自构造的样例工单，**不代表真实线上分布**，线上使用前需用真实数据再训练；
- 文本分类模型基于 TF-IDF 字符 n-gram + 逻辑回归，对长文本语义、否定句、跨领域迁移能力有限；
- RAG 检索使用特征哈希向量，语义泛化弱于神经嵌入模型（可平滑替换为 sentence-transformers）；
- 指标为离线验证集结果，不包含线上流量偏差。

## 6. 部署与调用

```bash
# 部署该版本（在平台"部署与服务"页面一键部署后）
curl -X POST http://127.0.0.1:8000/v1/chat/completions \\
  -H "Authorization: Bearer sk-mops-****" \\
  -H "Content-Type: application/json" \\
  -d '{{"model": "deployment-name", "messages": [{{"role": "user", "content": "我要退货"}}]}}'
```

## 7. 血缘

训练任务 `#{job.id if job else "-"}` → 数据集 `{dataset_name} v{dataset_version_no}` →
模型 `{registry.name} v{version.version}` → 部署实例可在平台"部署与服务"页面查看。

> 本卡片由 ai-modelops-platform 自动生成于 {datetime.now(timezone.utc).isoformat(timespec="seconds")}
"""


def register_model(
    db: Session,
    *,
    task_type: str,
    model_name: str,
    description: str,
    job: TrainingJob,
    metrics: dict,
    hyperparams: dict,
    labels: list,
    artifact_path: str,
    artifact_size: int,
    artifact_sha256: str,
    framework: str,
    created_by: str,
) -> ModelVersion:
    """把训练任务产物注册为模型版本（同名注册表自动递增版本号）。"""
    registry = model_crud.get_registry_by_name(db, model_name)
    if registry is None:
        registry = ModelRegistry(
            name=model_name,
            task_type=task_type,
            description=description or f"由训练任务 {job.name} 产出的模型",
            created_at=utcnow(),
        )
        db.add(registry)
        db.flush()
    elif registry.task_type != task_type:
        raise ConflictError(f"同名模型 '{model_name}' 已存在且任务类型为 {registry.task_type}")

    version_no = model_crud.next_version_no(db, registry.id)
    version = ModelVersion(
        registry_id=registry.id,
        version=version_no,
        training_job_id=job.id,
        framework=framework,
        metrics_json=metrics,
        hyperparams_json=hyperparams,
        labels_json=labels,
        status="staging",
        artifact_path=artifact_path,
        artifact_size=artifact_size,
        artifact_sha256=artifact_sha256,
        created_by=created_by,
        created_at=utcnow(),
    )
    db.add(version)
    db.flush()

    dataset_name, dataset_version_no = "", 0
    version_row: DatasetVersion | None = dataset_crud.get_version_detail(db, job.dataset_version_id)
    if version_row is not None:
        dataset_version_no = version_row.version
        dataset_name = version_row.dataset.name if version_row.dataset else ""

    version.model_card_md = build_model_card(
        registry, version, job, dataset_name or "未知数据集", dataset_version_no
    )
    job.model_version_id = version.id
    db.commit()
    db.refresh(version)
    return version


def set_status(db: Session, version: ModelVersion, status: str, note: str = "") -> ModelVersion:
    """切换发布状态；同一注册表内保证最多一个 production 版本。"""
    if status not in ("staging", "production", "archived"):
        raise AppError("非法状态", code=40001)
    if version.status == status:
        return version
    if status == "production":
        for other in model_crud.list_versions(db, version.registry_id):
            if other.id != version.id and other.status == "production":
                other.status = "archived"
                other.model_card_md = other.model_card_md.replace("`production`", "`archived`")
    version.status = status
    if note:
        version.model_card_md += f"\n\n---\n\n状态变更说明（{utcnow().isoformat(timespec='seconds')} UTC）：{note}\n"
    db.commit()
    db.refresh(version)
    return version


def rollback(db: Session, registry: ModelRegistry, to_version: int | None = None) -> ModelVersion:
    """回滚：把指定版本（默认最近一个非 production 版本）重新提升为 production。"""
    versions = model_crud.list_versions(db, registry.id)
    if not versions:
        raise NotFoundError("该模型还没有版本")
    current = next((item for item in versions if item.status == "production"), None)
    if to_version is not None:
        target = next((item for item in versions if item.version == to_version), None)
        if target is None:
            raise NotFoundError(f"版本 v{to_version} 不存在")
    else:
        candidates = [item for item in versions if current is None or item.id != current.id]
        if not candidates:
            raise ConflictError("没有可回滚的历史版本")
        target = candidates[0]
    if current is not None and current.id == target.id:
        raise ConflictError("目标版本已经是 production")
    return set_status(db, target, "production", note="回滚操作")


def ensure_artifact(version: ModelVersion) -> str:
    """校验产物文件存在，返回绝对路径。"""
    if not version.artifact_path:
        raise ConflictError("该版本没有模型产物，无法部署")
    path = settings.absolute_path(version.artifact_path)
    if not path.exists():
        raise ConflictError(f"模型产物缺失：{version.artifact_path}")
    return str(path)
