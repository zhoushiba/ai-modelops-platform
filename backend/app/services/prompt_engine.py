"""Prompt 模板引擎：变量渲染、A/B 实验执行、人工打分。

生成侧有两种引擎，按配置自动选择：
1. ``upstream``：配置了 ``UPSTREAM_LLM_BASE_URL`` 时，走真实的大模型服务（OpenAI 协议）；
2. ``local-extractive-v1``：默认的本地抽取式引擎——从渲染后的上下文里按问题相关性抽取句子，
   无需任何外部依赖即可演示 A/B 流程（不伪造大模型输出，返回内容明确标注引擎）。
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import AppError, NotFoundError
from app.models import PromptExperiment, PromptTemplate, utcnow

logger = logging.getLogger(__name__)

VARIABLE_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
CONTEXT_MARKERS = ("上下文：", "上下文:", "资料：", "资料:", "知识库：", "知识库:", "背景：", "背景:", "文档：")
QUESTION_MARKERS = ("问题：", "问题:", "用户输入：", "用户输入:", "Q：", "Q:", "提问：")
SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")

LOCAL_ENGINE = "local-extractive-v1"


def extract_variables(content: str) -> list[str]:
    """按出现顺序去重提取 ``{{variable}}`` 变量名。"""
    seen: list[str] = []
    for name in VARIABLE_PATTERN.findall(content or ""):
        if name not in seen:
            seen.append(name)
    return seen


def render(content: str, variables: dict[str, str]) -> tuple[str, list[str]]:
    """渲染模板；返回 (渲染结果, 缺失变量列表)。缺失变量以空串替换并在结果中标注。"""
    missing: list[str] = []

    def _replace(match: re.Match) -> str:
        name = match.group(1)
        if name in variables and variables[name] is not None:
            return str(variables[name])
        missing.append(name)
        return f"[缺少变量:{name}]"

    rendered = VARIABLE_PATTERN.sub(_replace, content or "")
    return rendered, sorted(set(missing))


def _split_sections(prompt: str) -> tuple[str, str]:
    """从提示词里拆出 (上下文, 问题)；拆不出来时退化为 (整体, 最后一行)。"""
    context_lines: list[str] = []
    question = ""
    in_context = False
    for line in prompt.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(marker) for marker in QUESTION_MARKERS):
            for marker in QUESTION_MARKERS:
                if stripped.startswith(marker):
                    question = stripped[len(marker) :].strip()
                    break
            in_context = False
            continue
        if any(stripped.startswith(marker) for marker in CONTEXT_MARKERS):
            in_context = True
            for marker in CONTEXT_MARKERS:
                if stripped.startswith(marker):
                    remainder = stripped[len(marker) :].strip()
                    if remainder:
                        context_lines.append(remainder)
                    break
            continue
        if in_context:
            context_lines.append(stripped)
    if not context_lines:
        context_lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    if not question:
        question = context_lines[-1] if context_lines else prompt[-80:]
    return "\n".join(context_lines), question


def _bigrams(text: str) -> Counter:
    cleaned = re.sub(r"\s+", "", text)
    return Counter(cleaned[index : index + 2] for index in range(max(0, len(cleaned) - 1)))


def local_extractive_answer(prompt: str) -> str:
    """抽取式回答：选与问题字符二元组重合度最高的句子，明确标注引擎。"""
    context, question = _split_sections(prompt)
    question_grams = _bigrams(question)
    sentences = [part.strip() for part in SENTENCE_SPLIT.split(context) if len(part.strip()) >= 8]
    if not sentences:
        return f"[{LOCAL_ENGINE}] 没有可抽取的上下文，原始输入：{prompt[:120]}"
    scored = []
    for index, sentence in enumerate(sentences):
        grams = _bigrams(sentence)
        overlap = sum((grams & question_grams).values())
        scored.append((overlap, index, sentence))
    scored.sort(key=lambda item: (-item[0], item[1]))
    picked = sorted(scored[:2], key=lambda item: item[1])
    body = "\n".join(f"- {sentence}" for _, _, sentence in picked)
    return (
        f"[{LOCAL_ENGINE}] 针对问题「{question[:60]}」，从上下文中抽取到以下依据：\n"
        f"{body}\n"
        f"（本地抽取式引擎不生成新文本，仅做相关性抽取；配置 UPSTREAM_LLM_* 可切换为真实大模型。）"
    )


def call_upstream(prompt: str, *, temperature: float = 0.2) -> tuple[str, str]:
    """调用上游 OpenAI 兼容服务，返回 (文本, 引擎名)。"""
    base = settings.upstream_llm_base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if settings.upstream_llm_api_key:
        headers["Authorization"] = f"Bearer {settings.upstream_llm_api_key}"
    payload = {
        "model": settings.upstream_llm_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    with httpx.Client(timeout=settings.upstream_timeout_seconds) as client:
        response = client.post(f"{base}/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    content = data["choices"][0]["message"]["content"]
    return str(content), f"upstream:{data.get('model', settings.upstream_llm_model)}"


def generate(prompt: str, *, temperature: float = 0.2) -> tuple[str, str, float]:
    """生成回答，返回 (文本, 引擎, 耗时毫秒)。"""
    started = time.perf_counter()
    if settings.upstream_llm_base_url:
        try:
            text, engine = call_upstream(prompt, temperature=temperature)
        except Exception as exc:  # noqa: BLE001 - 上游失败回退到本地引擎，保证演示可用
            logger.warning("上游模型调用失败，回退本地引擎：%s", exc)
            text, engine = local_extractive_answer(prompt), f"{LOCAL_ENGINE}(fallback)"
    else:
        text, engine = local_extractive_answer(prompt), LOCAL_ENGINE
    return text, engine, round((time.perf_counter() - started) * 1000, 2)


def run_experiment(
    db: Session,
    *,
    name: str,
    template_a: PromptTemplate,
    template_b: PromptTemplate,
    input_text: str,
    variables: dict[str, str],
    created_by: str,
) -> PromptExperiment:
    """执行一次 A/B 实验：两个模板分别渲染、生成、记录耗时。"""
    merged = dict(variables or {})
    if input_text and "input" not in merged:
        merged["input"] = input_text
    prompt_a, missing_a = render(template_a.content, merged)
    prompt_b, missing_b = render(template_b.content, merged)
    if missing_a or missing_b:
        raise AppError(
            f"变量缺失：A={missing_a or '无'} B={missing_b or '无'}，请补齐后再运行", code=40020
        )
    output_a, engine_a, latency_a = generate(prompt_a)
    output_b, engine_b, latency_b = generate(prompt_b)
    experiment = PromptExperiment(
        name=name or f"{template_a.name} vs {template_b.name}",
        template_a_id=template_a.id,
        template_b_id=template_b.id,
        input_text=input_text,
        variables_json=merged,
        output_a=output_a,
        output_b=output_b,
        latency_a_ms=latency_a,
        latency_b_ms=latency_b,
        engine=engine_a if engine_a == engine_b else f"{engine_a} | {engine_b}",
        status="completed",
        created_by=created_by,
        created_at=utcnow(),
    )
    db.add(experiment)
    db.commit()
    db.refresh(experiment)
    logger.info("Prompt A/B 实验已执行 id=%s", experiment.id)
    return experiment


def score_experiment(
    db: Session, experiment: PromptExperiment, score_a: int | None, score_b: int | None, notes: str = ""
) -> PromptExperiment:
    for label, score in (("A", score_a), ("B", score_b)):
        if score is not None and not 1 <= score <= 5:
            raise AppError(f"{label} 评分必须在 1-5 之间", code=40021)
    if score_a is not None:
        experiment.score_a = score_a
    if score_b is not None:
        experiment.score_b = score_b
    if notes:
        experiment.notes = notes
    db.commit()
    db.refresh(experiment)
    return experiment


def get_template_or_404(db: Session, template_id: int) -> PromptTemplate:
    template = db.get(PromptTemplate, template_id)
    if template is None:
        raise NotFoundError("Prompt 模板不存在")
    return template
