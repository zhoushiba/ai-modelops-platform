"""OpenAI 兼容推理服务：请求解析、响应组装、用量记账、调用日志。

平台把训练好的模型包装成 OpenAI 协议：
- ``POST /v1/chat/completions``：分类模型返回判定结果，RAG 索引返回检索增强答案；
- ``POST /v1/embeddings``：返回归一化向量；
- ``GET /v1/models``：列出运行中的部署。
"""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from typing import Iterable

import numpy as np
from sqlalchemy.orm import Session

from app.crud import deployments as deployment_crud
from app.crud import keys as key_crud
from app.errors import OpenAIError
from app.models import ApiKey, Deployment
from app.services.runtime import ModelRuntime, runtime_manager

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- 工具
def estimate_tokens(text: str) -> int:
    """粗略 token 估算：中文按 1.5 字符/token，其余按 4 字符/token。

    平台不内置 tokenizer（避免额外依赖），用量记账以估算值为准并在文档中说明。
    """
    if not text:
        return 0
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    other = max(0, len(text) - cjk)
    return max(1, int(round(cjk / 1.5 + other / 4)))


def message_text(message) -> str:  # noqa: ANN001
    """把 OpenAI 消息内容（字符串或多模态数组）拍平成纯文本。"""
    content = getattr(message, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def last_user_text(messages: Iterable) -> str:
    texts = [message_text(item) for item in messages if getattr(item, "role", "user") == "user"]
    if texts:
        return texts[-1]
    all_texts = [message_text(item) for item in messages]
    return "\n".join(text for text in all_texts if text)


def resolve_deployment(db: Session, model_name: str) -> Deployment:
    """按部署名或别名解析模型；未找到返回 OpenAI 风格 404。"""
    deployment = deployment_crud.get_by_name(db, model_name)
    if deployment is None:
        deployment = deployment_crud.get_by_alias(db, model_name)
    if deployment is None:
        raise OpenAIError(
            f"The model '{model_name}' does not exist",
            status_code=404,
            code="model_not_found",
            param="model",
        )
    if deployment.status != "running":
        raise OpenAIError(
            f"The model '{model_name}' is not ready (status={deployment.status})",
            status_code=503,
            error_type="service_unavailable",
            code="model_not_ready",
        )
    return deployment


def _record(
    db: Session,
    *,
    deployment: Deployment | None,
    key: ApiKey | None,
    endpoint: str,
    model_name: str,
    trace_id: str,
    prompt_text: str,
    response_text: str,
    prompt_tokens: int,
    completion_tokens: int,
    status_code: int,
    latency_ms: float,
    error: str = "",
) -> None:
    key_crud.record_usage(
        db,
        key=key,
        deployment_id=deployment.id if deployment else None,
        endpoint=endpoint,
        model_name=model_name,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        status_code=status_code,
        latency_ms=latency_ms,
    )
    key_crud.write_inference_log(
        db,
        trace_id=trace_id,
        key=key,
        deployment_id=deployment.id if deployment else None,
        endpoint=endpoint,
        model_name=model_name,
        status_code=status_code,
        latency_ms=latency_ms,
        prompt_preview=prompt_text,
        response_preview=response_text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        error=error,
    )
    if deployment is not None:
        deployment.request_count += 1
        deployment.total_latency_ms += latency_ms
        if status_code >= 400:
            deployment.error_count += 1
        db.commit()


# --------------------------------------------------------------------------- 回答构造
def _classification_answer(prompt: str, result: dict, json_mode: bool) -> str:
    if json_mode:
        return json.dumps(
            {
                "label": result["label"],
                "confidence": round(result["confidence"], 4),
                "scores": result["scores"],
            },
            ensure_ascii=False,
        )
    lines = [f"判定结果：{result['label']}（置信度 {result['confidence'] * 100:.1f}%）", "", "候选标签："]
    for item in result["scores"][:5]:
        lines.append(f"- {item['label']}：{item['score'] * 100:.1f}%")
    lines.append("")
    lines.append(f"输入摘要：{prompt[:80]}")
    return "\n".join(lines)


def _rag_answer(prompt: str, hits: list[dict]) -> str:
    if not hits:
        return "知识库中没有检索到相关片段，请补充文档后重试。"
    lines = [f"根据知识库检索到 {len(hits)} 个相关片段：", ""]
    for index, hit in enumerate(hits, start=1):
        lines.append(f"【{index}】{hit['title']}（相似度 {hit['score']:.3f}）")
        lines.append(hit["content"])
        lines.append("")
    lines.append("以上内容来自平台知识库检索结果，未经过生成式改写。")
    return "\n".join(lines)


# --------------------------------------------------------------------------- 主流程
def chat_completion(
    db: Session,
    deployment: Deployment,
    payload,  # noqa: ANN001 - ChatCompletionRequest
    key: ApiKey | None,
    trace_id: str,
) -> dict:
    """执行一次 chat completion 并返回 OpenAI 兼容响应体。"""
    endpoint = "/v1/chat/completions"
    prompt_text = last_user_text(payload.messages)
    prompt_tokens = sum(estimate_tokens(message_text(item)) for item in payload.messages)
    started = time.perf_counter()
    runtime: ModelRuntime | None = None
    citations: list[dict] = []
    try:
        if not prompt_text.strip():
            raise OpenAIError("messages 中必须包含非空的 user 内容", code="empty_prompt", param="messages")
        runtime = runtime_manager.get(deployment, db)
        json_mode = bool(payload.response_format and payload.response_format.get("type") == "json_object")
        if runtime.task_type == "text_classification":
            result = runtime.classify(prompt_text)
            content = _classification_answer(prompt_text, result, json_mode)
        else:
            top_k_raw = (payload.model_extra or {}).get("top_k", 3)
            try:
                top_k = int(top_k_raw)
            except (TypeError, ValueError):
                top_k = 3
            hits = runtime.search(prompt_text, top_k=top_k)
            citations = [
                {"title": hit["title"], "source": hit["source"], "score": hit["score"], "chunk_index": hit["chunk_index"]}
                for hit in hits
            ]
            content = _rag_answer(prompt_text, hits)
    except OpenAIError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        _record(
            db,
            deployment=deployment,
            key=key,
            endpoint=endpoint,
            model_name=deployment.name,
            trace_id=trace_id,
            prompt_text=prompt_text,
            response_text="",
            prompt_tokens=prompt_tokens,
            completion_tokens=0,
            status_code=exc.status_code,
            latency_ms=latency_ms,
            error=exc.message,
        )
        raise

    latency_ms = (time.perf_counter() - started) * 1000
    completion_tokens = estimate_tokens(content)
    response = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": deployment.name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
                "logprobs": None,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "system_fingerprint": f"fp-modelops-v{runtime.version_id if runtime else 0}",
        "modelops": {
            "trace_id": trace_id,
            "deployment_id": deployment.id,
            "deployment_name": deployment.name,
            "model_version_id": deployment.model_version_id,
            "task_type": runtime.task_type if runtime else "",
            "latency_ms": round(latency_ms, 2),
            "citations": citations,
        },
    }
    _record(
        db,
        deployment=deployment,
        key=key,
        endpoint=endpoint,
        model_name=deployment.name,
        trace_id=trace_id,
        prompt_text=prompt_text,
        response_text=content,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        status_code=200,
        latency_ms=latency_ms,
    )
    return response


def stream_completion(
    db: Session,
    deployment: Deployment,
    payload,  # noqa: ANN001
    key: ApiKey | None,
    trace_id: str,
) -> Iterable[str]:
    """SSE 流式返回：模型本身是判别式/检索式，因此先算完整结果再按片段推送。"""
    response = chat_completion(db, deployment, payload, key, trace_id)
    content: str = response["choices"][0]["message"]["content"]
    chunk_id = response["id"]
    created = response["created"]
    model = response["model"]
    usage = response["usage"]

    def event(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    def generate() -> Iterable[str]:
        yield event(
            {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
            }
        )
        step = 24
        for offset in range(0, len(content), step):
            yield event(
                {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {"index": 0, "delta": {"content": content[offset : offset + step]}, "finish_reason": None}
                    ],
                }
            )
        yield event(
            {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": usage,
            }
        )
        yield "data: [DONE]\n\n"

    return generate()


def embeddings(
    db: Session,
    deployment: Deployment,
    payload,  # noqa: ANN001 - EmbeddingRequest
    key: ApiKey | None,
    trace_id: str,
) -> dict:
    endpoint = "/v1/embeddings"
    texts = [payload.input] if isinstance(payload.input, str) else list(payload.input)
    if not texts:
        raise OpenAIError("input 不能为空", code="empty_input", param="input")
    prompt_tokens = sum(estimate_tokens(text) for text in texts)
    started = time.perf_counter()
    try:
        runtime = runtime_manager.get(deployment, db)
        vectors = runtime.embed([str(text) for text in texts])
        if payload.dimensions and payload.dimensions > vectors.shape[1]:
            raise OpenAIError(
                f"dimensions 不能超过模型维度 {vectors.shape[1]}",
                code="invalid_dimensions",
                param="dimensions",
            )
        if payload.dimensions and payload.dimensions < vectors.shape[1]:
            vectors = vectors[:, : payload.dimensions]
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            vectors = vectors / norms
    except OpenAIError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        _record(
            db,
            deployment=deployment,
            key=key,
            endpoint=endpoint,
            model_name=deployment.name,
            trace_id=trace_id,
            prompt_text=" | ".join(texts)[:500],
            response_text="",
            prompt_tokens=prompt_tokens,
            completion_tokens=0,
            status_code=exc.status_code,
            latency_ms=latency_ms,
            error=exc.message,
        )
        raise

    latency_ms = (time.perf_counter() - started) * 1000
    if payload.encoding_format == "base64":
        data = [
            {
                "object": "embedding",
                "index": index,
                "embedding": base64.b64encode(vector.astype(np.float32).tobytes()).decode("ascii"),
            }
            for index, vector in enumerate(vectors)
        ]
    else:
        data = [
            {
                "object": "embedding",
                "index": index,
                "embedding": [round(float(value), 6) for value in vector],
            }
            for index, vector in enumerate(vectors)
        ]
    response = {
        "object": "list",
        "data": data,
        "model": deployment.name,
        "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
        "modelops": {
            "trace_id": trace_id,
            "deployment_id": deployment.id,
            "dimensions": int(vectors.shape[1]),
            "latency_ms": round(latency_ms, 2),
        },
    }
    _record(
        db,
        deployment=deployment,
        key=key,
        endpoint=endpoint,
        model_name=deployment.name,
        trace_id=trace_id,
        prompt_text=" | ".join(texts)[:500],
        response_text=json.dumps({"count": len(texts), "dim": int(vectors.shape[1])}, ensure_ascii=False),
        prompt_tokens=prompt_tokens,
        completion_tokens=0,
        status_code=200,
        latency_ms=latency_ms,
    )
    return response


def list_models(db: Session) -> dict:
    deployments = deployment_crud.list_running(db)
    data = [
        {
            "id": item.name,
            "object": "model",
            "created": int(item.created_at.timestamp()) if item.created_at else 0,
            "owned_by": "ai-modelops-platform",
            "permission": [],
            "root": item.name,
            "parent": None,
            "modelops": {
                "deployment_id": item.id,
                "task_type": item.model_version.registry.task_type if item.model_version and item.model_version.registry else "",
                "alias": item.alias,
            },
        }
        for item in deployments
    ]
    return {"object": "list", "data": data}


def usage_tokens_estimate(text: str) -> int:
    """兼容旧调用点的别名。"""
    return estimate_tokens(text)
