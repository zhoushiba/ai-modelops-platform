"""数据库引擎、会话与建表逻辑。

默认 SQLite（``sqlite:///./data/app.db``），通过 ``DATABASE_URL`` 可切换
MySQL（``mysql+pymysql://``）或 PostgreSQL（``postgresql+psycopg://``）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def _build_engine() -> Engine:
    settings.ensure_dirs()
    kwargs: dict = {"echo": settings.db_echo, "future": True, "pool_pre_ping": True}
    if settings.is_sqlite:
        # 后台训练线程与请求线程会并发访问同一个 SQLite 文件
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
    engine = create_engine(settings.database_url, **kwargs)

    if settings.is_sqlite:

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            # WAL 让读与写（后台训练线程写日志）互不阻塞
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine: Engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """后台线程使用的会话上下文（自动提交/回滚）。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """创建全部表（幂等）。生产环境建议改用 Alembic 迁移。"""
    import app.models  # noqa: F401  确保模型已注册到 metadata

    Base.metadata.create_all(bind=engine)
