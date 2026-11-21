"""推理运行时：把训练产物加载成可服务的模型实例，并在进程内缓存。

- 文本分类：TF-IDF 向量化 + 逻辑回归，输出标签与置信度；用稀疏随机投影把
  TF-IDF 特征压到 ``embedding_dim`` 维，用于 ``/v1/embeddings``；
- RAG 语料：哈希向量化 + 向量表余弦检索，返回带出处的片段；
- 一个部署实例对应一个 ``ModelRuntime``，``start`` 时加载，``stop`` 时释放。
"""

from __future__ import annotations

import logging
import threading
import time

import joblib
import numpy as np
from scipy.sparse import csr_matrix
from sklearn.random_projection import GaussianRandomProjection
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Deployment, ModelVersion, RagChunk

logger = logging.getLogger(__name__)


class RuntimeLoadError(Exception):
    """模型产物无法加载（文件缺失、格式损坏、索引为空等）。"""


class ModelRuntime:
    """单个模型版本的推理封装（纯 CPU、无外部服务依赖）。"""

    def __init__(self, version: ModelVersion) -> None:
        self.version_id = version.id
        self.version_no = version.version
        # 血缘上的训练任务 id：RAG 索引按任务归属从向量表还原切片
        self.training_job_id = version.training_job_id
        registry = version.registry
        self.model_name = registry.name if registry else ""
        self.task_type = registry.task_type if registry else ""
        self.metrics = dict(version.metrics_json or {})
        self.hyperparams = dict(version.hyperparams_json or {})
        self.artifact_path = version.artifact_path
        self.vectorizer = None
        self.classifier = None
        self.projection = None
        self.embedding_dim = 0
        self.labels: list[str] = []
        self.chunks: list[dict] = []
        self.chunk_matrix: np.ndarray | None = None
        self.loaded_at = time.time()

    # ------------------------------------------------------------------ 装载
    def load(self, db: Session) -> "ModelRuntime":
        if not self.artifact_path:
            raise RuntimeLoadError("该版本没有模型产物")
        path = settings.absolute_path(self.artifact_path)
        if not path.exists():
            raise RuntimeLoadError(f"模型产物不存在：{self.artifact_path}")
        try:
            bundle = joblib.load(path)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeLoadError(f"模型产物损坏：{exc}") from exc

        if self.task_type == "text_classification":
            self._load_classifier(bundle)
        elif self.task_type == "rag_corpus":
            self._load_index(db, bundle)
        else:
            raise RuntimeLoadError(f"不支持的任务类型：{self.task_type}")
        self.loaded_at = time.time()
        logger.info(
            "模型已加载 version=%s task=%s dim=%s", self.version_id, self.task_type, self.embedding_dim
        )
        return self

    def _load_classifier(self, bundle: dict) -> None:
        self.vectorizer = bundle.get("vectorizer")
        self.classifier = bundle.get("classifier")
        if self.vectorizer is None or self.classifier is None:
            raise RuntimeLoadError("模型包缺少 vectorizer/classifier")
        self.labels = [str(item) for item in (bundle.get("labels") or list(self.classifier.classes_))]
        dim = int(self.hyperparams.get("embedding_dim") or 384)
        # 注意：TF-IDF 的真实输出维度是"拟合后的词表大小"，而不是 max_features
        # （max_features 只是词表上限）。若按 max_features 拟合投影矩阵，
        # 推理时会报 matmul: dimension mismatch，这里直接用词表维度。
        try:
            features = int(len(self.vectorizer.vocabulary_))
        except AttributeError:  # 兜底：没有 vocabulary_ 时用一次真实 transform 探测
            features = int(self.vectorizer.transform(["占位"]).shape[1])
        features = max(1, features)
        components = max(8, min(dim, features))
        self.projection = GaussianRandomProjection(
            n_components=components, random_state=42
        )
        self.projection.fit(csr_matrix((1, features), dtype=np.float32))
        self.embedding_dim = components

    def _load_index(self, db: Session, bundle: dict) -> None:
        self.vectorizer = bundle.get("vectorizer")
        if self.vectorizer is None:
            raise RuntimeLoadError("索引包缺少 vectorizer")
        # 向量表按"训练任务"归属：bundle 里带了 job_id 就直接用，
        # 否则回退到该模型版本血缘上的训练任务（部署时 bundle 可能已被裁剪）。
        training_job_id = bundle.get("job_id") or self.training_job_id
        rows = (
            db.query(RagChunk)
            .filter(RagChunk.training_job_id == training_job_id)
            .order_by(RagChunk.chunk_index)
            .all()
        )
        if not rows:
            raise RuntimeLoadError("向量表为空，索引不可用")
        vectors = []
        for row in rows:
            vector = np.frombuffer(row.vector or b"", dtype=np.float32)
            if vector.size == 0:
                continue
            vectors.append(vector)
            self.chunks.append(
                {
                    "chunk_index": row.chunk_index,
                    "title": row.doc_title,
                    "source": row.source,
                    "content": row.content,
                }
            )
        if not vectors:
            raise RuntimeLoadError("向量表数据损坏")
        self.chunk_matrix = np.vstack(vectors).astype(np.float32)
        self.embedding_dim = int(self.chunk_matrix.shape[1])

    # ------------------------------------------------------------------ 推理
    def classify(self, text: str) -> dict:
        if self.vectorizer is None or self.classifier is None:
            raise RuntimeLoadError("分类模型未加载")
        matrix = self.vectorizer.transform([text or ""])
        proba = self.classifier.predict_proba(matrix)[0]
        classes = [str(item) for item in self.classifier.classes_]
        order = np.argsort(-proba)
        scores = [
            {"label": classes[int(index)], "score": round(float(proba[int(index)]), 6)}
            for index in order
        ]
        return {
            "label": scores[0]["label"],
            "confidence": scores[0]["score"],
            "scores": scores[:5],
        }

    def embed(self, texts: list[str]) -> np.ndarray:
        """把文本编码成归一化向量；分类模型用随机投影把 TF-IDF 压到低维。"""
        if self.vectorizer is None:
            raise RuntimeLoadError("模型未加载")
        matrix = self.vectorizer.transform([text or "" for text in texts])
        if self.task_type == "rag_corpus":
            vectors = matrix.toarray().astype(np.float32)
        else:
            if self.projection is None:
                raise RuntimeLoadError("投影矩阵未初始化")
            # components_ 是稀疏矩阵，乘出来依然是稀疏矩阵，必须先转密集数组
            projected = matrix @ self.projection.components_.T
            vectors = (
                projected.toarray().astype(np.float32)
                if hasattr(projected, "toarray")
                else np.asarray(projected, dtype=np.float32)
            )
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        if self.chunk_matrix is None or not self.chunks:
            return []
        top_k = max(1, min(int(top_k), 20))
        vector = self.embed([query])[0]
        scores = self.chunk_matrix @ vector
        order = np.argsort(-scores)[:top_k]
        hits = []
        for index in order:
            chunk = self.chunks[int(index)]
            hits.append(
                {
                    "chunk_index": chunk["chunk_index"],
                    "title": chunk["title"],
                    "source": chunk["source"],
                    "content": chunk["content"],
                    "score": round(float(scores[int(index)]), 4),
                }
            )
        return hits

    def describe(self) -> dict:
        return {
            "version_id": self.version_id,
            "version": self.version_no,
            "model": self.model_name,
            "task_type": self.task_type,
            "embedding_dim": self.embedding_dim,
            "labels": self.labels,
            "chunks": len(self.chunks),
            "metrics": self.metrics,
        }


class RuntimeManager:
    """部署实例 → 运行时的进程内缓存。"""

    def __init__(self) -> None:
        self._runtimes: dict[int, ModelRuntime] = {}
        self._lock = threading.Lock()

    def get(self, deployment: Deployment, db: Session) -> ModelRuntime:
        with self._lock:
            runtime = self._runtimes.get(deployment.id)
        if runtime is not None:
            return runtime
        runtime = ModelRuntime(deployment.model_version).load(db)
        with self._lock:
            self._runtimes[deployment.id] = runtime
        return runtime

    def put(self, deployment_id: int, runtime: ModelRuntime) -> None:
        with self._lock:
            self._runtimes[deployment_id] = runtime

    def evict(self, deployment_id: int) -> None:
        with self._lock:
            self._runtimes.pop(deployment_id, None)

    def is_loaded(self, deployment_id: int) -> bool:
        with self._lock:
            return deployment_id in self._runtimes

    def loaded_ids(self) -> list[int]:
        with self._lock:
            return sorted(self._runtimes)

    def clear(self) -> None:
        with self._lock:
            self._runtimes.clear()

    def warmup(self, db: Session) -> dict[str, int]:
        """服务启动时恢复所有 running 的部署。"""
        stats = {"loaded": 0, "failed": 0}
        for deployment in db.query(Deployment).filter(Deployment.status == "running").all():
            try:
                self.put(deployment.id, ModelRuntime(deployment.model_version).load(db))
                stats["loaded"] += 1
            except Exception as exc:  # noqa: BLE001
                deployment.status = "failed"
                deployment.last_error = f"启动恢复失败：{exc}"
                db.commit()
                stats["failed"] += 1
                logger.warning("部署恢复失败 deployment=%s：%s", deployment.id, exc)
        if stats["loaded"] or stats["failed"]:
            logger.info("部署运行时恢复：%s", stats)
        return stats


runtime_manager = RuntimeManager()
