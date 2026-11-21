"""FastAPI 依赖：JWT 用户鉴权、API Key 鉴权（含令牌桶限流与配额校验）。"""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.crud import keys as key_crud
from app.database import get_db
from app.errors import ForbiddenError, OpenAIError, UnauthorizedError
from app.logging_utils import get_trace_id as current_trace_id
from app.models import ApiKey, User
from app.security import api_key_expired, decode_access_token, hash_api_key
from app.services.quota import quota_manager

bearer_scheme = HTTPBearer(auto_error=False, description="JWT 或平台 API Key（sk-mops- 前缀）")
API_KEY_PREFIX = "sk-mops-"


def _extract(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("缺少 Authorization 头", code=40101)
    return credentials.credentials.strip()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """解析后台 JWT，返回当前用户。"""
    token = _extract(credentials)
    if token.startswith(API_KEY_PREFIX):
        raise UnauthorizedError("该接口需要登录令牌，不能用 API Key 调用", code=40102)
    payload = decode_access_token(token)
    if not payload:
        raise UnauthorizedError("令牌无效或已过期", code=40103)
    subject = payload.get("sub")
    user = db.get(User, int(subject)) if subject and str(subject).isdigit() else None
    if user is None:
        raise UnauthorizedError("用户不存在", code=40104)
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise ForbiddenError("需要管理员权限")
    return user


def require_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> ApiKey:
    """校验 API Key（只比对哈希）、配额与令牌桶限流；失败返回 OpenAI 风格错误。"""
    if credentials is None or not credentials.credentials:
        raise OpenAIError(
            "Missing API key. Provide 'Authorization: Bearer sk-mops-...'.",
            status_code=401,
            error_type="authentication_error",
            code="invalid_api_key",
        )
    raw = credentials.credentials.strip()
    if not raw.startswith(API_KEY_PREFIX):
        raise OpenAIError(
            "Invalid API key prefix.",
            status_code=401,
            error_type="authentication_error",
            code="invalid_api_key",
        )
    key = key_crud.get_key_by_hash(db, hash_api_key(raw))
    if key is None or not key.active:
        raise OpenAIError(
            "Incorrect API key provided.",
            status_code=401,
            error_type="authentication_error",
            code="invalid_api_key",
        )
    if api_key_expired(key):
        raise OpenAIError(
            "This API key has expired.",
            status_code=401,
            error_type="authentication_error",
            code="invalid_api_key",
        )
    if key.token_quota and key.tokens_used >= key.token_quota:
        raise OpenAIError(
            f"Token quota exhausted ({key.tokens_used}/{key.token_quota}).",
            status_code=429,
            error_type="rate_limit_error",
            code="insufficient_quota",
        )
    decision = quota_manager.acquire(
        key.id,
        rate_per_min=key.rate_limit_per_min or settings.rate_limit_per_min,
        burst=key.burst or settings.rate_limit_burst,
    )
    if not decision.allowed:
        request.state.rate_limited = True
        raise OpenAIError(
            f"Rate limit exceeded: {int(decision.capacity)} requests burst, retry after {decision.retry_after}s.",
            status_code=429,
            error_type="rate_limit_error",
            code="rate_limit_exceeded",
            retry_after=decision.retry_after,
        )
    return key


def get_trace_id(request: Request) -> str:
    """取当前请求的 trace id（scope 优先，其次 contextvar），用于推理响应与调用日志。"""
    return request.scope.get("trace_id") or current_trace_id()
