from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.dictation_service import DictationService  # noqa: E402


HOST = os.environ.get("JARVIS_DICTATION_HOST", "127.0.0.1")
PORT = int(os.environ.get("JARVIS_DICTATION_PORT", "5110"))

VAULT_DIR = Path(
    os.environ.get(
        "JARVIS_VAULT_DIR",
        "D:/Jarvis_vault" if os.name == "nt" else "/mnt/d/Jarvis_vault",
    )
)

SERVICE = DictationService(VAULT_DIR)


class DictationHandler(BaseHTTPRequestHandler):
    server_version = "JarvisDictation/1.0"

    def do_GET(self) -> None:
        path = urlparse(self.path).path

        if path == "/health":
            self._json({"ok": True, "service": "dictation_daemon"})
            return

        if path == "/status":
            self._json(SERVICE.status())
            return

        if path == "/read_last":
            self._json(SERVICE.read_last())
            return

        self.send_error(404)

    def do_POST(self) -> None:
        try:
            self._do_POST()
        except Exception as e:
            self._json(
                {
                    "ok": False,
                    "error": str(e),
                    "traceback": traceback.format_exc(limit=5),
                },
                code=500,
            )

    def _do_POST(self) -> None:
        path = urlparse(self.path).path
        body = self._read_json()

        if path == "/start":
            title = body.get("title") or "Dictation"
            self._json(SERVICE.start(title=title))
            return

        if path == "/stop":
            self._json(SERVICE.stop())
            return

        if path == "/search":
            query = body.get("query") or ""
            limit = int(body.get("limit") or 5)
            self._json(SERVICE.search(query=query, limit=limit))
            return

        self.send_error(404)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}

        raw = self.rfile.read(length).decode("utf-8")
        if not raw.strip():
            return {}

        return json.loads(raw)

    def _json(self, data: dict, code: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args) -> None:
        print("[DICTATION]", fmt % args, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), DictationHandler)

    print(f"[DICTATION] daemon running on http://{args.host}:{args.port}", flush=True)
    print(f"[DICTATION] vault: {VAULT_DIR}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[DICTATION] stopped", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()