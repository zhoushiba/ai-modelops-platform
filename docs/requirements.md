# 需求说明

> AI ModelOps Platform · AI 模型训练与推理服务平台
> 文档版本：v1.0（2026-11）· 对应代码版本：1.0.0

## 1. 背景与目标

AI 团队常见的问题是「训练脚本散落在个人电脑、模型文件靠微信传、上线靠手工改配置」。本项目的目标是把模型从数据到线上服务的链路做成**一个可运行、可交付、可演示的平台**，并以此验证 AI 平台工程师的核心能力：模型训练、推理服务、接口设计、部署与平台模块开发。

**一句话目标**：在单机上用一条命令启动，跑通「数据 → 训练 → 注册 → 部署 → 调用 → 观测 → 评测」全流程，且每一步都有 Web 界面与 HTTP 接口。

## 2. 用户角色

| 角色 | 关注点 | 主要使用页面 |
| --- | --- | --- |
| 平台管理员 | 账号、API Key、配额、部署与资源占用 | 看板、API Key 管理、部署管理 |
| 算法 / AI 开发工程师 | 数据集质量、训练参数、指标、版本对比、评测 | 数据集、训练任务、模型注册表、评测 |
| 业务应用开发 | 如何调用模型、限流与错误码、调用是否成功 | 部署与在线推理、API Key 管理、接口文档 |

## 3. 用户故事

| 编号 | 用户故事 | 验收要点 |
| --- | --- | --- |
| US-01 | 作为算法工程师，我上传一份带标签的工单 CSV，得到一个可训练的数据集版本 | 上传校验、行数/标签/切分统计、失败给出明确原因 |
| US-02 | 我想知道新版本数据比旧版本多了什么 | 版本对比给出新增/删除/标签变更数量与示例 |
| US-03 | 我用一组超参发起训练，能实时看到进度和逐轮指标 | 异步执行、可取消、日志与指标增量拉取 |
| US-04 | 训练完成后模型自动进入注册表，可设为生产或回滚 | 版本号自增、状态流转、Model Card 自动生成 |
| US-05 | 我把生产版本一键部署成在线服务，用 OpenAI SDK 直接调用 | `/v1/chat/completions` 兼容、别名路由、trace id |
| US-06 | 我能看到每个 Key 的调用量、token 用量与限流情况 | 用量聚合、日志明细、超限 429 + Retry-After |
| US-07 | 我用评测集对比两个版本谁更好 | 指标表 + 多 run 横向对比 |
| US-08 | 我改了一版 Prompt，想和旧版做 A/B 对比 | 模板变量渲染、同输入双输出、人工打分 |

## 4. 功能需求

### 4.1 数据集（FR-D）

| 编号 | 需求 | 实现位置 |
| --- | --- | --- |
| FR-D1 | 支持 CSV / JSONL 上传，字段映射（文本、标签、切分列） | `backend/app/services/dataset_service.py` |
| FR-D2 | 自动/按比例切分训练集与验证集，记录校验和 | 同上 + `backend/app/models.py` |
| FR-D3 | 质量报告：重复、空值、超长、长度分位数、标签分布、问题提示 | `dataset_service.quality_report` |
| FR-D4 | 版本对比与 CSV 导出 | `dataset_service.diff_versions` |
| FR-D5 | 样本分页预览（可按 split 过滤） | `backend/app/routers/datasets.py` |

### 4.2 训练（FR-T）

| 编号 | 需求 | 实现位置 |
| --- | --- | --- |
| FR-T1 | 训练任务异步排队，多 worker 消费，服务重启后可恢复 | `backend/app/services/training_runner.py` |
| FR-T2 | 文本分类训练器（TF-IDF 字符 n-gram + LogisticRegression），逐轮记录 loss/acc/f1 | `backend/app/trainers/classification.py` |
| FR-T3 | RAG 语料训练器（切片 + 哈希向量化索引） | `backend/app/trainers/rag.py` |
| FR-T4 | 超参合法性校验，非法参数返回 400/40031 而非 500 | `backend/app/trainers/base.py`、`app/errors.py` |
| FR-T5 | 任务可取消；日志与指标可增量拉取，支持 SSE 流 | `app/routers/training.py` |
| FR-T6 | 训练产物落盘并记录大小与 SHA-256 | `trainers/base.py` |

### 4.3 模型注册表（FR-M）

| 编号 | 需求 | 实现位置 |
| --- | --- | --- |
| FR-M1 | 训练完成自动注册（可关闭），也可手工补注册 | `app/routers/training.py`、`app/services/registry_service.py` |
| FR-M2 | 版本状态流转 staging / production / archived | `app/routers/registry.py` |
| FR-M3 | 回滚到任意历史版本 | `registry_service.rollback` |
| FR-M4 | 自动生成 Model Card（Markdown，含指标/超参/复现命令） | `registry_service.build_model_card` |
| FR-M5 | 指标导出 `metrics.json` | `app/routers/registry.py` |

### 4.4 部署与推理（FR-I）

| 编号 | 需求 | 实现位置 |
| --- | --- | --- |
| FR-I1 | 一键部署模型版本，支持别名、QPS 上限、启停 | `app/services/deployment_service.py` |
| FR-I2 | 运行态懒加载模型产物，避免重复反序列化 | `app/services/runtime.py` |
| FR-I3 | OpenAI 兼容 `POST /v1/chat/completions`（含流式）与 `POST /v1/embeddings` | `app/routers/inference.py`、`app/services/inference_service.py` |
| FR-I4 | 部署统计：请求量、错误率、平均延迟、按小时序列 | `deployment_service.stats` |
| FR-I5 | 控制台内置在线推理调试台（等价 curl、trace id、耗时） | `frontend/src/views/DeploymentsView.vue` |

### 4.5 平台治理（FR-G）

| 编号 | 需求 | 实现位置 |
| --- | --- | --- |
| FR-G1 | API Key 只存散列，明文仅创建时返回一次 | `app/crud/keys.py`、`app/security.py` |
| FR-G2 | 令牌桶限流 + token 配额，超限 429 + Retry-After | `app/services/quota.py`、`app/deps.py` |
| FR-G3 | 调用日志与用量聚合（按天/接口/Key/模型） | `app/crud/keys.py`、`app/routers/apikeys.py` |
| FR-G4 | 评测：评测集上传、跑评测、多版本对比 | `app/services/eval_service.py` |
| FR-G5 | Prompt 模板 + 渲染 + A/B 实验与打分 | `app/services/prompt_engine.py`、`app/routers/prompts.py` |
| FR-G6 | 全局 trace id 与统一响应信封、统一错误码 | `app/logging_utils.py`、`app/errors.py` |

### 4.6 控制台（FR-F）

| 编号 | 需求 | 实现位置 |
| --- | --- | --- |
| FR-F1 | 登录页 + JWT 会话保持 + 401 自动跳转 | `frontend/src/views/LoginView.vue`、`src/api/http.ts` |
| FR-F2 | 看板：核心计数、今日调用、趋势、最近任务与调用 | `frontend/src/views/DashboardView.vue` |
| FR-F3 | 8 个业务页面（数据集/训练/注册表/部署/评测/Prompt/Key）均具备加载态、空态、错误重试 | `frontend/src/components/AsyncState.vue` 等 |
| FR-F4 | 全站 hash 路由，静态托管无需服务端 rewrite | `frontend/src/router/index.ts` |

## 5. 非功能需求

| 编号 | 类别 | 要求 | 现状 |
| --- | --- | --- | --- |
| NFR-1 | 开箱即用 | 默认零外部依赖（SQLite + 本地磁盘 + CPU 训练） | 满足 |
| NFR-2 | 性能 | 演示数据（300 行、8 类）训练在秒级完成；单条推理 P95 < 50ms | 实测训练 3~8s，推理毫秒级 |
| NFR-3 | 可靠性 | 训练任务可恢复、可取消；推理错误返回结构化错误体 | 满足 |
| NFR-4 | 安全 | 口令 PBKDF2 散列、Key 散列存储、JWT 过期时间可配 | 满足 |
| NFR-5 | 可观测 | 全局 trace id、访问日志、调用日志、指标接口 | 满足 |
| NFR-6 | 可测试 | 测试不依赖外部服务，可在 CI 中运行 | 35 个用例，临时 SQLite |
| NFR-7 | 可交付 | README + 6 篇文档 + 截图 + 一键 compose | 满足 |

## 6. 验收标准

1. `cd backend && python -m pytest -q` 输出 `35 passed`。
2 `python -m uvicorn app.main:app --port 8000` 后 `/health` 返回 200，`/docs` 可交互调试。
3. `cd frontend && npm install && npm run build` 成功，`npm run preview` 后 9 个页面可访问且数据来自真实接口。
4. `docker compose up --build` 可拉起 MySQL + 后端 + 前端（需本机有 Docker）。
5. README 的「快速开始」按步骤执行可复现。

## 7. 范围外（明确不做）

- 不做多租户与细粒度 RBAC（当前仅管理员演示账号）。
- 不做真实 GPU 训练 / 分布式训练（训练器是可插拔接口，本地实现为 CPU 友好版）。
- 不做模型服务 K8s 编排与自动扩缩容。
- 不内置计费系统（配额与用量统计已具备，结算不在范围内）。
