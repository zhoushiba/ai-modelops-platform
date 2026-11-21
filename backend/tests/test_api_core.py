"""核心接口测试：健康检查、认证、数据集、训练状态机、部署、OpenAI 兼容推理、用量。"""

from __future__ import annotations

import hashlib
import io
import time

from fastapi.testclient import TestClient

from app.config import settings
from tests.conftest import wait_job


# --------------------------------------------------------------------------
# 健康检查与认证
# --------------------------------------------------------------------------
def test_health(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["app"] == settings.app_name
    assert body["database"] == "sqlite"


def test_login_success(client: TestClient) -> None:
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["access_token"] and data["user"]["username"] == "admin"


def test_login_wrong_password(client: TestClient) -> None:
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "bad-pass"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == 40110
    assert body["trace_id"]


def test_me_requires_token(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_token(client: TestClient, auth: dict) -> None:
    body = client.get("/api/auth/me", headers=auth).json()["data"]
    assert body["username"] == "admin"
    assert "password_hash" not in body


def test_api_key_cannot_call_management_api(client: TestClient, api_key: dict) -> None:
    """API Key 只能调 /v1/**，不允许调管理面接口。"""
    resp = client.get("/api/datasets", headers={"Authorization": f"Bearer {api_key['plain_key']}"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------
# 数据集
# --------------------------------------------------------------------------
def test_dataset_upload_and_split(client: TestClient, auth: dict, dataset_payload: dict) -> None:
    version = dataset_payload["version"]
    assert version["row_count"] == 300
    assert version["train_count"] > 0 and version["val_count"] > 0
    assert version["train_count"] + version["val_count"] == version["row_count"]
    assert len(version["checksum"]) == 64


def test_dataset_list_and_detail(client: TestClient, auth: dict, dataset_payload: dict) -> None:
    listing = client.get("/api/datasets", headers=auth, params={"page": 1, "size": 5}).json()["data"]
    assert listing["total"] >= 3  # 种子数据 + 本次上传
    assert len(listing["items"]) <= 5
    detail = client.get(f"/api/datasets/{dataset_payload['dataset']['id']}", headers=auth).json()["data"]
    assert detail["versions"]
    assert detail["version_count"] >= 1


def test_dataset_duplicate_name_conflicts(
    client: TestClient, auth: dict, dataset_payload: dict, ticket_csv: bytes
) -> None:
    resp = client.post(
        "/api/datasets",
        headers=auth,
        data={
            "name": dataset_payload["dataset"]["name"],
            "task_type": "text_classification",
            "text_field": "text",
            "label_field": "label",
            "split_field": "split",
        },
        files={"file": ("tickets.csv", io.BytesIO(ticket_csv), "text/csv")},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 40900


def test_dataset_missing_label_column_rejected(client: TestClient, auth: dict) -> None:
    csv_body = "text\n这是一条没有标签的数据\n".encode("utf-8")
    resp = client.post(
        "/api/datasets",
        headers=auth,
        data={
            "name": f"pytest-缺列-{int(time.time())}",
            "task_type": "text_classification",
            "text_field": "text",
            "label_field": "label",
        },
        files={"file": ("bad.csv", io.BytesIO(csv_body), "text/csv")},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40003


def test_dataset_quality_report(client: TestClient, auth: dict, dataset_payload: dict) -> None:
    version_id = dataset_payload["version"]["id"]
    report = client.get(f"/api/dataset-versions/{version_id}/quality", headers=auth).json()["data"]
    assert report["row_count"] == 300
    assert 0.0 <= report["duplicate_ratio"] <= 1.0
    assert len(report["label_distribution"]) >= 5
    assert "length_stats" in report


def test_dataset_version_diff(client: TestClient, auth: dict, dataset_payload: dict) -> None:
    """追加一版数据后，diff 应只统计新增/删除，而不是整表变化。"""
    dataset_id = dataset_payload["dataset"]["id"]
    extra = (
        "text,label,split\n"
        "我买的电饭煲内胆涂层脱落了，能不能换新,商品质量,val\n"
        "发票抬头写错了公司名怎么改,发票开票,val\n"
    ).encode("utf-8")
    resp = client.post(
        f"/api/datasets/{dataset_id}/versions",
        headers=auth,
        data={"text_field": "text", "label_field": "label", "split_field": "split", "val_ratio": "0.2"},
        files={"file": ("tickets_v2.csv", io.BytesIO(extra), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    new_version = resp.json()["data"]["version"]
    assert new_version["version"] == dataset_payload["version"]["version"] + 1

    diff = client.get(
        f"/api/dataset-versions/{new_version['id']}/diff",
        headers=auth,
        params={"against": dataset_payload["version"]["id"]},
    ).json()["data"]
    assert diff["changed_total"] > 0


def test_dataset_samples_pagination(client: TestClient, auth: dict, dataset_payload: dict) -> None:
    version_id = dataset_payload["version"]["id"]
    page = client.get(
        f"/api/dataset-versions/{version_id}/samples",
        headers=auth,
        params={"split": "train", "page": 1, "size": 10},
    ).json()["data"]
    assert page["size"] == 10
    assert len(page["items"]) == 10
    assert all(item["split"] == "train" for item in page["items"])


# --------------------------------------------------------------------------
# 训练任务（真实训练）
# --------------------------------------------------------------------------
def test_training_job_succeeded(trained_job: dict) -> None:
    assert trained_job["status"] == "succeeded"
    assert trained_job["progress"] == 100
    assert trained_job["duration_ms"] >= 0
    assert trained_job["model_version_id"], "训练成功后应自动注册模型版本"


def test_training_artifact_checksum(trained_job: dict) -> None:
    path = settings.absolute_path(trained_job["artifact_path"])
    assert path.exists(), f"模型产物不存在：{path}"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == trained_job["artifact_sha256"]
    assert trained_job["artifact_size"] == path.stat().st_size


def test_training_metrics_quality(trained_job: dict) -> None:
    metrics = trained_job["metrics"]
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert metrics["accuracy"] >= 0.8, metrics
    assert metrics["train_size"] > metrics["val_size"]
    assert metrics["label_count"] >= 5
    assert len(metrics["confusion_matrix"]) == metrics["label_count"]


def test_training_logs_and_metric_series(client: TestClient, auth: dict, trained_job: dict) -> None:
    logs = client.get(f"/api/training/jobs/{trained_job['id']}/logs", headers=auth).json()["data"]
    assert logs["status"] == "succeeded"
    assert any("epoch" in item["message"] for item in logs["items"])
    series = client.get(f"/api/training/jobs/{trained_job['id']}/metrics", headers=auth).json()["data"]
    names = {point["name"] for point in series["items"]}
    assert {"train_loss", "val_acc"} & names


def test_training_job_invalid_hyperparams(client: TestClient, auth: dict, dataset_payload: dict) -> None:
    resp = client.post(
        "/api/training/jobs",
        headers=auth,
        json={
            "name": "非法超参",
            "dataset_version_id": dataset_payload["version"]["id"],
            "task_type": "text_classification",
            "hyperparams": {"epochs": 999},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40031


def test_training_job_task_type_mismatch(client: TestClient, auth: dict, dataset_payload: dict) -> None:
    resp = client.post(
        "/api/training/jobs",
        headers=auth,
        json={
            "name": "任务类型不匹配",
            "dataset_version_id": dataset_payload["version"]["id"],
            "task_type": "rag_corpus",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40030


def test_cancel_queued_job(client: TestClient, auth: dict, dataset_payload: dict) -> None:
    first = client.post(
        "/api/training/jobs",
        headers=auth,
        json={
            "name": f"pytest-取消-{int(time.time())}",
            "dataset_version_id": dataset_payload["version"]["id"],
            "task_type": "text_classification",
            "hyperparams": {"epochs": 2},
        },
    ).json()["data"]
    resp = client.post(f"/api/training/jobs/{first['id']}/cancel", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] in {"canceled", "running", "succeeded"}


def test_trainers_list(client: TestClient, auth: dict) -> None:
    tasks = client.get("/api/training/trainers", headers=auth).json()["data"]
    names = {item["task_type"] for item in tasks}
    assert {"text_classification", "rag_corpus"} <= names


# --------------------------------------------------------------------------
# 模型注册表
# --------------------------------------------------------------------------
def test_model_card_generated(client: TestClient, auth: dict, trained_job: dict) -> None:
    resp = client.get(f"/api/models/versions/{trained_job['model_version_id']}/card", headers=auth)
    assert resp.status_code == 200
    card = resp.json()["data"]["model_card"]
    assert "Model Card" in card
    assert "评估指标" in card and "预期用途" in card


def test_register_again_is_idempotent(client: TestClient, auth: dict, trained_job: dict) -> None:
    resp = client.post(f"/api/training/jobs/{trained_job['id']}/register", headers=auth, json={})
    assert resp.status_code == 200
    assert resp.json()["data"]["already"] is True


# --------------------------------------------------------------------------
# 部署 + OpenAI 兼容推理
# --------------------------------------------------------------------------
def test_deployment_running(deployment: dict) -> None:
    assert deployment["status"] == "running"
    assert deployment["curl"].startswith("curl")


def test_chat_completion_protocol(client: TestClient, deployment: dict, api_key: dict) -> None:
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key['plain_key']}"},
        json={
            "model": deployment["name"],
            "messages": [{"role": "user", "content": "我的快递一直没有更新，想查一下物流"}],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["object"] == "chat.completion"
    assert body["id"].startswith("chatcmpl-")
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["choices"][0]["message"]["content"]
    assert body["usage"]["total_tokens"] == body["usage"]["prompt_tokens"] + body["usage"]["completion_tokens"]
    assert body["modelops"]["trace_id"]
    assert body["modelops"]["deployment_id"] == deployment["id"]


def test_chat_completion_unknown_model(client: TestClient, api_key: dict) -> None:
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key['plain_key']}"},
        json={"model": "不存在的部署", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "model_not_found"
    assert "message" in resp.json()["error"]


def test_chat_completion_requires_key(client: TestClient, deployment: dict) -> None:
    resp = client.post(
        "/v1/chat/completions",
        json={"model": deployment["name"], "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_api_key"


def test_chat_completion_stream(client: TestClient, deployment: dict, api_key: dict) -> None:
    chunks: list[str] = []
    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key['plain_key']}"},
        json={
            "model": deployment["name"],
            "messages": [{"role": "user", "content": "优惠券用不了怎么处理"}],
            "stream": True,
        },
    ) as stream:
        for line in stream.iter_lines():
            if line.startswith("data: "):
                chunks.append(line[6:])
    assert chunks[-1] == "[DONE]"
    assert any('"chat.completion.chunk"' in item for item in chunks[:-1])


def test_embeddings_protocol(client: TestClient, deployment: dict, api_key: dict) -> None:
    resp = client.post(
        "/v1/embeddings",
        headers={"Authorization": f"Bearer {api_key['plain_key']}"},
        json={"model": deployment["name"], "input": ["退货流程", "开票流程"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["object"] == "list"
    assert len(body["data"]) == 2
    vector = body["data"][0]["embedding"]
    assert len(vector) == 384
    assert all(isinstance(value, float) for value in vector[:5])
    assert body["data"][0]["object"] == "embedding"


def test_embeddings_base64_format(client: TestClient, deployment: dict, api_key: dict) -> None:
    resp = client.post(
        "/v1/embeddings",
        headers={"Authorization": f"Bearer {api_key['plain_key']}"},
        json={"model": deployment["name"], "input": "只编码一句话", "encoding_format": "base64"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"][0]["embedding"], str)


def test_rate_limit_returns_429(client: TestClient, auth: dict, deployment: dict) -> None:
    """令牌桶容量为 1 时，第二次请求必须 429 并带 Retry-After。"""
    key = client.post(
        "/api/api-keys",
        headers=auth,
        json={
            "name": f"pytest-限流-{int(time.time())}",
            "rate_limit_per_min": 1,
            "burst": 1,
            "token_quota": 100000,
        },
    ).json()["data"]
    headers = {"Authorization": f"Bearer {key['plain_key']}"}
    payload = {"model": deployment["name"], "messages": [{"role": "user", "content": "限流测试"}]}
    first = client.post("/v1/chat/completions", headers=headers, json=payload)
    assert first.status_code == 200, first.text
    second = client.post("/v1/chat/completions", headers=headers, json=payload)
    assert second.status_code == 429
    body = second.json()
    assert body["error"]["code"] == "rate_limit_exceeded"
    assert int(second.headers["Retry-After"]) >= 1


# --------------------------------------------------------------------------
# 用量、日志与看板
# --------------------------------------------------------------------------
def test_usage_summary_and_logs(client: TestClient, auth: dict) -> None:
    summary = client.get("/api/usage/summary", headers=auth, params={"days": 1}).json()["data"]
    assert summary["total_requests"] >= 1
    assert summary["total_tokens"] >= 1
    logs = client.get("/api/usage/logs", headers=auth, params={"page": 1, "size": 5}).json()["data"]
    assert logs["total"] >= 1
    assert {"endpoint", "status_code", "latency_ms"} <= set(logs["items"][0])


def test_deployment_stats(client: TestClient, auth: dict, deployment: dict) -> None:
    stats = client.get(f"/api/deployments/{deployment['id']}/stats", headers=auth).json()["data"]
    assert stats["request_count"] >= 1
    assert stats["avg_latency_ms"] >= 0
    assert isinstance(stats["series"], list)


def test_dashboard_summary(client: TestClient, auth: dict) -> None:
    body = client.get("/api/dashboard/summary", headers=auth).json()["data"]
    assert body["dataset_count"] >= 1
    assert body["training_job_count"] >= 1
    assert body["model_count"] >= 1
    assert "recent_jobs" in body


def test_trace_id_header_roundtrip(client: TestClient) -> None:
    resp = client.get("/health", headers={"X-Trace-Id": "trace-pytest-001"})
    assert resp.headers["X-Trace-Id"] == "trace-pytest-001"
    body = client.get("/api/datasets").json()
    assert body["trace_id"]
