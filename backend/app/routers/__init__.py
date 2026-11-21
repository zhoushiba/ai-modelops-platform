"""路由层：每个模块一个 ``APIRouter``，由 ``app.main`` 统一挂载到 ``/api`` 前缀。"""

from __future__ import annotations

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

__all__ = [
    "apikeys",
    "auth",
    "dashboard",
    "datasets",
    "deployments",
    "evals",
    "inference",
    "prompts",
    "registry",
    "training",
]
