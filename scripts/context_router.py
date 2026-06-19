#!/usr/bin/env python3
from __future__ import annotations

import requests
from qdrant_client import QdrantClient


QDRANT_URL = "http://127.0.0.1:6333"
OLLAMA_URL = "http://127.0.0.1:11434"
COLLECTION = "jarvis_memory"
EMBED_MODEL = "nomic-embed-text"


def embed_text(text: str) -> list[float]:
    r = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["embedding"]


def compact_with_planner_model(query: str, raw_context: str) -> str:
    r = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": "qwen3:14b",
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Compress retrieved memory for a planning agent. "
                        "Return only concise bullet points. "
                        "Keep technical facts, paths, decisions, and constraints. "
                        "Remove frontmatter, duplicates, irrelevant text, and filler. "
                        "Maximum 12 bullets."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Current request:\n{query}\n\n"
                        f"Retrieved memory:\n{raw_context}"
                    ),
                },
            ],
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["message"]["content"].strip()



def embed_text(text: str) -> list[float]:
    r = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["embedding"]


def compact_with_planner_model(query: str, raw_context: str) -> str:
    r = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": "qwen3:14b",
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Compress retrieved memory for a planning agent. "
                        "Return only concise bullet points. "
                        "Keep technical facts, paths, decisions, and constraints. "
                        "Remove frontmatter, duplicates, irrelevant text, and filler. "
                        "Maximum 12 bullets."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Current request:\n{query}\n\n"
                        f"Retrieved memory:\n{raw_context}"
                    ),
                },
            ],
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["message"]["content"].strip()

def build_context_pack(query: str, limit: int = 5) -> str:
    if not query or len(query.strip()) < 4:
        return ""

    try:
        client = QdrantClient(url=QDRANT_URL)
        query_vector = embed_text(query)

        hits = client.query_points(
            collection_name=COLLECTION,
            query=query_vector,
            limit=limit,
        ).points

        blocks = []

        for i, hit in enumerate(hits, start=1):
            payload = hit.payload or {}
            score = float(hit.score or 0)

            if score < 0.45:
                continue

            title = payload.get("title", "Untitled")
            path = payload.get("path", "")
            text = payload.get("text", "")

            blocks.append(
                f"[Memory {i}]\n"
                f"Title: {title}\n"
                f"Path: {path}\n"
                f"Score: {score:.3f}\n"
                f"Content:\n{text[:1200]}"
            )

        if not blocks:
            return ""

        raw_context = "\n\n---\n\n".join(blocks)

        try:
            compact = compact_with_planner_model(query, raw_context)
        except Exception as e:
            compact = (
                f"Memory compression failed: {e}\n\n"
                f"Fallback raw memory:\n{raw_context[:2500]}"
            )

        return (
            "Relevant compact JARVIS memory from Obsidian/Qdrant:\n\n"
            + compact
        )

    except Exception as e:
        return f"Memory retrieval failed: {e}"