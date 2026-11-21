"""端到端冒烟脚本：真实跑通「建数据集 → 训练 → 部署 → OpenAI 兼容推理」。

用法（先启动后端）：
    python -m uvicorn app.main:app --port 8000
    python scripts/smoke_test.py --base-url http://127.0.0.1:8000

脚本会依次执行并打印关键响应片段，任一步失败即以非 0 退出码结束，
可直接用于 CI 或作品集验收演示。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
TERMINAL = {"succeeded", "failed", "canceled"}


def log(title: str, payload: object = "") -> None:
    print(f"\n=== {title} ===")
    if payload != "":
        if isinstance(payload, (dict, list)):
            print(json.dumps(payload, ensure_ascii=False, indent=2)[:1600])
        else:
            print(payload)


def wait_job(client: httpx.Client, headers: dict, job_id: int, timeout: int = 180) -> dict:
    """轮询训练任务直到终态，期间打印状态变化。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        data = client.get(f"/api/training/jobs/{job_id}", headers=headers).json()["data"]
        snapshot = (data["status"], data["progress"])
        if snapshot != last:
            print(f"  job {job_id}: {data['status']} {data['progress']}% - {data.get('status_message', '')}")
            last = snapshot
        if data["status"] in TERMINAL:
            return data
        time.sleep(1.0)
    raise SystemExit(f"任务 {job_id} 超时未结束")


def wait_health(client: httpx.Client, timeout: int = 40) -> dict:
    """等待服务就绪：刚启动的 uvicorn 需要几秒绑定端口，避免冒烟因连接被拒失败。"""
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            resp = client.get("/health")
            if resp.status_code == 200:
                return resp.json()
            last_error = f"HTTP {resp.status_code}"
        except httpx.HTTPError as exc:  # 端口未就绪
            last_error = str(exc)
        time.sleep(1.0)
    raise SystemExit(f"服务在 {timeout}s 内未就绪：{last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="AI ModelOps Platform 端到端冒烟")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--skip-rag", action="store_true")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base_url, timeout=60.0)

    # 1. 健康检查
    health = wait_health(client)
    log("1) GET /health", health)
    assert health["status"] == "ok", health

    # 2. 登录
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    log("2) POST /api/auth/login", {"user": resp.json()["data"]["user"], "token_prefix": token[:24] + "..."})

    # 3. 创建数据集（上传样例 CSV）
    train_text = (SAMPLES / "tickets_train.csv").read_text(encoding="utf-8").strip()
    val_lines = (SAMPLES / "tickets_val.csv").read_text(encoding="utf-8").strip().splitlines()
    raw = ("\n".join([train_text, *val_lines[1:]]) + "\n").encode("utf-8")
    resp = client.post(
        "/api/datasets",
        headers=headers,
        data={
            "name": f"冒烟用工单数据集-{int(time.time())}",
            "description": "smoke test",
            "task_type": "text_classification",
            "text_field": "text",
            "label_field": "label",
            "split_field": "split",
            "val_ratio": "0.2",
        },
        files={"file": ("tickets_smoke.csv", raw, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()["data"]
    dataset, version = payload["dataset"], payload["version"]
    log(
        "3) POST /api/datasets",
        {
            "dataset": {"id": dataset["id"], "name": dataset["name"], "task_type": dataset["task_type"]},
            "version": {
                "id": version["id"],
                "row_count": version["row_count"],
                "train_count": version["train_count"],
                "val_count": version["val_count"],
                "checksum": version["checksum"][:16] + "...",
            },
        },
    )

    # 4. 提交训练任务（真实 sklearn 训练）
    resp = client.post(
        "/api/training/jobs",
        headers=headers,
        json={
            "name": f"冒烟-TFIDF-{int(time.time())}",
            "dataset_version_id": version["id"],
            "task_type": "text_classification",
            "base_model": "tfidf-logreg",
            "hyperparams": {"epochs": args.epochs, "lr": 1.0, "max_features": 8000, "ngram_max": 2},
            "auto_register": True,
            "register_as": f"冒烟客服意图分类-{int(time.time())}",
        },
    )
    assert resp.status_code == 200, resp.text
    job = resp.json()["data"]
    log("4) POST /api/training/jobs", {"id": job["id"], "status": job["status"], "task_type": job["task_type"]})

    # 5. 轮询直到 succeeded
    started = time.time()
    job = wait_job(client, headers, job["id"])
    elapsed = round(time.time() - started, 2)
    log(
        "5) 训练完成",
        {
            "status": job["status"],
            "duration_ms": job.get("duration_ms"),
            "artifact_path": job.get("artifact_path"),
            "artifact_size": job.get("artifact_size"),
            "artifact_sha256": job.get("artifact_sha256"),
            "wall_clock_s": elapsed,
            "metrics": {
                key: job["metrics"].get(key)
                for key in ("accuracy", "f1_macro", "precision_macro", "recall_macro", "train_size", "val_size")
            },
        },
    )
    assert job["status"] == "succeeded", job.get("status_message")

    logs = client.get(f"/api/training/jobs/{job['id']}/logs", headers=headers).json()["data"]["items"]
    log("   训练日志（末 6 条）", [f"[{item['level']}] {item['message']}" for item in logs[-6:]])

    # 6. 部署为在线推理服务
    model_version_id = job.get("model_version_id")
    assert model_version_id, "任务未自动注册模型版本"
    resp = client.post(
        "/api/deployments",
        headers=headers,
        json={
            "model_version_id": model_version_id,
            "name": f"smoke-cls-{int(time.time())}",
            "alias": f"smoke-cls-alias-{int(time.time())}",
            "qps_limit": 50,
        },
    )
    assert resp.status_code == 200, resp.text
    deployment = resp.json()["data"]
    log("6) POST /api/deployments", {"id": deployment["id"], "name": deployment["name"], "status": deployment["status"]})

    # 7. 创建 API Key（明文只返回一次）
    resp = client.post(
        "/api/api-keys",
        headers=headers,
        json={"name": f"smoke-key-{int(time.time())}", "rate_limit_per_min": 600, "burst": 100},
    )
    assert resp.status_code == 200, resp.text
    key_data = resp.json()["data"]
    api_key = key_data["plain_key"]
    log("7) POST /api/api-keys", {"id": key_data["id"], "prefix": key_data["prefix"], "plain_key": api_key[:16] + "..."})
    auth = {"Authorization": f"Bearer {api_key}"}

    # 8. OpenAI 兼容推理：chat completions
    resp = client.post(
        "/v1/chat/completions",
        headers=auth,
        json={
            "model": deployment["name"],
            "messages": [{"role": "user", "content": "我上周买的蓝牙耳机右耳没有声音，想申请退款"}],
            "temperature": 0.2,
        },
    )
    assert resp.status_code == 200, resp.text
    chat = resp.json()
    log(
        "8) POST /v1/chat/completions",
        {
            "id": chat["id"],
            "object": chat["object"],
            "model": chat["model"],
            "choices": chat["choices"],
            "usage": chat["usage"],
            "modelops": chat.get("modelops"),
        },
    )

    # 9. 流式（SSE）推理
    chunks: list[str] = []
    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers=auth,
        json={
            "model": deployment["name"],
            "messages": [{"role": "user", "content": "物流显示签收但我没收到货怎么办"}],
            "stream": True,
        },
    ) as stream:
        for line in stream.iter_lines():
            if line.startswith("data: "):
                chunks.append(line[6:])
    log("9) POST /v1/chat/completions (stream=true)", {"chunks": len(chunks), "first": chunks[0][:160], "last": chunks[-1]})

    # 10. OpenAI 兼容推理：embeddings
    resp = client.post(
        "/v1/embeddings",
        headers=auth,
        json={"model": deployment["name"], "input": ["退货怎么操作", "发票怎么开"]},
    )
    assert resp.status_code == 200, resp.text
    emb = resp.json()
    log(
        "10) POST /v1/embeddings",
        {
            "object": emb["object"],
            "model": emb["model"],
            "count": len(emb["data"]),
            "dim": len(emb["data"][0]["embedding"]),
            "head": [round(value, 4) for value in emb["data"][0]["embedding"][:6]],
            "usage": emb["usage"],
        },
    )

    # 11. RAG 索引构建 + 检索问答
    if not args.skip_rag:
        rag_raw = (SAMPLES / "knowledge_docs.jsonl").read_bytes()
        resp = client.post(
            "/api/datasets",
            headers=headers,
            data={
                "name": f"冒烟用知识库-{int(time.time())}",
                "description": "smoke rag",
                "task_type": "rag_corpus",
                "text_field": "text",
                "label_field": "",
                "split_field": "",
                "val_ratio": "0",
            },
            files={"file": ("knowledge_docs.jsonl", rag_raw, "application/jsonl")},
        )
        assert resp.status_code == 200, resp.text
        rag_version = resp.json()["data"]["version"]
        resp = client.post(
            "/api/training/jobs",
            headers=headers,
            json={
                "name": f"冒烟-RAG-{int(time.time())}",
                "dataset_version_id": rag_version["id"],
                "task_type": "rag_corpus",
                "base_model": "hashing-tfidf",
                "hyperparams": {"embedding_dim": 384, "chunk_size": 140, "chunk_overlap": 30},
                "auto_register": True,
                "register_as": f"冒烟知识库索引-{int(time.time())}",
            },
        )
        assert resp.status_code == 200, resp.text
        rag_job = wait_job(client, headers, resp.json()["data"]["id"])
        log(
            "11) RAG 索引任务",
            {
                "status": rag_job["status"],
                "metrics": {
                    key: rag_job["metrics"].get(key)
                    for key in ("doc_count", "chunk_count", "embedding_dim", "self_hit_rate")
                },
            },
        )
        resp = client.post(
            "/api/deployments",
            headers=headers,
            json={
                "model_version_id": rag_job["model_version_id"],
                "name": f"smoke-rag-{int(time.time())}",
                "alias": f"smoke-rag-alias-{int(time.time())}",
                "qps_limit": 50,
            },
        )
        assert resp.status_code == 200, resp.text
        rag_deployment = resp.json()["data"]
        resp = client.post(
            "/v1/chat/completions",
            headers=auth,
            json={
                "model": rag_deployment["name"],
                "messages": [{"role": "user", "content": "退款一般多久到账？"}],
            },
        )
        assert resp.status_code == 200, resp.text
        rag_chat = resp.json()
        log(
            "    RAG 检索问答",
            {
                "content": rag_chat["choices"][0]["message"]["content"][:300],
                "citations": [c.get("title") for c in rag_chat["modelops"].get("citations", [])],
            },
        )

    # 12. 用量与日志
    usage = client.get("/api/usage/summary?days=1", headers=headers).json()["data"]
    log(
        "12) GET /api/usage/summary",
        {key: usage.get(key) for key in ("total_requests", "total_tokens", "error_rate", "avg_latency_ms")},
    )
    stats = client.get(f"/api/deployments/{deployment['id']}/stats", headers=headers).json()["data"]
    log("    GET /api/deployments/{id}/stats", {key: stats.get(key) for key in ("status", "request_count", "qps_last_minute", "avg_latency_ms")})

    print("\n✅ 冒烟通过：训练真的跑了、模型产物已落盘、OpenAI 兼容推理返回真实结果。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
