#!/usr/bin/env python3
"""
JARVIS boot init — one-shot startup tasks, extracted from jarvis.sh inline code.
Run by jarvis-init.service after redis/qdrant/ollama are up.

Idempotent and fault-tolerant: every step degrades gracefully so a missing
backend never blocks the rest of the stack from starting.
"""

import json
import os
import pathlib
import sys

PROJECT_DIR = pathlib.Path(__file__).resolve().parent.parent
VAULT_DIR = pathlib.Path(os.environ.get("VAULT_DIR", "/mnt/d/Jarvis_vault"))
STAGING_ROOT = pathlib.Path(os.environ.get("JARVIS_STAGING", "/mnt/e/coding/staging"))
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

sys.path.insert(0, str(PROJECT_DIR))


def step(name):
    print(f"[INIT] {name}")


def init_staging():
    step("staging workspace")
    for sub in ("dev", "tested", "approved"):
        (STAGING_ROOT / sub).mkdir(parents=True, exist_ok=True)


def init_bridge():
    step("bridge state")
    bridge = pathlib.Path("/tmp/jarvis")
    bridge.mkdir(parents=True, exist_ok=True)
    (bridge / "state.txt").write_text("standby")
    (bridge / "emotion.txt").write_text("neutral")
    (bridge / "input.txt").write_text("")


def init_redis():
    step("redis init")
    try:
        import subprocess
        subprocess.run(
            [sys.executable, str(PROJECT_DIR / "scripts" / "redis_init.py")],
            timeout=30, check=False,
        )
    except Exception as e:
        print(f"[INIT] redis_init skipped: {e}")


def init_agent_memory():
    step("agent memory")
    try:
        from memory.redis_memory import write_state, write_task, reset_loop
        write_state("JARVIS", task="booting", tools={}, confidence="low", notes="startup")
        write_task("idle")
        reset_loop()
        print("[INIT] agent memory initialised")
    except Exception as e:
        print(f"[INIT] agent memory skipped: {e}")


def ingest_last_snapshot():
    """Load last session snapshot into Qdrant (needs Ollama embeddings + Qdrant)."""
    step("snapshot ingestion")
    try:
        snapshot_dir = VAULT_DIR / "snapshots"
        snapshots = sorted(snapshot_dir.glob("session_*.json")) if snapshot_dir.exists() else []
        if not snapshots:
            print("[INIT] no snapshots, skipping")
            return

        latest = snapshots[-1]
        data = json.loads(latest.read_text())

        lines = []
        if data.get("task"):
            lines.append(f"Last task: {data['task']}")
        lines += [f"Step: {s}" for s in data.get("steps", [])]
        lines += [f"Memory: {m}" for m in data.get("working_memory", [])]
        if data.get("snapshot_at"):
            lines.append(f"Session ended: {data['snapshot_at']}")
        if not lines:
            print("[INIT] snapshot empty, skipping")
            return

        text = "\n".join(lines)

        import requests
        import uuid
        resp = requests.post(f"{OLLAMA_HOST}/api/embeddings",
                             json={"model": "nomic-embed-text", "prompt": text},
                             timeout=30)
        embedding = resp.json().get("embedding") or []
        if not embedding:
            print("[INIT] embeddings unavailable, skipping snapshot ingestion")
            return

        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PointStruct
        q = QdrantClient(host="127.0.0.1", port=6333)
        collection = "jarvis_sessions"
        existing = [c.name for c in q.get_collections().collections]
        if collection not in existing:
            q.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=len(embedding), distance=Distance.COSINE),
            )
        q.upsert(collection_name=collection, points=[PointStruct(
            id=str(uuid.uuid4()), vector=embedding,
            payload={"source": latest.name, "task": data.get("task", ""),
                     "steps": data.get("steps", []),
                     "loop_count": data.get("loop_count", 0),
                     "snapshot_at": data.get("snapshot_at", ""), "text": text},
        )])
        print(f"[INIT] snapshot {latest.name} ingested ({len(lines)} items)")
    except Exception as e:
        print(f"[INIT] snapshot ingestion skipped: {e}")


if __name__ == "__main__":
    init_staging()
    init_bridge()
    init_redis()
    init_agent_memory()
    ingest_last_snapshot()
    print("[INIT] done")
