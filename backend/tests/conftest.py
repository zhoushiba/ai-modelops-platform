"""pytest 公共夹具。

关键点：**必须在导入 app 之前**设置环境变量，因为 ``app.config.settings``
在模块导入时就完成了读取（pydantic-settings 是即时求值的）。
这样测试全程使用临时 SQLite 库与临时 storage 目录，不会污染开发数据。
"""

from __future__ import annotations

import io
import os
import tempfile
import time
from pathlib import Path

import pytest

# --------------------------------------------------------------------------
# 1) 环境隔离（务必在 import app.* 之前）
# --------------------------------------------------------------------------
TMP_ROOT = Path(tempfile.mkdtemp(prefix="mops-test-"))
os.environ.update(
    {
        "ENV": "test",
        "DATABASE_URL": f"sqlite:///{(TMP_ROOT / 'test.db').as_posix()}",
        "STORAGE_DIR": str(TMP_ROOT / "storage"),
        "SEED_SAMPLES": "true",
        "JWT_SECRET": "pytest-secret-key",
        "LOG_LEVEL": "WARNING",
        "RATE_LIMIT_PER_MIN": "600",
        "RATE_LIMIT_BURST": "120",
        "TOKEN_QUOTA": "1000000",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "admin123",
    }
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
SAMPLES = BACKEND_DIR / "samples"


def _merged_tickets() -> bytes:
    """合并 train/val 样例，保证文件内自带 train/val 两段 split。"""
    train_text = (SAMPLES / "tickets_train.csv").read_text(encoding="utf-8").strip()
    val_lines = (SAMPLES / "tickets_val.csv").read_text(encoding="utf-8").strip().splitlines()
    return ("\n".join([train_text, *val_lines[1:]]) + "\n").encode("utf-8")


@pytest.fixture(scope="session")
def client():
    """带 lifespan 的测试客户端（会真实启动训练线程池与种子数据）。"""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def auth(client: TestClient) -> dict:
    """管理员 JWT 请求头。"""
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def ticket_csv() -> bytes:
    return _merged_tickets()


@pytest.fixture(scope="session")
def dataset_payload(client: TestClient, auth: dict, ticket_csv: bytes) -> dict:
    """上传一份工单分类数据集，返回 {dataset, version}。"""
    resp = client.post(
        "/api/datasets",
        headers=auth,
        data={
            "name": f"pytest-工单分类-{int(time.time())}",
            "description": "pytest fixture",
            "task_type": "text_classification",
            "text_field": "text",
            "label_field": "label",
            "split_field": "split",
            "val_ratio": "0.2",
        },
        files={"file": ("tickets.csv", io.BytesIO(ticket_csv), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def wait_job(client: TestClient, headers: dict, job_id: int, timeout: float = 180.0) -> dict:
    """轮询训练任务直到终态。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/training/jobs/{job_id}", headers=headers).json()["data"]
        if data["status"] in {"succeeded", "failed", "canceled"}:
            return data
        time.sleep(0.25)
    raise AssertionError(f"任务 {job_id} 在 {timeout}s 内未结束")


@pytest.fixture(scope="session")
def trained_job(client: TestClient, auth: dict, dataset_payload: dict) -> dict:
    """真实训练一个 TF-IDF + LogisticRegression 模型（CPU 秒级完成）。"""
    resp = client.post(
        "/api/training/jobs",
        headers=auth,
        json={
            "name": f"pytest-训练-{int(time.time())}",
            "dataset_version_id": dataset_payload["version"]["id"],
            "task_type": "text_classification",
            "base_model": "tfidf-logreg",
            "hyperparams": {"epochs": 3, "lr": 1.0, "max_features": 6000, "ngram_max": 2},
            "auto_register": True,
            "register_as": f"pytest-客服意图分类-{int(time.time())}",
        },
    )
    assert resp.status_code == 200, resp.text
    return wait_job(client, auth, resp.json()["data"]["id"])


@pytest.fixture(scope="session")
def deployment(client: TestClient, auth: dict, trained_job: dict) -> dict:
    """把训练好的模型一键部署为在线推理服务。"""
    resp = client.post(
        "/api/deployments",
        headers=auth,
        json={
            "model_version_id": trained_job["model_version_id"],
            "name": f"pytest-cls-{int(time.time())}",
            "alias": f"pytest-alias-{int(time.time())}",
            "qps_limit": 100,
            "description": "pytest 部署",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


@pytest.fixture(scope="session")
def api_key(client: TestClient, auth: dict) -> dict:
    """创建一个高配额 API Key，供推理协议测试使用。"""
    resp = client.post(
        "/api/api-keys",
        headers=auth,
        json={"name": f"pytest-key-{int(time.time())}", "rate_limit_per_min": 600, "burst": 200},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]
