from __future__ import annotations
import threading
import json
import os
import time
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional


class TelegramGateway:
    def __init__(
        self,
        vault_dir: Path,
        token: Optional[str] = None,
        allowed_chat_ids: Optional[set[str]] = None,
    ):
        self.vault_dir = Path(vault_dir)
        self.token = token or os.environ.get("JARVIS_TELEGRAM_BOT_TOKEN", "")
        self.allowed_chat_ids = allowed_chat_ids or set(
            x.strip() for x in os.environ.get("JARVIS_TELEGRAM_ALLOWED_CHAT_IDS", "").split(",") if x.strip()
        )
        self.state_path = self.vault_dir / ".jarvis" / "telegram" / "state.json"
    def send_photo(self, chat_id: str | int, photo_path: str, caption: str = "") -> Dict[str, Any]:
        if not self.token:
            raise RuntimeError("Missing JARVIS_TELEGRAM_BOT_TOKEN")

        boundary = "----JarvisBoundary"
        path = Path(photo_path)

        if not path.exists():
            raise FileNotFoundError(str(path))

        body = bytearray()
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
        body.extend(str(chat_id).encode() + b"\r\n")

        if caption:
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
            body.extend(caption[:1000].encode("utf-8") + b"\r\n")

        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="photo"; filename="{path.name}"\r\n'.encode()
        )
        body.extend(b"Content-Type: image/png\r\n\r\n")
        body.extend(path.read_bytes())
        body.extend(f"\r\n--{boundary}--\r\n".encode())

        req = urllib.request.Request(
            self._api_url("sendPhoto"),
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        return data
    def send_message_with_buttons(
        self,
        chat_id: str | int,
        text: str,
        buttons: list[list[dict]],
    ) -> Dict[str, Any]:
        if not self.token:
            raise RuntimeError("Missing JARVIS_TELEGRAM_BOT_TOKEN")

        payload = urllib.parse.urlencode(
            {
                "chat_id": str(chat_id),
                "text": text[:3900],
                "reply_markup": json.dumps({"inline_keyboard": buttons}),
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            self._api_url("sendMessage"),
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {data}")

        return data
    def start_typing_loop(self, chat_id: str | int, stop_event: threading.Event, interval: float = 4.0) -> None:
        def _loop() -> None:
            while not stop_event.is_set():
                try:
                    self.send_chat_action(chat_id, "typing")
                except Exception:
                    pass
                stop_event.wait(interval)

        threading.Thread(target=_loop, daemon=True).start()
    def start_typing_stage(self, chat_id: str | int, stage_id: str, interval: float = 4.0) -> None:
        if not hasattr(self, "_typing_stages"):
            self._typing_stages = {}

        if stage_id in self._typing_stages:
            return

        stop_event = threading.Event()
        self._typing_stages[stage_id] = stop_event

        def _loop() -> None:
            while not stop_event.is_set():
                try:
                    self.send_chat_action(chat_id, "typing")
                except Exception:
                    pass
                stop_event.wait(interval)

        threading.Thread(target=_loop, daemon=True).start()


    def stop_typing_stage(self, stage_id: str) -> None:
        if not hasattr(self, "_typing_stages"):
            return

        stop_event = self._typing_stages.pop(stage_id, None)
        if stop_event:
            stop_event.set()
    def answer_callback_query(self, callback_query_id: str, text: str = "") -> Dict[str, Any]:
        if not self.token:
            raise RuntimeError("Missing JARVIS_TELEGRAM_BOT_TOKEN")

        payload = urllib.parse.urlencode(
            {
                "callback_query_id": callback_query_id,
                "text": text[:200],
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            self._api_url("answerCallbackQuery"),
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        return data

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {"offset": 0}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {"offset": 0}

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def get_updates(self, timeout: int = 30, limit: int = 10) -> list[dict]:
        if not self.token:
            raise RuntimeError("Missing JARVIS_TELEGRAM_BOT_TOKEN")

        state = self._load_state()
        params = {
            "offset": int(state.get("offset", 0)),
            "timeout": timeout,
            "limit": limit,
            "allowed_updates": json.dumps(["message", "callback_query"]),
        }

        url = self._api_url("getUpdates") + "?" + urllib.parse.urlencode(params)

        with urllib.request.urlopen(url, timeout=timeout + 10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not data.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {data}")

        updates = data.get("result", [])

        if updates:
            state["offset"] = max(int(u["update_id"]) for u in updates) + 1
            self._save_state(state)

        return updates
    def send_chat_action(self, chat_id: str | int, action: str = "typing") -> Dict[str, Any]:
        if not self.token:
            raise RuntimeError("Missing JARVIS_TELEGRAM_BOT_TOKEN")

        payload = urllib.parse.urlencode(
            {
                "chat_id": str(chat_id),
                "action": action,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            self._api_url("sendChatAction"),
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendChatAction failed: {data}")

        return data
    def send_message(self, chat_id: str | int, text: str) -> Dict[str, Any]:
        if not self.token:
            raise RuntimeError("Missing JARVIS_TELEGRAM_BOT_TOKEN")

        payload = urllib.parse.urlencode(
            {
                "chat_id": str(chat_id),
                "text": text[:3900],
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            self._api_url("sendMessage"),
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {data}")

        return data

    def is_allowed(self, chat_id: str | int) -> bool:
        if not self.allowed_chat_ids:
            return True
        return str(chat_id) in self.allowed_chat_ids
    
    def poll_forever(
        self,
        handle_message: Callable[[str, Dict[str, Any]], str],
        emit_event: Optional[Callable[[str, str, Optional[Dict[str, Any]]], None]] = None,
        sleep_on_error: int = 5,
    ) -> None:
        while True:
            try:
                updates = self.get_updates(timeout=30, limit=10)

                for update in updates:
                    callback = update.get("callback_query")

                    if callback:
                        callback_id = callback.get("id")
                        message = callback.get("message") or {}
                        chat = message.get("chat") or {}
                        chat_id = chat.get("id")
                        data = callback.get("data", "")

                        if callback_id:
                            self.answer_callback_query(callback_id, "Received")

                        if emit_event:
                            emit_event(
                                "telegram_callback",
                                "Telegram button pressed",
                                {"chat_id": chat_id, "data": data},
                            )

                        if chat_id and data:
                            reply = handle_message(data, update)
                            if reply:
                                self.send_message(chat_id, reply)

                        continue

                    message = update.get("message") or {}
                    chat = message.get("chat") or {}
                    chat_id = chat.get("id")
                    text = message.get("text", "")

                    print(f"[TELEGRAM] chat_id={chat_id} text={text!r}", flush=True)

                    if not chat_id or not text:
                        continue

                    if not self.is_allowed(chat_id):
                        self.send_message(chat_id, "This chat is not allowed to use this JARVIS bot.")
                        continue

                    if emit_event:
                        emit_event(
                            "telegram_in",
                            "Telegram message received",
                            {"chat_id": chat_id, "text": text[:500]},
                        )

                    reply = handle_message(text, update)

                    if not reply:
                        continue

                    lower = reply.lower()
                    plan_match = re.search(r"PLAN_ID:\s*([A-Za-z0-9_-]+)", reply)

                    if plan_match and "waiting_for:" in lower:
                        plan_id = plan_match.group(1)

                        self.send_message_with_buttons(
                            chat_id,
                            reply,
                            [
                                [
                                    {"text": "✅ Proceed", "callback_data": f"proceed {plan_id}"},
                                    {"text": "✏️ Modify", "callback_data": f"modify {plan_id}"},
                                ],
                                [
                                    {"text": "❌ Cancel", "callback_data": f"cancel {plan_id}"},
                                ],
                            ],
                        )
                    else:
                        self.send_message(chat_id, reply)

            except Exception as e:
                if emit_event:
                    emit_event("telegram_error", "Telegram polling error", {"error": str(e)})
                time.sleep(sleep_on_error)