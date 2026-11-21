"""认证接口：登录换 JWT、读取当前用户。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import serializers
from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.errors import UnauthorizedError, envelope
from app.models import User
from app.schemas import LoginRequest, TokenOut
from app.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=None)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    """用户名密码登录，返回 JWT 与用户信息。"""
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise UnauthorizedError("用户名或密码错误", code=40110)
    token = create_access_token(
        subject=str(user.id),
        role=user.role,
        expires_minutes=settings.access_token_expire_minutes,
    )
    expires_in = settings.access_token_expire_minutes * 60
    data = TokenOut(
        access_token=token,
        expires_in=expires_in,
        user=serializers.user(user),  # type: ignore[arg-type]
    )
    return envelope(data.model_dump())


@router.get("/me", response_model=None)
def me(user: User = Depends(get_current_user)) -> dict:
    """返回当前登录用户。"""
    return envelope(serializers.user(user))
