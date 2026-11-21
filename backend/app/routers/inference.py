"""OpenAI 兼容推理接口：``/v1/chat/completions``、``/v1/embeddings``、``/v1/models``。

鉴权使用平台 API Key（``Authorization: Bearer sk-mops-...``），响应体完全遵循 OpenAI 协议，
额外字段放在 ``modelops`` 命名空间下（trace_id、部署信息、检索引用），不影响官方 SDK 解析。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_trace_id, require_api_key
from app.models import ApiKey
from app.schemas import ChatCompletionRequest, EmbeddingRequest
from app.services import inference_service

router = APIRouter(prefix="/v1", tags=["推理服务（OpenAI 兼容）"])


@router.post("/chat/completions", response_model=None)
def chat_completions(
    request: Request,
    payload: ChatCompletionRequest,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_api_key),
    trace_id: str = Depends(get_trace_id),
):
    """OpenAI 兼容对话补全；``stream=true`` 时返回 SSE 流。"""
    deployment = inference_service.resolve_deployment(db, payload.model)
    if payload.stream:
        return StreamingResponse(
            inference_service.stream_completion(db, deployment, payload, key, trace_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return inference_service.chat_completion(db, deployment, payload, key, trace_id)


@router.post("/embeddings")
def create_embeddings(
    payload: EmbeddingRequest,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_api_key),
    trace_id: str = Depends(get_trace_id),
) -> dict:
    """OpenAI 兼容文本向量化，支持 ``encoding_format=float|base64`` 与 ``dimensions`` 截断。"""
    deployment = inference_service.resolve_deployment(db, payload.model)
    return inference_service.embeddings(db, deployment, payload, key, trace_id)


@router.get("/models")
def list_models(
    db: Session = Depends(get_db), _: ApiKey = Depends(require_api_key)
) -> dict:
    """列出当前处于 running 状态的推理服务（OpenAI 兼容 model 列表）。"""
    return inference_service.list_models(db)
