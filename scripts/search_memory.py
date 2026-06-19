#!/usr/bin/env python3
from __future__ import annotations

import sys
import requests

from qdrant_client import QdrantClient


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


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print('python3 scripts/search_memory.py "your query"')
        sys.exit(1)

    query = sys.argv[1]

    query_vector = embed_text(query)

    client = QdrantClient(url=QDRANT_URL)

    hits = client.query_points(
        collection_name=COLLECTION,
        query=query_vector,
        limit=5,
    ).points

    print(f"\nQUERY: {query}\n")

    for idx, hit in enumerate(hits, start=1):
        payload = hit.payload

        print("=" * 80)
        print(f"RESULT #{idx}")
        print(f"SCORE: {hit.score:.4f}")
        print(f"TITLE: {payload.get('title')}")
        print(f"PATH: {payload.get('path')}")
        print("-" * 80)
        print(payload.get("text", "")[:1200])
        print()


if __name__ == "__main__":
    main()