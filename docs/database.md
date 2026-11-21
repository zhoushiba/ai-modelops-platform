# 数据库设计

> ORM 定义：`backend/app/models.py` · 连接配置：`DATABASE_URL`（`backend/app/config.py`）
> 默认 SQLite（`backend/data/app.db`），生产可切 MySQL 8 / PostgreSQL 16，业务代码无需改动。

## 1. 数据模型总览

19 张表按领域分为五组：

| 分组 | 表 | 说明 |
| --- | --- | --- |
| 账号 | `user` | 平台账号（当前为管理员演示账号） |
| 数据 | `dataset`、`dataset_version`、`dataset_sample` | 数据集、版本、样本明细 |
| 训练 | `training_job`、`training_log`、`training_metric` | 训练任务、日志、逐轮指标 |
| 模型 | `model_registry`、`model_version` | 模型（逻辑名）与其版本 |
| 部署与调用 | `deployment`、`api_key`、`usage_record`、`inference_log` | 在线部署、密钥、用量、调用日志 |
| 评测 | `eval_dataset`、`eval_run`、`eval_result` | 评测集、评测批次、逐样本结果 |
| Prompt | `prompt_template`、`prompt_experiment` | 模板、A/B 实验 |
| RAG | `rag_chunk` | RAG 语料切片与向量（训练产物落库副本） |

## 2. 实体关系

```mermaid
erDiagram
    USER ||--o{ DATASET : owns
    DATASET ||--o{ DATASET_VERSION : has
    DATASET_VERSION ||--o{ DATASET_SAMPLE : contains
    DATASET_VERSION ||--o{ TRAINING_JOB : trains
    TRAINING_JOB ||--o{ TRAINING_LOG : logs
    TRAINING_JOB ||--o{ TRAINING_METRIC : metrics
    TRAINING_JOB |o--o{ MODEL_VERSION : produces
    MODEL_REGISTRY ||--o{ MODEL_VERSION : versions
    MODEL_VERSION ||--o{ DEPLOYMENT : deployed_as
    MODEL_VERSION ||--o{ EVAL_RUN : evaluated_by
    EVAL_DATASET ||--o{ EVAL_RUN : uses
    EVAL_RUN ||--o{ EVAL_RESULT : results
    API_KEY ||--o{ USAGE_RECORD : bills
    API_KEY ||--o{ INFERENCE_LOG : calls
    DEPLOYMENT ||--o{ INFERENCE_LOG : serves
    DEPLOYMENT ||--o{ USAGE_RECORD : meters
    PROMPT_TEMPLATE ||--o{ PROMPT_EXPERIMENT : ab_test
    TRAINING_JOB ||--o{ RAG_CHUNK : builds
```

## 3. 表结构要点

### 3.1 数据集域

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `dataset` | `name`(唯一)、`task_type`、`description`、`owner_id` | 逻辑数据集，`task_type` 决定可用训练器 |
| `dataset_version` | `dataset_id`、`version`、`row_count`、`train_count`、`val_count`、`label_count`、`checksum`、`stats`(JSON)、`file_path` | 每次上传+1；`(dataset_id, version)` 唯一；`stats` 存标签分布与长度统计 |
| `dataset_sample` | `dataset_version_id`、`row_index`、`text`、`label`、`split`、`meta`(JSON) | 样本明细，供分页预览；`split` ∈ `train/val` |

### 3.2 训练域

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `training_job` | `name`、`dataset_version_id`、`task_type`、`base_model`、`hyperparams`(JSON)、`status`、`progress`、`error`、`artifact_path`、`artifact_size`、`artifact_sha256`、`metrics`(JSON)、`model_version_id` | `status` ∈ `queued/running/succeeded/failed/canceled`；`metrics` 为最终指标快照 |
| `training_log` | `job_id`、`ts`、`level`、`message` | 增量日志（`after_id` 拉取） |
| `training_metric` | `job_id`、`epoch`、`name`、`value` | 长表存储，便于前端画曲线/表格 |

### 3.3 模型与部署域

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `model_registry` | `name`(唯一)、`task_type`、`description` | 模型逻辑名，例如 `ticket-intent-classifier` |
| `model_version` | `registry_id`、`version`、`status`、`framework`、`metrics`(JSON)、`hyperparams`(JSON)、`labels`(JSON)、`artifact_*`、`training_job_id`、`model_card_md` | `(registry_id, version)` 唯一；`status` ∈ `staging/production/archived` |
| `deployment` | `name`(唯一)、`model_version_id`、`alias`、`status`、`qps_limit`、`request_count`、`error_count`、`avg_latency_ms`、`last_error` | `status` ∈ `starting/running/stopped`；`alias` 可作为推理 `model` 参数 |
| `api_key` | `name`、`prefix`、`key_hash`(唯一)、`scopes`、`rate_limit_per_min`、`burst`、`token_quota`、`tokens_used`、`requests_used`、`active`、`last_used_at` | 只存 SHA-256 散列；明文仅创建时返回一次 |
| `usage_record` | `api_key_id`、`deployment_id`、`endpoint`、`tokens`、`created_at` | 按次记账，供 `/api/usage/*` 聚合 |
| `inference_log` | `trace_id`、`api_key_id`、`deployment_id`、`endpoint`、`model_name`、`status_code`、`latency_ms`、`prompt_tokens`、`completion_tokens`、`prompt_preview`、`response_preview`、`error` | 调用明细，预览字段截断存储 |

### 3.4 评测与 Prompt 域

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `eval_dataset` | `name`(唯一)、`task_type`、`file_path`、`row_count` | 评测集，复用数据集上传校验 |
| `eval_run` | `model_version_id`、`eval_dataset_id`、`status`、`metrics`(JSON)、`error` | 一次评测；同步执行 |
| `eval_result` | `run_id`、`sample_index`、`input_text`、`expected`、`predicted`、`correct`、`score`、`latency_ms` | 逐样本明细，`run_id` 级联删除 |
| `prompt_template` | `name`(唯一)、`content`、`variables`(JSON)、`tags`、`version` | 内容变更自动 `version+1` 并重抽变量 |
| `prompt_experiment` | `template_a_id`、`template_b_id`、`input_text`、`variables`(JSON)、`output_a`、`output_b`、`latency_a_ms`、`latency_b_ms`、`engine`、`score_a`、`score_b`、`notes` | A/B 实验结果与人工打分 |
| `rag_chunk` | `training_job_id`、`chunk_index`、`text`、`vector`、`meta` | RAG 训练产物的库内副本，便于检索演示 |

## 4. 约束与索引

- **唯一约束**：`user.username`、`dataset.name`、`model_registry.name`、`deployment.name`、`api_key.key_hash`、`eval_dataset.name`、`prompt_template.name`；组合唯一 `dataset_version(dataset_id, version)`、`model_version(registry_id, version)`。
- **外键级联**：`dataset_version`、`dataset_sample`、`training_log`、`training_metric`、`model_version`、`eval_result`、`rag_chunk` 对父表使用 `ON DELETE CASCADE`，删除数据集/任务/评测批次时自动清理子记录。
- **索引**：所有外键、所有状态字段、所有时间字段（`queued_at`、`created_at`、`ts`）、`inference_log.trace_id`、`api_key.key_hash` 均建索引，覆盖列表筛选、时间聚合与 trace 追查三类查询。
- **JSON 字段**：`stats`、`hyperparams`、`metrics`、`variables`、`meta` 用文本存 JSON；SQLite/MySQL 均可读写，业务侧统一用 `json.dumps/loads` 序列化。

## 5. 文件存储

数据库只存路径与校验信息，二进制落本地目录（`STORAGE_DIR`，默认 `backend/storage`）：

```text
storage/
├── datasets/            # 数据集版本 CSV（<dataset>-v<version>.csv）
├── models/
│   └── job-<id>/        # 训练产物 model.joblib + 元数据
└── eval/                # 评测集文件
```

`DATABASE_URL` 与 `STORAGE_DIR` 同时迁移即可搬迁整套环境；`storage/` 已在 `.gitignore` 中排除，避免把大文件提交进仓库。

## 6. 迁移与演进策略

- **当前**：应用启动时 `Base.metadata.create_all()` 幂等建表，适合单机演示与课程交付。
- **生产建议**：接入 Alembic，把 `create_all` 换成迁移脚本；字段变更走 `alembic revision --autogenerate`。
- **切换数据库**：仅需 `bash DATABASE_URL=mysql+pymysql://user:pwd@host:3306/modelops` 并安装对应驱动（`requirements.txt` 中被注释的 `PyMySQL` / `psycopg`），建表语句由 ORM 方言自动适配。
- **清理策略**：`inference_log` / `usage_record` 增长最快，建议按月分区或定期归档；本项目提供 `GET /api/usage/*` 聚合查询，未内置定时清理，生产可加定时任务。

## 7. 备份与恢复

```bash
# SQLite
cp backend/data/app.db backup/app-$(date +%F).db
# MySQL
mysqldump -u modelops -p modelops > backup/modelops-$(date +%F).sql
# 同时备份产物目录
tar -czf backup/storage-$(date +%F).tar.gz -C backend storage
```

恢复时先还原数据库、再还原 `storage/`，保证记录里的路径有效。
