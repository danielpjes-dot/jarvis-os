from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


DEFAULT_VAULT = Path("/mnt/d/Jarvis_vault")


def vault_root() -> Path:
    return Path(os.environ.get("JARVIS_VAULT", DEFAULT_VAULT))


def chat_dir() -> Path:
    return vault_root() / ".jarvis" / "chat"


def today_chat_file() -> Path:
    return chat_dir() / time.strftime("%Y-%m-%d.jsonl")


def read_last_chat_chars(max_chars: int = 4000) -> str:
    path = today_chat_file()

    if not path.exists():
        return "No chat log found for today."

    text = path.read_text(encoding="utf-8", errors="ignore").strip()

    if not text:
        return "Today’s chat log is empty."

    return text[-max_chars:]


def read_last_chat_messages(limit: int = 20) -> str:
    path = today_chat_file()

    if not path.exists():
        return "No chat log found for today."

    rows: list[dict[str, Any]] = []

    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue

    if not rows:
        return "Today’s chat log is empty."

    out = []

    for row in rows[-limit:]:
        role = row.get("role", "unknown")
        route = row.get("route") or "-"
        t = row.get("time") or ""
        content = str(row.get("content", "")).strip().replace("\n", " ")

        if len(content) > 500:
            content = content[:500] + "..."

        out.append(f"{t} {role.upper()}[{route}]: {content}")

    return "\n".join(out)


def summarize_chat_log(limit: int = 30) -> str:
    messages = read_last_chat_messages(limit=limit)

    return (
        "Recent chat log:\n\n"
        f"{messages}\n\n"
        "Use this to answer what we recently discussed."
    )


def run(action: str = "recent", limit: int = 20, max_chars: int = 4000, **kwargs: Any) -> str:
    if action in ("raw", "chars"):
        return read_last_chat_chars(max_chars=max_chars)

    if action in ("recent", "messages", "last"):
        return read_last_chat_messages(limit=limit)

    if action in ("summary", "summarize"):
        return summarize_chat_log(limit=limit)

    return f"Unknown chat_log action: {action}"

def chat_log(action: str = "recent", limit: int = 20, max_chars: int = 4000, **kwargs):
    return run(action=action, limit=limit, max_chars=max_chars, **kwargs)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "chat_log",
            "description": "Read recent Jarvis chat log/history. Use when user asks what we chatted, what was said earlier, last messages, or recent conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "recent, raw, or summary",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of recent messages for action=recent or summary",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters for action=raw",
                    },
                },
                "required": ["action"],
            },
        },
    },
]


TOOL_MAP = {
    "chat_log": chat_log,
}


KEYWORDS = {
    "chat_log": [
        "chat log",
        "chat history",
        "recent chat",
        "last messages",
        "what did we chat",
        "what have we chatted",
        "what did i say",
        "what did you say",
        "conversation history",
    ],
}


SKILL_META = {
    "intent_aliases": [
        "chat history",
        "recent chat",
        "what did we chat",
        "what have we chatted",
        "conversation history",
    ],
    "keywords": KEYWORDS["chat_log"],
    "route": "live",
    "tools": {
        "chat_log": {
            "intent_aliases": [
                "chat history",
                "recent chat",
                "what did we chat",
                "what have we chatted",
            ],
            "keywords": KEYWORDS["chat_log"],
            "direct_match": [
                "what did we chat",
                "what have we chatted",
                "show chat log",
                "show recent chat",
                "last messages",
            ],
            "route": "live",
        }
    },
}