#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import soundfile as sf

# ─────────────────────────────────────────────
# TTS ENGINE (Coqui XTTS v2)
# ─────────────────────────────────────────────
from TTS.api import TTS

print("[ORPHEUS] Loading XTTS model...")

tts = TTS(
    model_name="tts_models/multilingual/multi-dataset/xtts_v2",
    progress_bar=False,
    gpu=False  # set True if you want GPU
)

print("[ORPHEUS] Ready")

# Optional: map your voices
VOICE_MAP = {
    "tara": "en",      # default
    "emma": "en",
    "daniel": "en",
}

# ─────────────────────────────────────────────
# Helper: generate WAV in memory
# ─────────────────────────────────────────────
def synthesize(text: str, voice: str = "tara") -> bytes:
    language = VOICE_MAP.get(voice, "en")

    wav = tts.tts(
        text=text,
        speaker_wav=None,   # can add reference voice later
        language=language,
    )

    wav = np.array(wav, dtype=np.float32)

    buf = io.BytesIO()
    sf.write(buf, wav, 22050, format="WAV")
    buf.seek(0)

    return buf.read()

# ─────────────────────────────────────────────
# HTTP Server
# ─────────────────────────────────────────────
class OrpheusHandler(BaseHTTPRequestHandler):

    def _json(self, data: dict, code: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json({"status": "ok"})
            return

        self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/speak":
            self._json({"error": "not found"}, 404)
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")

        try:
            data = json.loads(raw)
        except:
            self._json({"error": "invalid json"}, 400)
            return

        text = str(data.get("text", "")).strip()
        voice = str(data.get("voice", "tara"))

        if not text:
            self._json({"error": "empty text"}, 400)
            return

        try:
            wav_bytes = synthesize(text, voice)

            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav_bytes)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(wav_bytes)

        except Exception as e:
            self._json({"error": str(e)}, 500)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        return  # silence logs


# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("ORPHEUS_PORT", 5100))
    print(f"[ORPHEUS] Listening on http://127.0.0.1:{port}")

    server = ThreadingHTTPServer(("127.0.0.1", port), OrpheusHandler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[ORPHEUS] Stopped")