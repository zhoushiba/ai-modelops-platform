# 接口文档

> 基地址：`http://127.0.0.1:8000` · 交互式文档：`/docs`（Swagger UI，静态资源本地托管，可离线使用）· OpenAPI：`/openapi.json`

## 1. 通用约定

### 1.1 响应信封（管理接口 `/api/**`）

```json
{ "code": 0, "message": "ok", "data": { }, "trace_id": "f2c1a9d0e8b24f0f" }
```

- `code == 0` 表示成功，非 0 为业务错误码；HTTP 状态码同时反映错误类别。
- `X-Trace-Id` 响应头与 `trace_id` 一致，可凭它到调用日志里定位。
- `/v1/**` 与 `/health` **不使用信封**，遵循各自原生结构（OpenAI 兼容）。

### 1.2 分页

```json
{ "items": [], "total": 123, "page": 1, "size": 20 }
```

参数统一为 `page`（从 1 开始）与 `size`（默认 20）。

### 1.3 错误码

| HTTP | code | 含义 |
| --- | --- | --- |
| 400 | 40000 | 请求参数或业务前置条件不满足 |
| 400 | 40031 | 训练超参非法（由训练器校验） |
| 401 | 40100 | 未认证 / token 无效或过期 |
| 401 | 40110 | 用户名或密码错误 |
| 401 | 40101/40102/40103/40104 | API Key 缺失/无效/禁用/过期 |
| 403 | 40300 | 无权限 |
| 404 | 40400 | 资源不存在 |
| 409 | 40900 | 唯一性冲突（如数据集重名） |
| 422 | 42200 | Pydantic 字段校验失败 |
| 429 | 42900 | 触发限流（响应头含 `Retry-After`） |
| 500 | 50000/50002 | 服务端错误（含 trace id，便于追日志） |

推理接口错误为 OpenAI 风格：

```json
{ "error": { "message": "Rate limit exceeded", "type": "rate_limit_error", "code": "rate_limit_exceeded" } }
```

### 1.4 认证

| 面 | 方式 | 说明 |
| --- | --- | --- |
| 管理接口 `/api/**` | `Authorization: Bearer <JWT>` | `POST /api/auth/login` 获取，默认 720 分钟 |
| 推理接口 `/v1/**` | `Authorization: Bearer <API Key>` | 在「API Key 管理」创建，明文仅展示一次 |

## 2. 认证与看板

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login` | 账号登录，返回 `access_token`、`expires_in`、`user` |
| GET | `/api/auth/me` | 当前登录用户 |
| GET | `/api/dashboard/summary` | 平台概览（计数、今日调用/token、成功率、最近任务与调用） |
| GET | `/api/dashboard/timeseries?days=7` | 按天调用趋势 `{items:[{date,requests,tokens,errors}]}` |

```bash
curl -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "expires_in": 43200,
    "user": { "id": 1, "username": "admin", "display_name": "平台管理员", "role": "admin" }
  },
  "trace_id": "9c1f..."
}
```

## 3. 数据集

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/datasets?q&task_type&page&size` | 列表（含 `latest_version`） |
| POST | `/api/datasets` | 上传数据集（multipart），返回 `{dataset, version}` |
| GET | `/api/datasets/{id}` | 详情（含 `versions[]`） |
| DELETE | `/api/datasets/{id}` | 删除数据集及其版本/样本 |
| POST | `/api/datasets/{id}/versions` | 追加新版本（multipart），返回 `{dataset, version}` |
| GET | `/api/datasets/{id}/versions` | 版本列表 |
| GET | `/api/dataset-versions/{vid}` | 版本详情（附 `dataset_name`、`task_type`） |
| GET | `/api/dataset-versions/{vid}/samples?split&page&size` | 样本分页预览 |
| GET | `/api/dataset-versions/{vid}/quality` | 质量报告 |
| GET | `/api/dataset-versions/{vid}/diff?against=<vid>` | 与另一版本对比 |
| GET | `/api/dataset-versions/{vid}/download` | 导出 CSV |

```bash
curl -X POST http://127.0.0.1:8000/api/datasets \
  -H "Authorization: Bearer $TOKEN" \
  -F "name=客服工单分类 v2" \
  -F "task_type=text_classification" \
  -F "text_field=text" -F "label_field=label" -F "val_ratio=0.2" \
  -F "file=@backend/samples/tickets_train.csv"
```

质量报告结构：`row_count`、`label_count`、`duplicate_count/ratio`、`empty_count`、`too_long_count`、`label_distribution`、`split_distribution`、`length_stats{min,max,avg,p50,p95}`、`issues[]`。

## 4. 训练

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/training/trainers` | 可用训练器（`task_type`、`display_name`、`base_models`），返回数组 |
| GET | `/api/training/jobs?status&q&page&size` | 任务列表 |
| POST | `/api/training/jobs` | 提交训练任务 |
| GET | `/api/training/jobs/{id}` | 任务详情（含 `logs[]`、`metrics_series[]`） |
| GET | `/api/training/jobs/{id}/logs?after_id&limit` | 增量日志 `{items,status,progress}` |
| GET | `/api/training/jobs/{id}/metrics` | 逐轮指标 `{items:[{epoch,name,value}]}` |
| POST | `/api/training/jobs/{id}/cancel` | 取消任务 |
| POST | `/api/training/jobs/{id}/register` | 补注册为模型版本（`model_name` 可空，回落任务名） |
| GET | `/api/training/jobs/{id}/stream` | SSE 推送日志与状态 |

```bash
curl -X POST http://127.0.0.1:8000/api/training/jobs \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "name": "客服工单意图分类 · TF-IDF + LR",
    "dataset_version_id": 1,
    "task_type": "text_classification",
    "base_model": "tfidf-logreg",
    "hyperparams": {"epochs": 6, "lr": 1.0, "max_len": 256, "max_features": 8000, "ngram_max": 2},
    "auto_register": true,
    "register_as": "ticket-intent-classifier"
  }'
```

超参（`task_type` 不同字段不同）：

| 字段 | 适用 | 默认 | 区间 |
| --- | --- | --- | --- |
| `epochs` | 分类 | 6 | 1–50 |
| `lr` | 分类 | 1.0 | > 0（作为 LogisticRegression 的 C） |
| `max_len` | 分类 | 256 | 16–4096 |
| `max_features` | 分类 | 8000 | 100–200000 |
| `ngram_max` | 分类 | 2 | 1–3 |
| `chunk_size` | RAG | 220 | ≥ 20 |
| `chunk_overlap` | RAG | 40 | 0 ≤ overlap < chunk_size |
| `embedding_dim` | RAG | 384 | 64–4096 |

## 5. 模型注册表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/models?q&task_type&page&size` | 模型列表（含版本数与生产版本） |
| GET | `/api/models/{rid}` | 模型详情（含 `versions[]`） |
| GET | `/api/models/versions/{vid}` | 版本详情（附训练任务信息） |
| PATCH | `/api/models/versions/{vid}/status` | `{status: staging\|production\|archived, note}` |
| GET | `/api/models/versions/{vid}/card` | Model Card：`{model_version_id, model_card, markdown}` |
| GET | `/api/models/versions/{vid}/metrics.json` | 指标 JSON 下载 |
| POST | `/api/models/{rid}/rollback` | `{to_version}` 回滚到历史版本 |

## 6. 部署与在线推理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/deployments?status` | 部署列表 |
| POST | `/api/deployments` | `{name, model_version_id, qps_limit, alias, description}`，响应含 `curl` 示例 |
| GET | `/api/deployments/{id}` | 详情 |
| POST | `/api/deployments/{id}/start` \| `/stop` | 启动 / 停止 |
| DELETE | `/api/deployments/{id}` | 删除 |
| GET | `/api/deployments/{id}/stats` | 统计（含 `series[]` 按小时序列） |
| GET | `/api/deployments/{id}/timeseries?hours=24` | 时间序列 |

### 6.1 Chat Completions（OpenAI 兼容）

```bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-mops-xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ticket-intent-online",
    "messages": [{"role": "user", "content": "我的订单三天没发货了"}],
    "temperature": 0.2,
    "max_tokens": 128
  }'
```

```json
{
  "id": "chatcmpl-1a2b3c",
  "object": "chat.completion",
  "created": 1732200000,
  "model": "ticket-intent-online",
  "choices": [{ "index": 0, "message": { "role": "assistant", "content": "..." }, "finish_reason": "stop" }],
  "usage": { "prompt_tokens": 12, "completion_tokens": 18, "total_tokens": 30 },
  "modelops": { "trace_id": "9c1f8a...", "deployment_id": 1, "latency_ms": 6.4 }
}
```

- `model` 可填部署名或部署别名；`stream: true` 时返回 SSE：`data: {...}` 逐块，末行 `data: [DONE]`。

### 6.2 Embeddings

```bash
curl -X POST http://127.0.0.1:8000/v1/embeddings \
  -H "Authorization: Bearer sk-mops-xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"model":"support-rag","input":["第一段文本","第二段文本"],"encoding_format":"float"}'
```

返回 `{"object":"list","data":[{"object":"embedding","index":0,"embedding":[384 维浮点]}],"model":...,"usage":{...}}`，默认 384 维；`encoding_format=base64` 时按官方格式编码。

### 6.3 模型列表

`GET /v1/models` 返回当前运行中的部署（OpenAI `list` 结构），便于 SDK 直接列举。

## 7. API Key 与用量

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/api-keys` | Key 列表（不返回明文与散列） |
| POST | `/api/api-keys` | `{name, rate_limit_per_min, burst, token_quota, scopes}`，响应额外含 `plain_key`（仅此一次） |
| PATCH | `/api/api-keys/{id}` | 修改 `active`、`name`、限流与配额 |
| DELETE | `/api/api-keys/{id}` | 删除 |
| GET | `/api/usage/summary?days=7` | 汇总：总量、token 拆分、错误率、平均延迟、按天/接口/Key/模型聚合 |
| GET | `/api/usage/logs?page&size&endpoint&status_code&q` | 调用日志分页 |
| GET | `/api/usage/recent?limit=20` | 最近调用（看板用） |
| GET | `/api/usage/today` | 今日实时指标 |

## 8. 评测

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/evals/datasets` | 评测集列表 |
| POST | `/api/evals/datasets` | 上传评测集（multipart） |
| GET | `/api/evals/runs?model_version_id` | 评测记录列表 |
| POST | `/api/evals/runs` | `{model_version_id, eval_dataset_id, name, max_samples}`，同步执行 |
| GET | `/api/evals/runs/{id}?include_results=true` | 详情（含逐样本结果） |
| POST | `/api/evals/compare` | `{run_ids:[...]}`，2–8 个批次对比 |

对比响应：

```json
{
  "runs": [{ "id": 1, "model_name": "ticket-intent-classifier", "model_version_number": 1 }],
  "metric_names": ["accuracy", "precision_macro", "recall_macro", "f1_macro", "f1_weighted", "avg_latency_ms", "sample_count"],
  "rows": [
    { "metric": "accuracy", "values": [{ "run_id": 1, "value": 1.0 }] },
    { "metric": "avg_latency_ms", "values": [{ "run_id": 1, "value": 1.8 }] }
  ]
}
```

## 9. Prompt 模板与 A/B

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/prompts` | 模板列表 |
| POST | `/api/prompts` | `{name, description, content, tags, variables}` |
| GET/PUT/DELETE | `/api/prompts/{id}` | 详情 / 更新（内容变更 `version+1`）/ 删除 |
| POST | `/api/prompts/{id}/render` | `{variables:{...}}` → `{rendered, missing_variables}` |
| GET | `/api/prompts/experiments?template_id` | A/B 实验列表 |
| POST | `/api/prompts/experiments` | `{name, template_a_id, template_b_id, input_text, variables}` |
| GET | `/api/prompts/experiments/{id}` | 实验详情 |
| POST | `/api/prompts/experiments/{id}/score` | `{score_a, score_b, notes}` |

模板占位符语法为 `{{变量名}}`；渲染时缺失的变量会出现在 `missing_variables` 中。实验默认使用本地抽取式引擎（`local-extractive-v1`），配置上游 LLM 后改走真实模型。

## 10. 系统

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 探活：状态、版本、环境、数据库类型、是否已生成演示 Key |
| GET | `/` | 服务首页：名称、版本、文档与兼容接口列表 |
| GET | `/docs` | Swagger UI（本地静态资源） |
| GET | `/openapi.json` | OpenAPI 3.1 描述 |
