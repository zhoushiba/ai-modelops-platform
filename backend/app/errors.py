"""统一异常与统一响应体。

管理面接口（``/api/**``）返回 ``{code, message, data, trace_id}``；
OpenAI 兼容接口（``/v1/**``）与 ``/health`` 返回官方格式，不套信封。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.logging_utils import get_trace_id

logger = logging.getLogger("app.errors")


class AppError(Exception):
    """业务异常：携带业务码、HTTP 状态码与可读消息。"""

    def __init__(
        self,
        message: str,
        code: int = 40000,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在", code: int = 40400) -> None:
        super().__init__(message, code=code, status_code=status.HTTP_404_NOT_FOUND)


class ConflictError(AppError):
    def __init__(self, message: str = "状态冲突", code: int = 40900) -> None:
        super().__init__(message, code=code, status_code=status.HTTP_409_CONFLICT)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "未认证或凭证已失效", code: int = 40100) -> None:
        super().__init__(message, code=code, status_code=status.HTTP_401_UNAUTHORIZED)


class ForbiddenError(AppError):
    def __init__(self, message: str = "无权访问", code: int = 40300) -> None:
        super().__init__(message, code=code, status_code=status.HTTP_403_FORBIDDEN)


class QuotaExceededError(AppError):
    """限流 / 配额超限，映射为 429。"""

    def __init__(self, message: str = "请求过于频繁", retry_after: int = 1, code: str = "rate_limit_exceeded") -> None:
        super().__init__(message, code=42900, status_code=status.HTTP_429_TOO_MANY_REQUESTS)
        self.retry_after = retry_after
        self.error_code = code


class OpenAIError(AppError):
    """OpenAI 兼容错误：``/v1/**`` 的异常必须返回官方错误结构而不是统一信封。"""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        *,
        error_type: str = "invalid_request_error",
        code: str | None = None,
        param: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message, code=status_code * 100, status_code=status_code)
        self.error_type = error_type
        self.upstream_code = code
        self.param = param
        self.retry_after = retry_after


def envelope(data: Any = None, message: str = "ok", code: int = 0) -> dict:
    """统一成功响应体。"""
    return {"code": code, "message": message, "data": data, "trace_id": get_trace_id()}


def request_trace_id(request: Request) -> str:
    """从请求 scope 中取 trace id。

    统一异常处理器里必须优先读 ``scope["trace_id"]``：未捕获异常由最外层
    ``ServerErrorMiddleware`` 处理，此时 contextvar 可能已被重置。
    """
    return request.scope.get("trace_id") or get_trace_id()


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器（所有异常都转成统一响应体）。"""

    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        if isinstance(exc, OpenAIError):
            body = {
                "error": {
                    "message": exc.message,
                    "type": exc.error_type,
                    "param": exc.param,
                    "code": exc.upstream_code,
                }
            }
            headers = {}
            if exc.retry_after is not None:
                headers["Retry-After"] = str(exc.retry_after)
            return JSONResponse(status_code=exc.status_code, content=body, headers=headers)
        body = envelope(None, exc.message, exc.code)
        body["trace_id"] = request_trace_id(_request)
        if exc.details is not None:
            body["details"] = exc.details
        headers = {}
        if isinstance(exc, QuotaExceededError):
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(status_code=exc.status_code, content=body, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": ".".join(str(part) for part in err.get("loc", [])), "msg": err.get("msg", "")}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                **envelope(None, "参数校验失败", 42200),
                "trace_id": request_trace_id(_request),
                "details": details,
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("数据库异常: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={**envelope(None, "数据库操作失败", 50002), "trace_id": request_trace_id(_request)},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={**envelope(None, "服务器内部错误", 50000), "trace_id": request_trace_id(_request)},
        )
