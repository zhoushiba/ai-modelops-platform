"""数据访问层（repository）。只做查询/持久化，不含业务规则。"""

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


def paginate(db: Session, stmt: Select, page: int, size: int) -> tuple[list, int]:
    """对任意 select 语句做分页，返回 ``(items, total)``。"""
    page = max(1, page)
    size = min(max(1, size), 200)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = list(db.scalars(stmt.offset((page - 1) * size).limit(size)).all())
    return items, int(total)
