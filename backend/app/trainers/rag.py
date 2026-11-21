"""RAG 索引构建训练器：文档切片 + 特征哈希向量（字符 n-gram）+ 向量表落库。

不依赖任何模型下载：``HashingVectorizer`` 是**无状态**的确定性特征哈希，
把中文文本映射到固定维度的 L2 归一化向量，余弦相似度即点积。
"""

from __future__ import annotations

import re
from collections import Counter

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

from app.models import RagChunk
from app.trainers.base import BaseTrainer, TrainResult, TrainingContext, TrainingError

SENTENCE_END = "。！？；!?;\n."


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """按字符窗口切片，尽量在句末标点处断开，并保留 ``overlap`` 字符重叠。"""
    text = normalize_text(text)
    if not text:
        return []
    chunks: list[str] = []
    start, total = 0, len(text)
    while start < total:
        end = min(total, start + chunk_size)
        if end < total:
            window = text[start:end]
            cut = max(window.rfind(char) for char in SENTENCE_END)
            if cut > chunk_size * 0.5:
                end = start + cut + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= total:
            break
        start = max(end - overlap, start + 1)
    return chunks


class RagIndexTrainer(BaseTrainer):
    task_type = "rag_corpus"
    display_name = "RAG 索引构建"
    description = "文档切片 + 字符 n-gram 哈希向量 + 向量表，供 /v1/embeddings 与检索问答使用"
    base_models = ("hashing-tfidf",)

    def validate(self, rows: list, hyperparams: dict) -> None:
        docs = [row for row in rows if row.text.strip()]
        if len(docs) < 1:
            raise TrainingError("语料为空，至少需要 1 篇文档")
        total_chars = sum(len(row.text) for row in docs)
        if total_chars < 50:
            raise TrainingError("语料总长度不足 50 字符，无法构建有意义的索引")

    def train(self, rows: list, hyperparams: dict, ctx: TrainingContext) -> TrainResult:
        chunk_size = int(hyperparams["chunk_size"])
        overlap = min(int(hyperparams["chunk_overlap"]), chunk_size // 2)
        dim = int(hyperparams["embedding_dim"])

        docs = [row for row in rows if normalize_text(row.text)]
        ctx.log(f"语料载入：{len(docs)} 篇文档，chunk_size={chunk_size} overlap={overlap} dim={dim}")
        ctx.progress(15, "文档切片")

        chunks: list[dict] = []
        for doc_index, row in enumerate(docs):
            # RAG 语料的 label 字段存文档标题，meta.source 存来源
            title = (row.label or f"文档-{doc_index + 1}")[:250]
            source = str((row.meta or {}).get("source", "samples"))[:250]
            for piece in chunk_text(row.text, chunk_size, overlap):
                chunks.append(
                    {"title": title, "source": source, "content": piece, "doc_index": doc_index}
                )
            if doc_index % 20 == 0:
                ctx.check_cancel()
                ctx.progress(15 + int(20 * (doc_index + 1) / max(len(docs), 1)), "文档切片")
        if not chunks:
            raise TrainingError("切片结果为空，请检查文档内容")

        ctx.log(f"切片完成：{len(chunks)} 个 chunk，平均 {sum(len(c['content']) for c in chunks) / len(chunks):.1f} 字符")
        ctx.check_cancel()
        ctx.progress(40, "向量化")

        vectorizer = HashingVectorizer(
            n_features=dim,
            analyzer="char",
            ngram_range=(2, 3),
            alternate_sign=False,
            norm="l2",
            dtype=np.float32,
        )
        matrix = vectorizer.transform([chunk["content"] for chunk in chunks])
        ctx.log(f"向量矩阵：shape={matrix.shape} nnz={matrix.nnz}")

        # 检索自检：用 chunk 自身当 query，看能否召回自己（衡量索引一致性）
        ctx.progress(65, "检索自检")
        sample_size = min(25, len(chunks))
        sample_ids = np.linspace(0, len(chunks) - 1, sample_size).astype(int)
        similarity = matrix[sample_ids] @ matrix.T
        top1 = np.asarray(similarity.argmax(axis=1)).ravel()
        self_hit_rate = float(np.mean(top1 == sample_ids))

        vectors = matrix.toarray().astype(np.float32)
        for index, chunk in enumerate(chunks):
            chunk["vector"] = vectors[index].tobytes()

        char_counts = [len(chunk["content"]) for chunk in chunks]
        metrics = {
            "doc_count": len(docs),
            "chunk_count": len(chunks),
            "embedding_dim": dim,
            "index_nnz": int(matrix.nnz),
            "avg_chunk_chars": round(float(np.mean(char_counts)), 2),
            "min_chunk_chars": int(np.min(char_counts)),
            "max_chunk_chars": int(np.max(char_counts)),
            "self_hit_rate": round(self_hit_rate, 4),
            "duplicate_chunk_ratio": round(
                1 - len({chunk["content"] for chunk in chunks}) / len(chunks), 4
            ),
        }
        ctx.log(
            f"索引完成：chunks={metrics['chunk_count']} self_hit_rate={metrics['self_hit_rate']:.2%} "
            f"重复切片率={metrics['duplicate_chunk_ratio']:.2%}"
        )
        ctx.progress(90, "写入向量表")

        bundle = {
            "task_type": self.task_type,
            "framework": "scikit-learn",
            "vectorizer": vectorizer,
            "dim": dim,
            "chunk_count": len(chunks),
            "doc_count": len(docs),
            "hyperparams": dict(hyperparams),
            "metrics": metrics,
        }
        return TrainResult(
            bundle=bundle,
            metrics=metrics,
            extra={"chunks": chunks},
            artifact_filename="index.joblib",
        )

    def persist(self, db, job, result: TrainResult) -> None:  # noqa: ANN001
        """把切片与向量写入 ``rag_chunk`` 向量表（可被部署直接检索）。"""
        chunks = result.extra.get("chunks", [])
        if not chunks:
            return
        db.query(RagChunk).filter(RagChunk.training_job_id == job.id).delete()
        db.add_all(
            [
                RagChunk(
                    training_job_id=job.id,
                    chunk_index=index,
                    doc_title=chunk["title"],
                    source=chunk["source"],
                    content=chunk["content"],
                    char_count=len(chunk["content"]),
                    dim=result.bundle.get("dim", 0),
                    vector=chunk["vector"],
                )
                for index, chunk in enumerate(chunks)
            ]
        )
        db.commit()
