from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.telegram_gateway import TelegramGateway  # noqa: E402


VAULT_DIR = Path(
    os.environ.get(
        "JARVIS_VAULT_DIR",
        "D:/Jarvis_vault" if os.name == "nt" else "/mnt/d/Jarvis_vault",
    )
)

REACT_SERVER = os.environ.get("JARVIS_REACT_SERVER", "http://127.0.0.1:7900")


def call_jarvis_chat(text: str) -> str:
    payload = {
        "source": "telegram",
        "messages": [
            {
                "role": "user",
                "content": text,
            }
        ],
        "stream": False,
    }

    req = urllib.request.Request(
        f"{REACT_SERVER}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    return data.get("message", {}).get("content", "") or ""


def emit_event(event_type: str, message: str, data: dict | None = None) -> None:
    print(json.dumps({"type": event_type, "message": message, "data": data or {}}, ensure_ascii=False), flush=True)


def handle_message(text: str, update: dict) -> str:
    # Optional: make Telegram explicit to JARVIS.
    return call_jarvis_chat(f"{text}")


if __name__ == "__main__":
    gateway = TelegramGateway(VAULT_DIR)
    emit_event("telegram_start", "Telegram watcher started", {})
    gateway.poll_forever(handle_message=handle_message, emit_event=emit_event)