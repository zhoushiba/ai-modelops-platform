"""FastAPI 应用入口：路由装配、中间件、生命周期钩子。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db, session_scope
from app.errors import register_exception_handlers
from app.logging_utils import AccessLogMiddleware, TraceIdMiddleware, configure_logging
from app.routers import (
    apikeys,
    auth,
    dashboard,
    datasets,
    deployments,
    evals,
    inference,
    prompts,
    registry,
    training,
)
from app.seed import seed_all
from app.services.runtime import runtime_manager
from app.services.training_runner import training_runner

logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：建表、种子数据、拉起训练线程池、恢复运行中的部署；关闭：停线程池。"""
    configure_logging(settings.log_level)
    settings.ensure_dirs()
    init_db()
    app.state.demo_api_key = ""
    try:
        result = seed_all()
        app.state.demo_api_key = result.get("demo_api_key", "")
    except Exception:  # noqa: BLE001 - 种子失败不应阻塞服务启动
        logger.exception("初始化种子数据失败，服务继续启动")

    training_runner.start()
    try:
        recovered = training_runner.recover()
        if any(recovered.values()):
            logger.warning("训练任务恢复：%s", recovered)
    except Exception:  # noqa: BLE001
        logger.exception("训练任务恢复失败")

    try:
        with session_scope() as db:
            warmed = runtime_manager.warmup(db)
        logger.info("推理运行时预热：%s 个部署", warmed)
    except Exception:  # noqa: BLE001
        logger.exception("推理运行时预热失败")

    logger.info(
        "%s v%s 启动完成（env=%s, db=%s）",
        settings.app_name,
        settings.app_version,
        settings.env,
        "sqlite" if settings.is_sqlite else "external",
    )
    yield
    training_runner.stop()
    runtime_manager.clear()
    logger.info("服务已关闭")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "AI 模型全生命周期管理平台：数据集版本管理、异步训练、模型注册与回滚、"
        "一键部署、OpenAI 兼容推理网关、评测与 Prompt 实验。"
    ),
    lifespan=lifespan,
    # Swagger UI 资源改为本地托管（离线环境也能打开 /docs）
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id", "X-Response-Time-Ms"],
)
app.add_middleware(AccessLogMiddleware)
app.add_middleware(TraceIdMiddleware)

register_exception_handlers(app)

# 后台管理接口统一挂 /api 前缀
for module in (auth, datasets, training, registry, deployments, apikeys, evals, prompts, dashboard):
    app.include_router(module.router, prefix=settings.api_prefix)
    extra = getattr(module, "version_router", None)
    if extra is not None:
        app.include_router(extra, prefix=settings.api_prefix)

# OpenAI 兼容推理接口固定在 /v1（不带 /api 前缀）
app.include_router(inference.router)

# 本地托管的 Swagger UI 静态资源（backend/app/static），不依赖公网 CDN
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/docs", include_in_schema=False)
def swagger_ui():
    """交互式 API 文档。

    与 FastAPI 默认实现相比，JS/CSS 走本服务的 ``/static``，
    因此在完全离线的交付环境中也能正常打开与调试接口。
    """
    return get_swagger_ui_html(
        openapi_url=app.openapi_url or "/openapi.json",
        title=f"{settings.app_name} · API 文档",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
        swagger_favicon_url="/static/favicon-32x32.png",
    )


@app.get("/health", tags=["系统"], summary="健康检查")
def health() -> dict:
    """探活接口：不鉴权，供容器/K8s/负载均衡健康检查使用。"""
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.env,
        "database": "sqlite" if settings.is_sqlite else "external",
        "api_prefix": settings.api_prefix,
        "demo_api_key_created": bool(getattr(app.state, "demo_api_key", "")),
    }


@app.get("/", tags=["系统"], summary="服务首页")
def index() -> dict:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
        "openai_compatible": ["/v1/chat/completions", "/v1/embeddings", "/v1/models"],
    }
