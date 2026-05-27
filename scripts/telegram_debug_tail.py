#!/usr/bin/env python3
# telegram_debug_tail.py

import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# --------------------------------------------------
# ENV
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)

BOT_TOKEN = os.getenv("JARVIS_DEBUG_TELEGRAM_BOT_TOKEN", "").strip()

ALLOWED_CHATS = {
    x.strip()
    for x in os.getenv("JARVIS_DEBUG_TELEGRAM_ALLOWED_CHATS", "").split(",")
    if x.strip()
}

EVENT_FILE = os.getenv(
    "JARVIS_EVENT_FILE",
    "/tmp/jarvis/react_events.jsonl"
)

POLL_INTERVAL = float(
    os.getenv("JARVIS_DEBUG_TAIL_INTERVAL", "0.25")
)

MAX_MESSAGE_LEN = int(
    os.getenv("JARVIS_DEBUG_MAX_LEN", "3500")
)

# --------------------------------------------------
# FILTERS
# --------------------------------------------------

IMPORTANT_TYPES = {
    "router",
    "tool",
    "error",
    "timing",
    "planner",
    "runtime",
}

IGNORE_MESSAGES = {
    "tts_chunk",
}

# --------------------------------------------------
# TELEGRAM
# --------------------------------------------------

def send_telegram(chat_id: str, text: str):
    if not BOT_TOKEN:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    parts = [
        text[i:i + MAX_MESSAGE_LEN]
        for i in range(0, len(text), MAX_MESSAGE_LEN)
    ]

    total = len(parts)

    for idx, part in enumerate(parts, start=1):

        prefix = ""
        if total > 1:
            prefix = f"[{idx}/{total}]\n"

        try:
            requests.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": prefix + part,
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
        except Exception as e:
            print(f"[telegram] send failed: {e}")
# --------------------------------------------------
# CHAT ID DISCOVERY
# --------------------------------------------------

def telegram_get_updates(offset: int | None = None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

    params = {
        "timeout": 30,
        "allowed_updates": json.dumps(["message"]),
    }

    if offset is not None:
        params["offset"] = offset

    try:
        r = requests.get(url, params=params, timeout=35)
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception as e:
        print(f"[telegram] getUpdates failed: {e}", flush=True)
        return []


def discover_chat_ids():
    print("[debug_tail] discovery mode active", flush=True)
    print("[debug_tail] send any message to the debug bot", flush=True)

    offset = None

    while True:
        updates = telegram_get_updates(offset)

        for update in updates:
            offset = update["update_id"] + 1

            msg = update.get("message") or {}
            chat = msg.get("chat") or {}
            user = msg.get("from") or {}

            chat_id = str(chat.get("id", ""))
            chat_type = chat.get("type", "")
            title = chat.get("title") or chat.get("username") or ""
            username = user.get("username", "")
            first_name = user.get("first_name", "")

            text = (
                "🔎 JARVIS DEBUG BOT CHAT ID\n"
                f"chat_id: {chat_id}\n"
                f"chat_type: {chat_type}\n"
                f"title/user: {title}\n"
                f"from: {first_name} @{username}\n\n"
                "Add this to .env:\n"
                f"JARVIS_DEBUG_TELEGRAM_ALLOWED_CHATS={chat_id}"
            )

            print(text, flush=True)

            if chat_id:
                send_telegram(chat_id, text)

        time.sleep(1)
# --------------------------------------------------
# EVENT FORMAT
# --------------------------------------------------

def format_event(event: dict) -> str:

    typ = event.get("type", "?")
    msg = event.get("message", "")

    data = event.get("data", {})

    data_text = json.dumps(
        data,
        indent=2,
        ensure_ascii=False
    )

    return (
        f"🔧 JARVIS EVENT\n"
        f"type: {typ}\n"
        f"time: {event.get('time', '')}\n"
        f"message: {msg}\n\n"
        f"{data_text}"
    )

# --------------------------------------------------
# FILTER
# --------------------------------------------------

def should_send(event: dict) -> bool:

    typ = event.get("type", "")

    if typ not in IMPORTANT_TYPES:
        return False

    msg = str(event.get("message", "")).lower()

    if msg in IGNORE_MESSAGES:
        return False

    return True

# --------------------------------------------------
# FOLLOW FILE
# --------------------------------------------------

def follow_file(path: str):

    print(f"[debug_tail] waiting for file: {path}")

    while not os.path.exists(path):
        time.sleep(1)

    print(f"[debug_tail] following: {path}")

    with open(path, "r", encoding="utf-8") as f:

        f.seek(0, os.SEEK_END)

        while True:

            line = f.readline()

            if not line:
                time.sleep(POLL_INTERVAL)
                continue

            line = line.strip()

            if not line:
                continue

            try:
                event = json.loads(line)
            except Exception:
                continue

            if not should_send(event):
                continue

            text = format_event(event)

            for chat_id in ALLOWED_CHATS:
                send_telegram(chat_id, text)

# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():

    if not BOT_TOKEN:
        print("[debug_tail] missing token", flush=True)
        return

    if not ALLOWED_CHATS:
        discover_chat_ids()
        return

    follow_file(EVENT_FILE)

# --------------------------------------------------

if __name__ == "__main__":
    while True:
        try:
            main()
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[debug_tail] crashed: {e}")
            time.sleep(2)