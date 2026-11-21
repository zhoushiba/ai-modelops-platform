"""数据集导入、校验、质量检查与版本 diff。

支持 CSV / JSONL / JSON 数组；编码自动识别 UTF-8(BOM) / GBK（中文工单常见）。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.errors import AppError
from app.models import Dataset, DatasetSample, DatasetVersion, utcnow

MAX_TEXT_LEN = 512
VALID_SPLITS = {"train": "train", "valid": "val", "val": "val", "validation": "val", "test": "test"}


@dataclass
class ParsedRow:
    text: str
    label: str
    split: str = "train"
    meta: dict[str, Any] = field(default_factory=dict)


def decode_bytes(raw: bytes) -> str:
    """按 UTF-8(BOM) -> GBK 顺序解码上传文件。"""
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise AppError("文件编码无法识别，请使用 UTF-8 或 GBK 编码", code=40001)


def _load_records(filename: str, raw: bytes) -> list[dict]:
    """把上传文件解析成原始记录列表。"""
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else "csv"
    text = decode_bytes(raw)
    records: list[dict] = []
    if suffix in ("jsonl", "ndjson"):
        for line_no, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AppError(f"第 {line_no} 行 JSON 解析失败：{exc.msg}", code=40001) from exc
            records.append(item if isinstance(item, dict) else {"text": str(item)})
    elif suffix == "json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AppError(f"JSON 解析失败：{exc.msg}", code=40001) from exc
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            payload = payload["data"]
        if not isinstance(payload, list):
            raise AppError("JSON 顶层必须是数组，或 {'data': [...]}", code=40001)
        records = [item if isinstance(item, dict) else {"text": str(item)} for item in payload]
    else:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise AppError("CSV 缺少表头行", code=40001)
        records = [dict(row) for row in reader]
    if not records:
        raise AppError("文件中没有可用数据行", code=40002)
    return records


def _pick(record: dict, field_name: str, default: str = "") -> str:
    if field_name and field_name in record and record[field_name] is not None:
        return str(record[field_name]).strip()
    return default


def parse_dataset(
    filename: str,
    raw: bytes,
    *,
    text_field: str = "text",
    label_field: str = "label",
    split_field: str = "",
    val_ratio: float = 0.2,
    task_type: str = "text_classification",
) -> list[ParsedRow]:
    """解析并规范化样本，同时完成按比例切分或读取显式 split 列。"""
    records = _load_records(filename, raw)
    sample_columns = list(records[0].keys())
    if text_field not in sample_columns:
        raise AppError(
            f"字段映射错误：文件里没有 '{text_field}' 列，可用列：{', '.join(sample_columns[:12])}",
            code=40003,
        )
    if task_type == "text_classification" and label_field not in sample_columns:
        raise AppError(
            f"字段映射错误：文件里没有 '{label_field}' 列，可用列：{', '.join(sample_columns[:12])}",
            code=40003,
        )

    rows: list[ParsedRow] = []
    for index, record in enumerate(records):
        text = _pick(record, text_field)
        if not text:
            continue
        label = _pick(record, label_field, "未标注") if task_type == "text_classification" else _pick(record, label_field, "文档")
        split = "train"
        if task_type != "rag_corpus":
            raw_split = _pick(record, split_field).lower() if split_field else ""
            if raw_split in VALID_SPLITS:
                split = VALID_SPLITS[raw_split]
            else:
                # 稳定哈希切分：同一文本在多次上传中落入同一 split，便于版本间公平对比
                bucket = int(hashlib.md5(text.encode("utf-8")).hexdigest()[:8], 16) % 100
                split = "val" if bucket < round(val_ratio * 100) else "train"
        meta = {key: value for key, value in record.items() if key not in (text_field, label_field, split_field)}
        rows.append(ParsedRow(text=text, label=label, split=split, meta=meta))
        _ = index
    if not rows:
        raise AppError("所有行的文本列都为空，无法导入", code=40002)
    return rows


def quality_report(rows: list[ParsedRow], max_text_len: int = MAX_TEXT_LEN) -> dict:
    """质量检查：空值、超长、重复率、标签分布、长度分布。"""
    total = len(rows)
    texts = [row.text for row in rows]
    counter = Counter(texts)
    duplicate_count = sum(count - 1 for count in counter.values() if count > 1)
    empty_count = sum(1 for row in rows if not row.text.strip() or not row.label.strip())
    too_long = sum(1 for row in rows if len(row.text) > max_text_len)

    lengths = sorted(len(text) for text in texts)
    def percentile(pct: float) -> int:
        if not lengths:
            return 0
        index = min(len(lengths) - 1, max(0, math.ceil(pct * len(lengths)) - 1))
        return lengths[index]

    label_distribution = Counter(row.label for row in rows).most_common(30)
    split_distribution = Counter(row.split for row in rows)

    issues: list[str] = []
    duplicate_ratio = round(duplicate_count / total, 4) if total else 0.0
    if empty_count:
        issues.append(f"存在 {empty_count} 条空文本或空标签样本")
    if duplicate_ratio > 0.05:
        issues.append(f"重复率偏高：{duplicate_ratio:.1%}")
    if too_long:
        issues.append(f"存在 {too_long} 条超过 {max_text_len} 字符的长文本（训练时会按 max_len 截断）")
    if len(label_distribution) < 2:
        issues.append("标签种类少于 2，无法训练分类模型")
    if label_distribution:
        top_ratio = label_distribution[0][1] / total
        if top_ratio > 0.8:
            issues.append(f"标签分布不均衡：'{label_distribution[0][0]}' 占比 {top_ratio:.0%}")
    if total < 50:
        issues.append(f"样本量偏少（{total} 条），指标波动会较大")

    return {
        "row_count": total,
        "label_count": len(label_distribution),
        "duplicate_count": duplicate_count,
        "duplicate_ratio": duplicate_ratio,
        "empty_count": empty_count,
        "too_long_count": too_long,
        "label_distribution": {label: count for label, count in label_distribution},
        "split_distribution": dict(split_distribution),
        "length_stats": {
            "min": lengths[0] if lengths else 0,
            "max": lengths[-1] if lengths else 0,
            "avg": round(sum(lengths) / total, 1) if total else 0.0,
            "p50": percentile(0.5),
            "p95": percentile(0.95),
        },
        "issues": issues,
    }


def diff_versions(old_samples: list[DatasetSample], new_rows: list[ParsedRow]) -> dict:
    """对比两个版本：新增 / 删除 / 标签变更 / 总量变化。"""
    old_pairs = {(sample.text, sample.label) for sample in old_samples}
    new_pairs = {(row.text, row.label) for row in new_rows}
    old_texts = {sample.text: sample.label for sample in old_samples}
    new_texts = {row.text: row.label for row in new_rows}
    added = len(new_pairs - old_pairs)
    removed = len(old_pairs - new_pairs)
    label_changed = sum(
        1 for text, label in new_texts.items() if text in old_texts and old_texts[text] != label
    )
    return {
        "previous_version_total": len(old_samples),
        "current_version_total": len(new_rows),
        "added": added,
        "removed": removed,
        "label_changed": label_changed,
        "changed_total": added + removed + label_changed,
        "added_examples": [pair[0][:80] for pair in list(new_pairs - old_pairs)[:5]],
        "removed_examples": [pair[0][:80] for pair in list(old_pairs - new_pairs)[:5]],
    }


def import_rows(
    db: Session,
    *,
    dataset: Dataset,
    rows: list[ParsedRow],
    filename: str,
    raw: bytes,
    created_by: str,
) -> DatasetVersion:
    """把解析后的样本落库为一个新版本（含文件落盘与 diff 统计）。"""
    previous = (
        db.query(DatasetVersion)
        .filter(DatasetVersion.dataset_id == dataset.id)
        .order_by(DatasetVersion.version.desc())
        .first()
    )
    version_no = (previous.version + 1) if previous else 1
    checksum = hashlib.sha256(raw).hexdigest()

    folder = settings.datasets_path / str(dataset.id) / f"v{version_no}"
    folder.mkdir(parents=True, exist_ok=True)
    safe_name = filename.replace("..", "_").replace("/", "_").replace("\\", "_") or "upload.csv"
    file_path = folder / safe_name
    file_path.write_bytes(raw)

    stats = quality_report(rows)
    previous_samples = (
        list(
            db.query(DatasetSample)
            .filter(DatasetSample.version_id == previous.id)
            .all()
        )
        if previous
        else []
    )
    diff = diff_versions(previous_samples, rows) if previous else {"initial": True, "current_version_total": len(rows)}

    version = DatasetVersion(
        dataset_id=dataset.id,
        version=version_no,
        file_path=settings.relative_path(file_path),
        row_count=len(rows),
        train_count=sum(1 for row in rows if row.split == "train"),
        val_count=sum(1 for row in rows if row.split == "val"),
        label_count=len(stats["label_distribution"]),
        checksum=checksum,
        stats_json=stats,
        diff_json=diff,
        created_by=created_by,
        created_at=utcnow(),
    )
    db.add(version)
    db.flush()

    db.add_all(
        [
            DatasetSample(
                version_id=version.id,
                row_index=index,
                text=row.text[:8000],
                label=row.label[:128],
                split=row.split,
                meta_json=row.meta,
            )
            for index, row in enumerate(rows)
        ]
    )
    dataset.updated_at = utcnow()
    db.commit()
    db.refresh(version)
    return version


def create_dataset(
    db: Session,
    *,
    name: str,
    description: str,
    task_type: str,
    owner_id: int | None,
    filename: str,
    raw: bytes,
    text_field: str = "text",
    label_field: str = "label",
    split_field: str = "",
    val_ratio: float = 0.2,
    created_by: str = "system",
) -> tuple[Dataset, DatasetVersion]:
    """新建数据集并导入 v1。"""
    if len(raw) > settings.max_upload_mb * 1024 * 1024:
        raise AppError(f"文件超过 {settings.max_upload_mb}MB 限制", code=40004)
    rows = parse_dataset(
        filename,
        raw,
        text_field=text_field,
        label_field=label_field,
        split_field=split_field,
        val_ratio=val_ratio,
        task_type=task_type,
    )
    if db.query(Dataset).filter(Dataset.name == name).first():
        raise AppError(f"数据集名称 '{name}' 已存在", code=40900, status_code=409)
    dataset = Dataset(
        name=name,
        description=description,
        task_type=task_type,
        owner_id=owner_id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(dataset)
    db.flush()
    version = import_rows(
        db, dataset=dataset, rows=rows, filename=filename, raw=raw, created_by=created_by
    )
    return dataset, version


def append_version(
    db: Session,
    *,
    dataset: Dataset,
    filename: str,
    raw: bytes,
    text_field: str = "text",
    label_field: str = "label",
    split_field: str = "",
    val_ratio: float = 0.2,
    created_by: str = "system",
) -> DatasetVersion:
    """给已有数据集追加一个新版本。"""
    if len(raw) > settings.max_upload_mb * 1024 * 1024:
        raise AppError(f"文件超过 {settings.max_upload_mb}MB 限制", code=40004)
    rows = parse_dataset(
        filename,
        raw,
        text_field=text_field,
        label_field=label_field,
        split_field=split_field,
        val_ratio=val_ratio,
        task_type=dataset.task_type,
    )
    return import_rows(
        db, dataset=dataset, rows=rows, filename=filename, raw=raw, created_by=created_by
    )


def load_samples_as_rows(db: Session, version_id: int) -> list[ParsedRow]:
    """把数据库样本还原成 ParsedRow（供训练与评测使用）。"""
    samples = (
        db.query(DatasetSample)
        .filter(DatasetSample.version_id == version_id)
        .order_by(DatasetSample.row_index)
        .all()
    )
    return [
        ParsedRow(text=item.text, label=item.label, split=item.split, meta=item.meta_json or {})
        for item in samples
    ]
