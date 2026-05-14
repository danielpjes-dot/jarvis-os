from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict


SKILL_NAME = "dictate"
SKILL_DESCRIPTION = "Control the dictation daemon: record microphone WAV, transcribe with Whisper, and index transcripts."

INTENT_ALIASES = [
    "dictate",
    "dictation",
    "start dictation",
    "stop dictation",
    "record note",
    "voice note",
    "transcribe",
]

KEYWORDS = [
    "dictate",
    "dictation",
    "record",
    "voice note",
    "transcribe",
    "wav",
    "microphone",
]

DIRECT_MATCH = [
    "start dictate",
    "start dictation",
    "stop dictate",
    "stop dictation",
    "read dictation",
    "search dictation",
]


DICTATION_HOST = os.environ.get("JARVIS_DICTATION_HOST", "http://127.0.0.1:5110").rstrip("/")


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "dictate",
            "description": "Start/stop microphone dictation, save WAV, transcribe, index, read, or search dictations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["start", "stop", "status", "read_last", "search"],
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional title for new dictation.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query for dictation transcripts.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum search results.",
                    },
                },
                "required": ["action"],
            },
        },
    }
]


def _get(path: str) -> Dict[str, Any]:
    url = f"{DICTATION_HOST}{path}"

    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {
            "ok": False,
            "speech": f"Dictation daemon unavailable: {type(e).__name__}: {e}",
            "error": str(e),
            "url": url,
        }


def _post(path: str, payload: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    url = f"{DICTATION_HOST}{path}"

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {
            "ok": False,
            "speech": f"Dictation daemon unavailable: {type(e).__name__}: {e}",
            "error": str(e),
            "url": url,
        }


def run(
    action: str,
    title: str = "Dictation",
    query: str = "",
    limit: int = 5,
) -> Dict[str, Any]:
    action = (action or "").strip().lower()

    if action == "start":
        return _post("/start", {"title": title or "Dictation"})

    if action == "stop":
        # stopping may transcribe, so allow longer timeout
        return _post("/stop", {}, timeout=900)

    if action == "status":
        return _get("/status")

    if action == "read_last":
        return _get("/read_last")

    if action == "search":
        return _post("/search", {"query": query, "limit": limit})

    return {
        "ok": False,
        "speech": f"Unknown dictate action: {action}",
    }