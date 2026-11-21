"""文本分类训练器：TF-IDF(char n-gram) + LogisticRegression(L-BFGS, warm_start)。

真实训练，CPU 上 200~2000 条样本通常 1~3 秒。
每个 epoch 执行一次 L-BFGS 迭代（warm_start 续训），因此能记录**真实**的
loss / accuracy 曲线，而不是伪造的下降序列。
"""

from __future__ import annotations

import warnings
from collections import Counter

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
)

from app.trainers.base import BaseTrainer, TrainResult, TrainingContext, TrainingError

warnings.filterwarnings("ignore", category=ConvergenceWarning)


def _split_dataset(rows: list) -> tuple[list, list]:
    """优先使用数据集自带的 train/val 切分；没有 val 时按 80/20 兜底切分。"""
    train = [row for row in rows if row.split == "train"]
    val = [row for row in rows if row.split == "val"]
    if not train:
        train = list(rows)
    if not val and len(train) >= 20:
        cut = int(len(train) * 0.8)
        val = train[cut:]
        train = train[:cut]
    return train, val


class TextClassificationTrainer(BaseTrainer):
    task_type = "text_classification"
    display_name = "文本分类微调"
    description = "TF-IDF 字符 n-gram 特征 + 逻辑回归，产出 joblib 模型与准确率/F1 指标"
    base_models = ("tfidf-logreg",)

    def validate(self, rows: list, hyperparams: dict) -> None:
        labels = {row.label for row in rows if row.label}
        if len(rows) < 10:
            raise TrainingError(f"样本量不足（{len(rows)} 条），至少需要 10 条")
        if len(labels) < 2:
            raise TrainingError("标签种类少于 2 个，无法训练分类模型")
        empty = sum(1 for row in rows if not row.text.strip())
        if empty == len(rows):
            raise TrainingError("所有样本文本为空")

    def train(self, rows: list, hyperparams: dict, ctx: TrainingContext) -> TrainResult:
        train_rows, val_rows = _split_dataset(rows)
        if not val_rows:
            # 样本太少时用训练集自身评估，并在日志中明确说明
            ctx.log("警告：没有验证集，使用训练集评估（指标偏乐观）", level="WARN")
            val_rows = train_rows

        train_texts = [row.text[: hyperparams["max_len"]] for row in train_rows]
        train_labels = [row.label for row in train_rows]
        val_texts = [row.text[: hyperparams["max_len"]] for row in val_rows]
        val_labels = [row.label for row in val_rows]

        ctx.log(
            f"数据就绪：train={len(train_texts)} val={len(val_texts)} "
            f"labels={len(set(train_labels))} 分布={dict(Counter(train_labels).most_common(8))}"
        )
        ctx.progress(10, "特征工程")

        vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(1, int(hyperparams["ngram_max"])),
            max_features=int(hyperparams["max_features"]),
            min_df=1,
            sublinear_tf=True,
            dtype=np.float32,
        )
        x_train = vectorizer.fit_transform(train_texts)
        x_val = vectorizer.transform(val_texts)
        ctx.log(f"TF-IDF 特征维度：{x_train.shape[1]}（train 矩阵 nnz={x_train.nnz}）")
        ctx.progress(25, "开始训练")

        classifier = LogisticRegression(
            C=float(hyperparams["lr"]),
            max_iter=1,
            warm_start=True,
            solver="lbfgs",
            n_jobs=None,
            random_state=42,
        )

        # 训练损失用训练集的一个子样本估计，避免每轮全量 predict_proba 拖慢进度
        rng = np.random.default_rng(42)
        sample_size = min(len(train_texts), 1500)
        sample_idx = rng.choice(len(train_texts), size=sample_size, replace=False)
        x_sample = x_train[sample_idx]
        y_sample = np.array(train_labels, dtype=object)[sample_idx]

        epochs = int(hyperparams["epochs"])
        for epoch in range(1, epochs + 1):
            ctx.check_cancel()
            classifier.fit(x_train, train_labels)
            proba_sample = classifier.predict_proba(x_sample)
            train_loss = float(log_loss(y_sample, proba_sample, labels=classifier.classes_))
            train_acc = float(accuracy_score(y_sample, classifier.predict(x_sample)))
            val_proba = classifier.predict_proba(x_val)
            val_pred = classifier.predict(x_val)
            val_loss = float(log_loss(val_labels, val_proba, labels=classifier.classes_))
            val_acc = float(accuracy_score(val_labels, val_pred))
            val_f1 = float(f1_score(val_labels, val_pred, average="macro", zero_division=0))

            ctx.metric(epoch, "train_loss", round(train_loss, 5))
            ctx.metric(epoch, "train_acc", round(train_acc, 5))
            ctx.metric(epoch, "val_loss", round(val_loss, 5))
            ctx.metric(epoch, "val_acc", round(val_acc, 5))
            ctx.metric(epoch, "val_f1", round(val_f1, 5))
            ctx.log(
                f"epoch {epoch}/{epochs} loss={train_loss:.4f} acc={train_acc:.4f} "
                f"val_loss={val_loss:.4f} val_acc={val_acc:.4f} val_f1={val_f1:.4f}"
            )
            ctx.progress(25 + int(65 * epoch / epochs), f"训练中 epoch {epoch}/{epochs}")

        # 收敛收尾：以更高迭代上限再拟合一次，保证交付的模型真正收敛
        ctx.check_cancel()
        classifier.max_iter = 300
        classifier.fit(x_train, train_labels)
        ctx.log(f"最终拟合完成：n_iter_={int(np.max(classifier.n_iter_))}（上限 300）")

        final_pred = classifier.predict(x_val)
        labels = list(classifier.classes_)
        accuracy = float(accuracy_score(val_labels, final_pred))
        macro_f1 = float(f1_score(val_labels, final_pred, average="macro", zero_division=0))
        macro_precision = float(precision_score(val_labels, final_pred, average="macro", zero_division=0))
        macro_recall = float(recall_score(val_labels, final_pred, average="macro", zero_division=0))
        matrix = confusion_matrix(val_labels, final_pred, labels=labels).tolist()

        metrics = {
            "accuracy": round(accuracy, 4),
            "f1_macro": round(macro_f1, 4),
            "precision_macro": round(macro_precision, 4),
            "recall_macro": round(macro_recall, 4),
            "train_size": len(train_texts),
            "val_size": len(val_texts),
            "label_count": len(labels),
            "feature_dim": int(x_train.shape[1]),
            "labels": labels,
            "confusion_matrix": matrix,
            "duration_note": f"epochs={epochs}",
        }
        ctx.log(
            f"评估结果：accuracy={accuracy:.4f} macro_f1={macro_f1:.4f} "
            f"precision={macro_precision:.4f} recall={macro_recall:.4f}"
        )
        ctx.progress(95, "保存模型产物")

        bundle = {
            "task_type": self.task_type,
            "framework": "scikit-learn",
            "vectorizer": vectorizer,
            "classifier": classifier,
            "labels": labels,
            "hyperparams": dict(hyperparams),
            "metrics": metrics,
        }
        return TrainResult(bundle=bundle, metrics=metrics, artifact_filename="model.joblib")
