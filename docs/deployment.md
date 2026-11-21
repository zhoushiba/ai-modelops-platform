# 部署与运维手册

> 目标环境：单机 Linux / Windows（演示）、Docker Compose（交付）、可扩展为 K8s（未内置）

## 1. 环境要求

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.11+ | 后端；已用 3.11.9 验证 |
| Node.js | 20+ | 前端构建；已用 Node 24.20 / npm 11.19 验证 |
| Docker / Compose | Docker 24+ / Compose v2 | 容器化部署（可选） |
| 数据库 | 无（默认 SQLite）/ MySQL 8.0 / PostgreSQL 16 | 本地零依赖，生产建议独立数据库 |
| 磁盘 | ≥ 2 GB | 依赖 + 模型产物（演示数据集很小） |

## 2. 本地运行（推荐用于验收）

```bash
# 1) 后端
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2) 前端（另开终端）
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173
```

验证：

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","app":"AI ModelOps Platform","version":"1.0.0","env":"dev","database":"sqlite","api_prefix":"/api","demo_api_key_created":true}

cd backend && python -m pytest -q          # 35 passed
python scripts/smoke_test.py               # 端到端冒烟
```

前端生产构建与本地预览（预览服务器同样把 `/api`、`/v1` 代理到 8000）：

```bash
cd frontend
npm run build
npm run preview      # 默认 4173；端口被占用时可 -- --port 4417
```

## 3. Docker Compose 部署

```bash
cp .env.example .env      # 修改 MYSQL_*、JWT_SECRET、ADMIN_PASSWORD
docker compose up --build -d
docker compose ps
```

| 服务 | 端口 | 说明 |
| --- | --- | --- |
| `mysql` | 3306 | MySQL 8，`utf8mb4`，首启执行 `db/init.sql`，数据在具名卷 `mysql-data` |
| `backend` | 8000 | FastAPI（等待 MySQL healthy 后启动），产物在具名卷 `modelops-storage` |
| `frontend` | 8080 | Nginx 托管静态资源，`/api/`、`/v1/` 反代 `backend:8000` |

访问 <http://127.0.0.1:8080/#/login>，用 `.env` 中的 `ADMIN_USERNAME/ADMIN_PASSWORD` 登录。

常用命令：

```bash
docker compose logs -f backend        # 看日志
docker compose exec backend python -m pytest -q
docker compose exec mysql mysql -umodelops -pmodelops123 modelops -e "show tables;"
docker compose down                   # 停止（保留数据卷）
docker compose down -v                # 停止并清空数据卷（重置演示环境）
```

## 4. 环境变量

完整清单见仓库根 `.env.example`。关键项：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ENV` | `dev` | 运行环境标识，出现在 `/health` |
| `DATABASE_URL` | `sqlite:///./data/app.db` | 连接串；MySQL/PostgreSQL 需装驱动 |
| `STORAGE_DIR` | `./storage` | 数据集/模型产物目录 |
| `MAX_UPLOAD_MB` | `20` | 单次上传上限（Nginx `client_max_body_size` 需同步） |
| `JWT_SECRET` | 开发默认值 | **生产必须替换**，否则令牌可伪造 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `720` | 登录有效期 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `admin123` | 首次启动 seed 的账号 |
| `WORKER_CONCURRENCY` | `2` | 训练 worker 线程数 |
| `TRAINING_INLINE` | `false` | `true` 时同步训练（测试用） |
| `SEED_SAMPLES` | `true` | 是否导入演示数据集/评测集/Prompt |
| `RATE_LIMIT_PER_MIN` / `RATE_LIMIT_BURST` | `60` / `10` | 新建 API Key 的默认限流 |
| `TOKEN_QUOTA` | `200000` | 新建 API Key 默认 token 配额 |
| `UPSTREAM_LLM_BASE_URL` / `UPSTREAM_LLM_API_KEY` / `UPSTREAM_LLM_MODEL` | 空 / 空 / `gpt-4o-mini` | 可选上游大模型，留空则用本地引擎 |
| `CORS_ORIGINS` | 本地 5173/4173 | 逗号分隔；容器部署走同源反代通常无需改 |

## 5. 生产部署建议

1. **反向代理与 HTTPS**：Nginx（或云 LB）终止 TLS，前端与后端同域，避免额外 CORS 配置；`/v1/` 必须关闭响应缓冲以支持 SSE。
2. **密钥管理**：`JWT_SECRET`、数据库口令、上游 LLM Key 用环境变量或密钥管理服务注入，禁止写进镜像。
3. **数据库**：使用 MySQL 8 / PostgreSQL 16，独立实例 + 定时备份；接入 Alembic 管理表结构变更。
4. **存储**：多副本部署时把 `STORAGE_DIR` 换成共享存储（NFS/S3/MinIO），否则各副本只能看到自己的产物。
5. **训练进程**：`WORKER_CONCURRENCY` 按 CPU 核数调整；重训练场景建议外置队列（Celery/RQ）并把 worker 拆成独立进程。
6. **可观测**：接入 Prometheus 指标与集中式日志，保留 `trace_id` 贯穿；`/health` 用于存活探针。
7. **安全**：
   - 修改默认管理员口令，禁用演示账号前先创建新账号；
   - API Key 按业务方分发并设置配额；
   - 上传接口限制类型与大小（`MAX_UPLOAD_MB`、Nginx `client_max_body_size`）；
   - 不要把 `backend/data/` 与 `backend/storage/` 提交到仓库。

## 6. 数据备份与恢复

```bash
# 备份
cp backend/data/app.db backup/app-$(date +%F).db                 # SQLite
mysqldump -umodelops -p modelops > backup/modelops-$(date +%F).sql   # MySQL
tar -czf backup/storage-$(date +%F).tar.gz -C backend storage

# 恢复
cp backup/app-2026-11-21.db backend/data/app.db
tar -xzf backup/storage-2026-11-21.tar.gz -C backend
```

**先还原数据库、再还原存储目录**，保证记录中的相对路径能命中文件。

## 7. 升级与回滚

1. 代码升级前备份数据库与 `storage/`。
2. 若表结构有变更：执行 Alembic 迁移（当前版本为 `create_all`，加字段需手动迁移）。
3. 后端与前端可独立升级；前端为纯静态资源，支持灰度发布。
4. 回滚：切回上一个镜像 tag / git 提交，数据库用备份恢复；模型侧回滚使用平台「模型注册表 → 回滚」把生产版本指回历史版本。

## 8. 故障排查

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| 启动报 `database is locked` | 多个进程共用同一 SQLite 文件 | 单进程运行，或改用 MySQL/PostgreSQL |
| `503` / 连接被拒（Compose） | backend 等待 MySQL 健康检查未通过 | `docker compose logs mysql` 检查口令与端口 |
| `/v1/*` 返回 401 `invalid_api_key` | Key 错误 / 已禁用 / 过期 | 在「API Key 管理」新建并检查 `active` |
| `/v1/*` 返回 429 | 触发令牌桶或 token 配额 | 看响应头 `Retry-After`；调大 `rate_limit_per_min`/`token_quota` |
| 训练一直 `queued` | worker 未启动或并发占满 | 查日志 `training runner`；调大 `WORKER_CONCURRENCY` 或重启服务 |
| 部署 `starting` 卡住 | 模型产物缺失（storage 被清理） | 重新训练/注册，或恢复 `storage/` 后重启部署 |
| 页面空白但接口正常 | 静态资源 404（`base` 配置/部署路径） | 确认 `frontend/vite.config.ts` 的 `base: './'` 与 Nginx `root` 一致 |
| `/docs` 空白 | 旧版本依赖公网 CDN，离线环境加载失败 | 当前版本 Swagger 资源已本地化在 `backend/app/static/`，重启后端即可 |
| 训练报 `40031` | 超参越界 | 参考 `docs/api.md` 的超参区间 |

日志位置：本地默认输出到控制台（可重定向到 `backend/data/server.log`）；容器用 `docker compose logs`。每行访问日志都带 `trace_id`，结合 `/api/usage/logs` 可定位到具体调用。
