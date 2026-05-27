#!/usr/bin/env python3
from __future__ import annotations

import sys
import uuid
import requests
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct


QDRANT_URL = "http://127.0.0.1:6333"
OLLAMA_URL = "http://127.0.0.1:11434"
COLLECTION = "jarvis_memory"
EMBED_MODEL = "nomic-embed-text"


def embed_text(text: str) -> list[float]:
    r = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={
            "model": EMBED_MODEL,
            "prompt": text,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["embedding"]


def read_note(path: str) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    return p.read_text(encoding="utf-8", errors="ignore")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/index_one_note.py /path/to/note.md")
        sys.exit(1)

    note_path = Path(sys.argv[1]).expanduser()
    text = read_note(str(note_path)).strip()

    if not text:
        raise ValueError("Note is empty")

    chunk = text[:4000]
    vector = embed_text(chunk)

    client = QdrantClient(url=QDRANT_URL)

    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(note_path.resolve())))

    client.upsert(
        collection_name=COLLECTION,
        points=[
            PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "source": "obsidian",
                    "path": str(note_path),
                    "title": note_path.stem,
                    "text": chunk,
                },
            )
        ],
    )

    print(f"Indexed: {note_path}")
    print(f"Point ID: {point_id}")

    query = "Jarvis memory architecture"
    query_vector = embed_text(query)

    hits = client.query_points(
        collection_name=COLLECTION,
        query=query_vector,
        limit=5,
    ).points

    print("\nSearch results:")
    for hit in hits:
        print("-" * 60)
        print("score:", hit.score)
        print("title:", hit.payload.get("title"))
        print("path:", hit.payload.get("path"))
        print("text:", hit.payload.get("text", "")[:500])


if __name__ == "__main__":
    main()