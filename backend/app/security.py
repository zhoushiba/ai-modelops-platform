"""认证、密码哈希与 API Key 工具。

* 用户密码：PBKDF2-HMAC-SHA256（标准库实现，无需编译扩展）；
* 登录态：HS256 JWT；
* API Key：形如 ``sk-mops-<32位随机>``，数据库只保存 SHA-256 哈希与前 12 位前缀。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

PBKDF2_ITERATIONS = 120_000
API_KEY_PREFIX = "sk-mops-"


# --------------------------------------------------------------------------
# 密码
# --------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """生成 ``pbkdf2_sha256$iterations$salt$hash`` 格式的密码哈希。"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码，使用常量时间比较避免时序侧信道。"""
    try:
        algorithm, iterations, salt, expected = stored.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)
    )
    return hmac.compare_digest(digest.hex(), expected)


# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------
def create_access_token(subject: str, role: str = "admin", expires_minutes: int | None = None) -> str:
    """签发访问令牌。"""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "role": role, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    """解码访问令牌，非法/过期返回 ``None``。"""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None


# --------------------------------------------------------------------------
# API Key
# --------------------------------------------------------------------------
def hash_api_key(raw_key: str) -> str:
    """API Key 的存储哈希（SHA-256 十六进制）。"""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """生成 API Key，返回 ``(明文, 前缀, 哈希)``。明文只在创建响应中出现一次。"""
    raw = API_KEY_PREFIX + secrets.token_urlsafe(24)
    prefix = raw[:12] + "…" + raw[-4:]
    return raw, prefix, hash_api_key(raw)


def mask_key(prefix: str, key_hash: str) -> str:
    return prefix or f"sk-…{key_hash[:4]}"


def api_key_expired(value) -> bool:
    """判断 API Key 是否过期。

    同时兼容两种调用方式：直接传 ApiKey 实例（路由/依赖里的常见写法），
    或只传 expires_at 时间（单元测试里更直观）。
    """
    expires_at = getattr(value, "expires_at", value)
    if expires_at is None:
        return False
    return expires_at < datetime.now(timezone.utc).replace(tzinfo=None)


def b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")
