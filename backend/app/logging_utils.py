"""结构化日志 + 全链路 trace id。

* 每个请求生成/透传 ``X-Trace-Id``，写入 contextvar，日志 JSON 中自带该字段；
* 训练线程会显式绑定所属任务的 trace id，便于把训练日志与请求日志串起来。
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone

from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

TRACE_HEADER = "X-Trace-Id"
_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")
_job_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("job_id", default="-")


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def get_trace_id() -> str:
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> None:
    _trace_id_var.set(trace_id)


def set_job_context(job_id: int | str) -> None:
    _job_id_var.set(str(job_id))


class JsonFormatter(logging.Formatter):
    """把日志格式化为单行 JSON，方便 ELK/Loki 采集。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": get_trace_id(),
            "job_id": _job_id_var.get(),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # 降低第三方噪音
    for noisy in ("uvicorn.access", "multipart", "httpx"):
        logging.getLogger(noisy).setLevel("WARNING")


class TraceIdMiddleware:
    """纯 ASGI 中间件：为每个请求注入 trace id。

    相比 ``BaseHTTPMiddleware``，纯 ASGI 实现有两个好处：
    1. 不额外创建 anyio 任务，避免上下文变量丢失；
    2. trace id 同时写入 ``scope["trace_id"]``，即使异常冒泡到最外层的
       ``ServerErrorMiddleware``（统一异常处理器所在层）也依然能取到，
       保证错误响应里的 trace_id 不会退化成 ``-``。
    """

    def __init__(self, app) -> None:  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send):  # noqa: ANN001, ANN204
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        trace_id = Headers(scope=scope).get(TRACE_HEADER) or new_trace_id()
        scope["trace_id"] = trace_id
        token = _trace_id_var.set(trace_id)
        started = time.perf_counter()

        async def send_with_trace(message):  # noqa: ANN001, ANN202
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((TRACE_HEADER.lower().encode(), trace_id.encode()))
                headers.append((b"x-response-time-ms", f"{(time.perf_counter() - started) * 1000:.1f}".encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace)
        finally:
            _trace_id_var.reset(token)


class AccessLogMiddleware(BaseHTTPMiddleware):
    """访问日志（结构化）：方法、路径、状态码、耗时。"""

    def __init__(self, app) -> None:  # noqa: ANN001
        super().__init__(app)
        self.logger = logging.getLogger("app.access")

    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = (time.perf_counter() - started) * 1000
        if not request.url.path.startswith(("/docs", "/openapi", "/redoc")):
            self.logger.info(
                "%s %s -> %s (%.1fms)",
                request.method,
                request.url.path,
                response.status_code,
                elapsed,
            )
        return response
