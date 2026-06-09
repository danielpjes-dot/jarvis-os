from __future__ import annotations

import asyncio
import ast
import base64
import json
import os
import subprocess
import sys
import traceback
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
HF_TOKEN = os.environ.get("HUGGINGFACEHUB_API_TOKEN", "") == ""
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.kokoro import health_check_text, kokoro_stream

PORT = int(os.environ.get("KOKORO_PORT", "5100"))
DEFAULT_VOICE = os.environ.get("KOKORO_VOICE", "af_heart")


VALID_VOICES = {
    "af_heart",
    "af_bella",
    "af_nicole",
    "af_sarah",
    "af_sky",
    "am_adam",
    "am_michael",
    "bf_emma",
    "bf_isabella",
    "bm_george",
    "bm_lewis",
}



def play_with_mpv_ipc(wav_path: str) -> None:
    win_wav_path = subprocess.check_output(
        ["wslpath", "-w", wav_path],
        text=True,
    ).strip()

    cmd = {
        "command": [
            "loadfile",
            win_wav_path,
            "replace",
        ]
    }

    ps = f"""
$ErrorActionPreference = 'Stop'
$pipe = New-Object System.IO.Pipes.NamedPipeClientStream('.', 'jarvis-mpv', [System.IO.Pipes.PipeDirection]::Out)
$pipe.Connect(3000)
$writer = New-Object System.IO.StreamWriter($pipe)
$writer.AutoFlush = $true
$writer.WriteLine('{json.dumps(cmd)}')
$writer.Dispose()
$pipe.Dispose()
"""

    subprocess.run(
        [
            "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
            "-NoProfile",
            "-Command",
            ps,
        ],
        check=True,
    )

class KokoroHandler(BaseHTTPRequestHandler):
    server_version = "JarvisKokoro/1.0"

    def _json_response(self, payload: dict, code: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")

        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}

        raw = self.rfile.read(length).decode("utf-8", errors="ignore")
        if not raw.strip():
            return {}

        return json.loads(raw)
    
   
    def _normalize_chunk(self, chunk) -> dict | None:
        if isinstance(chunk, dict):
            audio = chunk.get("audio")
            if not audio:
                return None

            return {
                "audio": str(audio),
                "sample_rate": int(chunk.get("sample_rate", 24000)),
            }

        if isinstance(chunk, bytes):
            return {
                "audio": base64.b64encode(chunk).decode("ascii"),
                "sample_rate": 24000,
            }

        if isinstance(chunk, str):
            text = chunk.strip()

            # Fix case where kokoro_stream returns stringified Python dict:
            # "{'audio': '...', 'sample_rate': 24000}"
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, dict):
                    return self._normalize_chunk(parsed)
            except Exception:
                pass

            # Fallback: assume the string itself is base64 audio
            if text:
                return {
                    "audio": text,
                    "sample_rate": 24000,
                }

        return None

    def _collect_chunks(self, text: str, voice: str) -> list[dict]:
        chunks: list[dict] = []

        async def _run() -> None:
            async for chunk in kokoro_stream(text, voice=voice):
                normalized = self._normalize_chunk(chunk)
                if normalized:
                    chunks.append(normalized)

        asyncio.run(_run())
        return chunks

    def _chunks_to_pcm(self, chunks: list[dict]) -> bytes:
        pcm_parts: list[bytes] = []

        for chunk in chunks:
            audio = chunk.get("audio")
            if not audio:
                continue

            try:
                pcm_parts.append(base64.b64decode(audio))
            except Exception:
                continue

        return b"".join(pcm_parts)

    def do_GET(self) -> None:
        path = urlparse(self.path).path

        if path in {"/health", "/tts/health"}:
            try:
                self._json_response(
                    health_check_text(
                        "Hello Jarvis.",
                        voice=DEFAULT_VOICE,
                    )
                )
            except Exception as e:
                self._json_response(
                    {
                        "status": "error",
                        "error": str(e),
                        "traceback": traceback.format_exc(limit=5),
                    },
                    code=500,
                )
            return

        if path in {"/test", "/tts/test"}:
            self._handle_tts_test(play=False)
            return

        if path in {"/play-test", "/tts/play-test"}:
            self._handle_tts_test(play=True)
            return

        self._json_response(
            {
                "status": "error",
                "error": "not_found",
                "path": path,
            },
            code=404,
        )

    def do_POST(self) -> None:
        path = urlparse(self.path).path

        if path in {"/speak", "/tts/speak"}:
            self._handle_speak()
            return

        self._json_response(
            {
                "status": "error",
                "error": "not_found",
                "path": path,
            },
            code=404,
        )

    def _handle_speak(self) -> None:
        try:
            body = self._read_json()
           
            text = str(body.get("text") or "").strip()
            voice = str(body.get("voice") or DEFAULT_VOICE).strip()
            if voice not in VALID_VOICES:
                print(
                    f"[KOKORO] Unknown voice '{voice}', using bm_george",
                    flush=True,
                )
                voice = "bm_george"
            if not text:
                self._json_response(
                    {
                        "status": "error",
                        "error": "missing text",
                    },
                    code=400,
                )
                return

            chunks = self._collect_chunks(text, voice)

            if not chunks:
                self._json_response(
                    {
                        "status": "error",
                        "error": "No audio chunks generated",
                    },
                    code=500,
                )
                return

            sample_rate = int(chunks[0].get("sample_rate", 24000))
            pcm_bytes = self._chunks_to_pcm(chunks)
            played = False
            wav_path = None

            if body.get("play"):
                wav_path = "/tmp/jarvis_tts_speak.wav"

                with wave.open(wav_path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(pcm_bytes)

                #play_with_mpv_ipc(wav_path)
                played = True

            self._json_response(
                {
                    "status": "ok",
                    "text": text,
                    "voice": voice,
                    "chunks": chunks,
                    "total_chunks": len(chunks),
                    "sample_rate": sample_rate,
                    "format": "int16_pcm_base64",
                    "total_bytes": len(pcm_bytes),
                    "played": played,
                    "wav_path": wav_path,
                }
            )

        except Exception as e:
            self._json_response(
                {
                    "status": "error",
                    "error": str(e),
                    "traceback": traceback.format_exc(limit=10),
                },
                code=500,
            )

    def _handle_tts_test(self, play: bool = False) -> None:
        try:
            text = "Systems online. JARVIS is ready."
            voice = DEFAULT_VOICE

            chunks = self._collect_chunks(text, voice)

            if not chunks:
                self._json_response(
                    {
                        "status": "error",
                        "error": "No audio chunks generated",
                    },
                    code=500,
                )
                return

            sample_rate = int(chunks[0].get("sample_rate", 24000))
            pcm_bytes = self._chunks_to_pcm(chunks)

            response = {
                "status": "ok",
                "text": text,
                "voice": voice,
                "chunks": len(chunks),
                "sample_rate": sample_rate,
                "format": "int16_pcm_base64",
                "total_bytes": len(pcm_bytes),
                "preview_chunk": chunks[0].get("audio", "")[:200] + "...",
            }

            if play:
                wav_path = "/tmp/jarvis_tts_test.wav"

                with wave.open(wav_path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(pcm_bytes)

                
                play_with_mpv_ipc(wav_path)

                response["played"] = True
                response["wav_path"] = wav_path

            self._json_response(response)

        except Exception as e:
            self._json_response(
                {
                    "status": "error",
                    "error": str(e),
                    "traceback": traceback.format_exc(limit=10),
                },
                code=500,
            )

    def log_message(self, fmt: str, *args) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), KokoroHandler)

    print(f"[KOKORO] server: http://127.0.0.1:{PORT}")
    print(f"[KOKORO] voice: {DEFAULT_VOICE}")
    print("[KOKORO] endpoints:")
    print("  GET  /tts/health")
    print("  GET  /tts/test")
    print("  GET  /tts/play-test")
    print("  POST /tts/speak")
    print("[KOKORO] READY")

    server.serve_forever()