"""
JARVIS OS — Memory Router
/jarvis/memory/memory_router.py

Memory types:
  recent_chat  — this conversation / last few turns (in-context)
  chat_log     — exact old wording, previous commands, debugging history
  qdrant       — semantic memory, concepts, decisions, summaries
  obsidian     — durable notes, project docs, plans
  files        — code/config source of truth
  tools        — live action or device state (caller handles, not fetched here)

Flow:
  Pass 1 — classify: need memory? which types?
  Pass 2 — build fetch plan per type
  Pass 3 — fetch all types
  Pass 4 — summarize into one context block
"""

import json
import requests
from pathlib import Path
from qdrant_client import QdrantClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OLLAMA_BASE   = "http://127.0.0.1:11434"
EMBED_MODEL   = "nomic-embed-text"

# Routing passes (1, 2, 4) run against llama.cpp Gemma 4B — fast, cheap
LLAMA_CPP_BASE  = "http://127.0.0.1:8081"
FAST_MODEL      = "gemma4:4b"   # label only — llama.cpp serves whatever is loaded
QDRANT_HOST   = "127.0.0.1"
QDRANT_PORT   = 6333
QDRANT_COLS   = ["jarvis_sessions", "jarvis_memory"]
OBSIDIAN_DIR  = Path("/mnt/d/Jarvis_vault")
CHAT_LOG_PATH = Path("/mnt/d/Jarvis_vault/chat_log.jsonl")
TOP_K         = 5
SCORE_MIN     = 0.55  # lower while collections are sparse; raise to 0.65 once populated

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _llama(prompt: str, system: str, timeout: int = 20) -> str:
    """Call llama.cpp server (Gemma 4B) for fast routing passes."""
    try:
        resp = requests.post(f"{LLAMA_CPP_BASE}/v1/chat/completions", json={
            "model":    "gemma",
            "messages": [
                {"role": "system",  "content": system},
                {"role": "user",    "content": prompt}
            ],
            "temperature": 0.1,
            "stream":      False
        }, timeout=timeout)
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        if "<think>" in raw:
            raw = raw.split("</think>")[-1].strip()
        return raw
    except Exception as e:
        return f"ERROR: {e}"

def _embed(text: str) -> list[float] | None:
    try:
        resp = requests.post(f"{OLLAMA_BASE}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text}, timeout=15)
        return resp.json().get("embedding")
    except Exception:
        return None

def _parse_json(raw: str) -> dict | list | None:
    try:
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None

# ---------------------------------------------------------------------------
# Pass 1 — classify
# ---------------------------------------------------------------------------

CLASSIFY_SYSTEM = """You are the memory classifier for JARVIS, a local AI assistant.

Available memory types and their use cases:
  recent_chat  — this conversation / last few turns (already in context window)
  chat_log     — exact old wording, previous commands, what was said in past sessions, debugging history
  qdrant       — semantic memory: past decisions, project summaries, concepts, what JARVIS knows about you
  obsidian     — durable notes: project docs, plans, recipes, long-form personal notes
  files        — code or config files, source of truth for technical details
  tools        — live device/service state: needs a tool call, not a memory fetch

Set need_memory: false when:
  - You already know the answer from general knowledge
  - A direct tool call would answer it (set type "tools" — caller handles)
  - You genuinely do not understand the question
  - Simple command with no context dependency
  → memory_confidence: low

Set need_memory: true when:
  - You understand the question but would otherwise say "I don't have specific information on that"
  - References past events, conversations, prior commands, or history
  - About identity, project state, what was done/said previously
  - Requires personal or project-specific context JARVIS might have stored
  → memory_confidence: high
  → list every type that could plausibly contain a useful answer

Respond ONLY with valid JSON, no explanation, no markdown:
{
  "need_memory": true,
  "memory_confidence": "high",
  "reasoning": "one sentence",
  "memory_types": [
    {"type": "qdrant", "reason": "past project decisions may be stored"},
    {"type": "obsidian", "reason": "user may have written project notes"}
  ]
}

If need_memory is false, memory_types must be [].
"""

def classify(user_input: str, recent_turns: list[str] | None = None) -> dict:
    context = ""
    if recent_turns:
        context = "Recent conversation:\n" + "\n".join(recent_turns[-4:]) + "\n\n"
    result = _llama(f"{context}User message: {user_input}", CLASSIFY_SYSTEM)
    parsed = _parse_json(result)
    if not parsed:
        return {"need_memory": False, "memory_confidence": "low",
                "reasoning": "parse error", "memory_types": []}
    return parsed

# ---------------------------------------------------------------------------
# Pass 2 — build fetch plan
# ---------------------------------------------------------------------------

BUILD_QUERY_SYSTEM = """You are a search query builder for a multi-source memory system.
Given a user message and list of memory types, output a fetch plan.

Respond ONLY with valid JSON. Only include keys for the requested types. Null = skip.
{
  "qdrant":      {"query": "semantic phrase for vector search", "top_k": 5},
  "chat_log":    {"query": "keywords or phrase to match in chat history"},
  "obsidian":    {"query": "keywords to search vault notes"},
  "files":       {"query": "filename or code pattern"},
  "recent_chat": null,
  "tools":       null
}

recent_chat and tools are never fetched — always null.
Keep queries short and semantic, not the user's raw phrasing.
"""

def build_fetch_plan(user_input: str, memory_types: list[dict]) -> dict:
    type_names = [m["type"] for m in memory_types]
    prompt = f"Memory types needed: {type_names}\nUser message: {user_input}"
    result = _llama(prompt, BUILD_QUERY_SYSTEM)
    parsed = _parse_json(result)
    return parsed or {t: {"query": user_input} for t in type_names}

# ---------------------------------------------------------------------------
# Pass 3 — fetchers
# ---------------------------------------------------------------------------

def fetch_qdrant(query: str, top_k: int = TOP_K) -> list[dict]:
    embedding = _embed(query)
    if not embedding:
        return []
    q = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    existing = [c.name for c in q.get_collections().collections]
    results = []
    for col in QDRANT_COLS:
        if col not in existing:
            continue
        try:
            # qdrant-client >=1.7 uses query_points; fallback to search for older
            try:
                from qdrant_client.models import Query
                hits = q.query_points(
                    collection_name=col,
                    query=embedding,
                    limit=top_k,
                    score_threshold=SCORE_MIN,
                    with_payload=True
                ).points
            except AttributeError:
                hits = q.search(
                    collection_name=col,
                    query_vector=embedding,
                    limit=top_k,
                    score_threshold=SCORE_MIN,
                    with_payload=True
                )
            for h in hits:
                results.append({
                    "type": "qdrant", "score": round(h.score, 3),
                    "source": h.payload.get("source", col),
                    "text": h.payload.get("text", ""),
                    "task": h.payload.get("task", ""),
                    "steps": h.payload.get("steps", []),
                })
        except Exception as e:
            print(f"[MEMORY] Qdrant error ({col}): {e}")
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def fetch_chat_log(query: str, max_results: int = 5) -> list[dict]:
    if not CHAT_LOG_PATH.exists():
        return []
    results = []
    terms = query.lower().split()
    try:
        for line in reversed(CHAT_LOG_PATH.read_text().splitlines()):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                content = entry.get("content", "").lower()
                if any(t in content for t in terms):
                    results.append({
                        "type": "chat_log", "score": 1.0,
                        "source": "chat_log.jsonl",
                        "text": entry.get("content", "")[:500],
                        "ts": entry.get("ts", "")
                    })
                    if len(results) >= max_results:
                        break
            except Exception:
                continue
    except Exception as e:
        print(f"[MEMORY] chat_log error: {e}")
    return results


def fetch_obsidian(query: str, max_results: int = 5) -> list[dict]:
    if not OBSIDIAN_DIR.exists():
        return []
    results = []
    terms = query.lower().split()
    try:
        for md in sorted(OBSIDIAN_DIR.rglob("*.md"),
                         key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                text = md.read_text(encoding="utf-8", errors="ignore")
                lines = text.splitlines()
                low   = [l.lower() for l in lines]
                if any(t in l for t in terms for l in low):
                    # return context window (5 lines before/after) around each match
                    snippets = []
                    seen = set()
                    for i, l in enumerate(low):
                        if any(t in l for t in terms):
                            start  = max(0, i - 5)
                            end    = min(len(lines), i + 6)
                            key    = (start, end)
                            if key not in seen:
                                seen.add(key)
                                snippets.append("\n".join(lines[start:end]))
                    results.append({
                        "type":   "obsidian", "score": 1.0,
                        "source": str(md.relative_to(OBSIDIAN_DIR)),
                        "text":   "\n---\n".join(snippets[:3])[:600]
                    })
                    if len(results) >= max_results:
                        break
            except Exception:
                continue
    except Exception as e:
        print(f"[MEMORY] Obsidian error: {e}")
    return results


def fetch_files(query: str, **_) -> list[dict]:
    # Signals to caller that a file search is needed — tool dispatcher handles actual grep
    return [{"type": "files", "score": 1.0, "source": "file_search",
             "text": f"File search needed: {query}"}]


FETCHERS = {
    "qdrant":      lambda plan: fetch_qdrant(plan["query"], plan.get("top_k", TOP_K)),
    "chat_log":    lambda plan: fetch_chat_log(plan["query"]),
    "obsidian":    lambda plan: fetch_obsidian(plan["query"]),
    "files":       lambda plan: fetch_files(plan["query"]),
    "recent_chat": lambda plan: [],   # already in context
    "tools":       lambda plan: [],   # caller handles tool dispatch
}

def fetch_all(fetch_plan: dict) -> list[dict]:
    results = []
    for mem_type, plan in fetch_plan.items():
        if not plan:
            continue
        fetcher = FETCHERS.get(mem_type)
        if not fetcher:
            continue
        try:
            results.extend(fetcher(plan))
        except Exception as e:
            print(f"[MEMORY] fetch error ({mem_type}): {e}")
    return results

# ---------------------------------------------------------------------------
# Pass 4 — summarize
# ---------------------------------------------------------------------------

SUMMARIZE_SYSTEM = """You are a memory summarizer for JARVIS, a local AI assistant.
Compress retrieved memory results into a clean context block for the main model.

Rules:
- Summarize ALL results — the retrieval system already filtered for relevance
- Only discard a result if it is pure noise with zero connection to the question
- Include dates, task names, decisions, steps — concrete details are valuable
- Under 300 words total
- Group by source type with a short label
- Plain text, no JSON
- Start with: RETRIEVED MEMORY:
- Only write "RETRIEVED MEMORY: none relevant" if every single result is completely unrelated noise
- Do not explain what you are doing or repeat the question
"""

def summarize_context(user_input: str, results: list[dict]) -> str:
    """
    Build context block directly from results — no LLM filtering.
    The main model decides relevance; our job is just to format cleanly.
    LLM summarization only kicks in if total raw text exceeds 1200 chars.
    """
    if not results:
        return "RETRIEVED MEMORY: none relevant"

    by_type: dict[str, list] = {}
    for r in results:
        by_type.setdefault(r["type"], []).append(r)

    blocks = []
    total_chars = 0
    for mem_type, items in by_type.items():
        block = f"[{mem_type.upper()}]\n"
        for item in items:
            entry = ""
            if item.get("source"):
                entry += f"source: {item['source']}"
            if item.get("score") and item["score"] != 1.0:
                entry += f" (score: {item['score']})"
            entry += "\n"
            if item.get("task"):
                entry += f"task: {item['task']}\n"
            if item.get("steps"):
                entry += "steps: " + " → ".join(item["steps"][:5]) + "\n"
            if item.get("text"):
                entry += item["text"][:400] + "\n"
            block += entry + "\n"
            total_chars += len(entry)
        blocks.append(block)

    raw_context = "RETRIEVED MEMORY:\n" + "\n---\n".join(blocks)

    # Only compress via LLM if too long for context window
    if total_chars > 1200:
        prompt = (
            f"User question: {user_input}\n\n"
            f"Memory results (compress to under 300 words, keep all dates/tasks/decisions):\n\n"
            + "\n---\n".join(blocks)
        )
        compressed = _llama(prompt, SUMMARIZE_SYSTEM, timeout=30)
        if compressed and len(compressed) > 20:
            if not compressed.startswith("RETRIEVED MEMORY"):
                compressed = f"RETRIEVED MEMORY:\n{compressed}"
            return compressed

    return raw_context

# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def route(user_input: str, recent_turns: list[str] | None = None) -> tuple[str, dict]:
    """
    Full memory routing pipeline.

    Args:
        user_input:   current user message
        recent_turns: last N turns as strings — helps pass 1 avoid false positives

    Returns:
        context_block (str)  — prepend to system prompt, empty string if not needed
        meta          (dict) — routing metadata for logging

    Usage:
        context, meta = route(user_input, recent_turns)
        system_prompt = (context + "\\n\\n" + base_prompt) if context else base_prompt
    """
    classification = classify(user_input, recent_turns)

    if not classification.get("need_memory", False):
        return "", {
            "routed":     False,
            "confidence": classification.get("memory_confidence"),
            "reasoning":  classification.get("reasoning"),
            "types":      []
        }

    memory_types = classification.get("memory_types", [])
    if not memory_types:
        return "", {"routed": False, "reasoning": "no types returned", "types": []}

    fetch_plan = build_fetch_plan(user_input, memory_types)
    results    = fetch_all(fetch_plan)
    context    = summarize_context(user_input, results)

    return context, {
        "routed":     True,
        "confidence": classification.get("memory_confidence"),
        "reasoning":  classification.get("reasoning"),
        "types":      [m["type"] for m in memory_types],
        "hits":       len(results),
        "top_score":  results[0]["score"] if results else 0,
        "fetch_plan": fetch_plan
    }

# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    test = " ".join(sys.argv[1:]) or "What did we work on yesterday?"
    print(f"\nInput: {test}\n{'='*60}")

    print("\n[PASS 1] Classify")
    c = classify(test)
    print(json.dumps(c, indent=2))

    if c.get("need_memory"):
        print("\n[PASS 2] Fetch plan")
        plan = build_fetch_plan(test, c["memory_types"])
        print(json.dumps(plan, indent=2))

        print("\n[PASS 3] Fetch")
        results = fetch_all(plan)
        print(f"  {len(results)} results")
        for r in results:
            print(f"  [{r['type']}] score={r.get('score','?')} {r.get('text','')[:80]}")

        print("\n[PASS 4] Summary")
        print(summarize_context(test, results))
    else:
        print(f"\nNo memory needed — {c.get('reasoning')}")