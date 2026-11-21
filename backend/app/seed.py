"""初始化数据：管理员账号、样例数据集、Prompt 模板、演示 API Key。

幂等：已存在的数据不会重复创建，可安全地在每次启动时调用。
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.crud import datasets as dataset_crud
from app.crud import evals as eval_crud
from app.crud import keys as key_crud
from app.crud import prompts as prompt_crud
from app.models import ApiKey, Dataset, PromptTemplate, User, utcnow
from app.security import generate_api_key, hash_password
from app.services import dataset_service, eval_service

logger = logging.getLogger(__name__)

SAMPLES = settings.samples_path

SEED_PROMPTS = [
    {
        "name": "客服回复-简洁版",
        "description": "只给结论与一条建议，适合移动端快速回复",
        "tags": "客服,简洁",
        "content": (
            "你是企业客服助手，请基于下面资料回答用户问题，控制在 2 句话内。\n\n"
            "资料：\n{{context}}\n\n"
            "问题：{{question}}\n\n"
            "回答："
        ),
    },
    {
        "name": "客服回复-详细版",
        "description": "先复述问题，再给排查步骤与后续承诺，适合工单邮件",
        "tags": "客服,详细",
        "content": (
            "你是企业客服助手。请先复述用户问题，再依据资料给出分步解决方案，最后说明后续跟进方式。\n\n"
            "资料：\n{{context}}\n\n"
            "问题：{{question}}\n\n"
            "请用中文分点输出：\n1. 问题复述\n2. 解决步骤\n3. 后续跟进\n\n回答："
        ),
    },
]


def seed_admin(db: Session) -> User:
    """确保管理员账号存在（默认 admin / admin123，可在 .env 覆盖）。"""
    user = db.scalar(select(User).where(User.username == settings.admin_username))
    if user is not None:
        return user
    user = User(
        username=settings.admin_username,
        password_hash=hash_password(settings.admin_password),
        display_name="平台管理员",
        role="admin",
        created_at=utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("已创建管理员账号 %s", settings.admin_username)
    return user


def _read(name: str) -> bytes:
    path = SAMPLES / name
    if not path.exists():
        raise FileNotFoundError(f"样例文件缺失：{path}")
    return path.read_bytes()


def _merge_ticket_csv() -> bytes:
    """合并 train/val 两个样例文件为一份 CSV（保留 split 列）。"""
    parts: list[str] = []
    for filename in ("tickets_train.csv", "tickets_val.csv"):
        content = _read(filename).decode("utf-8-sig").strip().splitlines()
        parts.extend(content[1:] if parts else content)
    return ("\n".join(parts) + "\n").encode("utf-8")


def seed_datasets(db: Session, owner: User) -> dict[str, Dataset]:
    """导入样例数据集：工单分类（含 train/val）、RAG 知识库、评测集。"""
    created: dict[str, Dataset] = {}

    ticket_name = "客服工单分类（样例）"
    dataset = dataset_crud.get_dataset_by_name(db, ticket_name)
    if dataset is None:
        raw = _merge_ticket_csv()
        dataset, version = dataset_service.create_dataset(
            db,
            name=ticket_name,
            description="中文客服工单意图分类，覆盖退款、物流、账号、发票等 8 类意图，含 train/val 切分。",
            task_type="text_classification",
            owner_id=owner.id,
            filename="tickets.csv",
            raw=raw,
            text_field="text",
            label_field="label",
            split_field="split",
            val_ratio=0.2,
            created_by=owner.username,
        )
        logger.info("已导入样例数据集 %s v%s（%s 行）", dataset.name, version.version, version.row_count)
    created["tickets"] = dataset

    rag_name = "产品知识库（RAG 样例）"
    dataset = dataset_crud.get_dataset_by_name(db, rag_name)
    if dataset is None:
        raw = _read("knowledge_docs.jsonl")
        dataset, version = dataset_service.create_dataset(
            db,
            name=rag_name,
            description="产品帮助中心文档，用于演示 RAG 切片与向量检索（rag_corpus 任务）。",
            task_type="rag_corpus",
            owner_id=owner.id,
            filename="knowledge_docs.jsonl",
            raw=raw,
            text_field="text",
            label_field="",
            split_field="",
            val_ratio=0.0,
            created_by=owner.username,
        )
        logger.info("已导入 RAG 语料 %s v%s（%s 行）", dataset.name, version.version, version.row_count)
    created["knowledge"] = dataset

    eval_name = "工单意图评测集（样例）"
    if eval_crud.get_by_name(db, eval_name) is None:
        eval_service.create_eval_dataset(
            db,
            name=eval_name,
            description="与训练集同分布但完全独立的 120 条标注数据，用于离线评测。",
            task_type="text_classification",
            text_field="text",
            label_field="label",
            filename="eval_tickets.csv",
            raw=_read("eval_tickets.csv"),
        )
        logger.info("已导入评测集 %s", eval_name)
    return created


def seed_prompts(db: Session) -> list[PromptTemplate]:
    """导入两个可直接做 A/B 的 Prompt 模板。"""
    created: list[PromptTemplate] = []
    for item in SEED_PROMPTS:
        if prompt_crud.get_by_name(db, item["name"]) is not None:
            continue
        template = PromptTemplate(
            name=item["name"],
            description=item["description"],
            content=item["content"],
            tags=item["tags"],
            variables_json=["context", "question"],
            version=1,
        )
        db.add(template)
        created.append(template)
    if created:
        db.commit()
        logger.info("已创建 %s 个 Prompt 模板", len(created))
    return created


def seed_demo_key(db: Session, owner: User) -> str:
    """首次启动时创建一把演示 API Key，明文只在日志里出现一次。"""
    existing = key_crud.list_keys(db)
    if existing:
        return ""
    raw, prefix, key_hash = generate_api_key()
    key = ApiKey(
        name="demo-integration",
        prefix=prefix,
        key_hash=key_hash,
        scopes_json=["chat", "embeddings"],
        rate_limit_per_min=settings.rate_limit_per_min,
        burst=settings.rate_limit_burst,
        token_quota=settings.token_quota,
        active=True,
        owner_id=owner.id,
        created_at=utcnow(),
    )
    db.add(key)
    db.commit()
    logger.warning("已创建演示 API Key（仅本次显示）：%s", raw)
    return raw


def seed_all() -> dict:
    """编排全部初始化动作（在 lifespan 里调用一次），返回演示 Key（如有）。"""
    from app.database import session_scope

    with session_scope() as db:
        user = seed_admin(db)
        if settings.seed_samples:
            seed_datasets(db, user)
            seed_prompts(db)
        raw_key = seed_demo_key(db, user)
    return {"demo_api_key": raw_key}


__all__ = [
    "SEED_PROMPTS",
    "seed_admin",
    "seed_datasets",
    "seed_prompts",
    "seed_demo_key",
    "seed_all",
]
