#!/usr/bin/env python3
from __future__ import annotations

import uuid
import requests
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct


QDRANT_URL = "http://127.0.0.1:6333"
OLLAMA_URL = "http://127.0.0.1:11434"
COLLECTION = "jarvis_memory"
EMBED_MODEL = "nomic-embed-text"

VAULT_PATH = Path("/mnt/d/Jarvis_vault")


def embed_text(text: str) -> list[float]:
    r = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={
            "model": EMBED_MODEL,
            "prompt": text,
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["embedding"]


def chunk_text(text: str, chunk_size: int = 1200):
    text = text.strip()

    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]


def index_file(client: QdrantClient, path: Path):
    try:
        text = path.read_text(
            encoding="utf-8",
            errors="ignore",
        ).strip()

        if not text:
            return

        chunks = list(chunk_text(text))

        points = []

        for idx, chunk in enumerate(chunks):
            vector = embed_text(chunk)

            point_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{path.resolve()}::{idx}"
                )
            )

            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "source": "obsidian",
                        "path": str(path),
                        "title": path.stem,
                        "chunk_index": idx,
                        "text": chunk,
                    },
                )
            )

        client.upsert(
            collection_name=COLLECTION,
            points=points,
        )

        print(f"Indexed {path} ({len(points)} chunks)")

    except Exception as e:
        print(f"FAILED {path}: {e}")


def main():
    client = QdrantClient(url=QDRANT_URL)

    md_files = list(VAULT_PATH.rglob("*.md"))

    print(f"Found {len(md_files)} markdown files")

    for path in md_files:
        index_file(client, path)


if __name__ == "__main__":
    main()