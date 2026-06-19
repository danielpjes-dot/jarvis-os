from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import threading
import time
from typing import AsyncIterator, Dict, Any

import numpy as np

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

DEFAULT_VOICE = os.environ.get("KOKORO_VOICE", "af_heart")
DEFAULT_SPEED = float(os.environ.get("KOKORO_SPEED", "1.0"))
DEFAULT_LANG = os.environ.get("KOKORO_LANG", "en-us")


_kokoro_instance = None
_kokoro_lock = threading.Lock()


def split_sentences(text: str) -> list[str]:
    parts = SENTENCE_SPLIT_RE.split((text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def sanitize_for_tts(text: str) -> str:
    text = str(text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def get_kokoro():
    global _kokoro_instance

    if _kokoro_instance is not None:
        return _kokoro_instance

    with _kokoro_lock:
        if _kokoro_instance is not None:
            return _kokoro_instance

        from kokoro_onnx import Kokoro
        from huggingface_hub import hf_hub_download

        model_path = os.environ.get("KOKORO_MODEL_PATH")
        voices_path = os.environ.get("KOKORO_VOICES_PATH")

        if not model_path:
            model_path = hf_hub_download(
                "fastrtc/kokoro-onnx",
                "kokoro-v1.0.onnx",
            )

        if not voices_path:
            voices_path = hf_hub_download(
                "fastrtc/kokoro-onnx",
                "voices-v1.0.bin",
            )

        _kokoro_instance = Kokoro(model_path, voices_path)
        return _kokoro_instance


def generate_sentence_chunk(
    sentence: str,
    voice: str = DEFAULT_VOICE,
    speed: float = DEFAULT_SPEED,
    lang: str = DEFAULT_LANG,
) -> Dict[str, Any]:
    kokoro = get_kokoro()

    pcm, sample_rate = kokoro.create(
        sentence,
        voice=voice,
        speed=speed,
        lang=lang,
    )

    pcm_int16 = (
        np.array(pcm, dtype=np.float32)
        * 32767
    ).clip(-32768, 32767).astype(np.int16)

    return {
        "audio": base64.b64encode(pcm_int16.tobytes()).decode("utf-8"),
        "sample_rate": int(sample_rate or 24000),
        "format": "int16_pcm_base64",
        "backend": "kokoro_onnx",
        "voice": voice,
    }


async def kokoro_stream(
    text: str,
    voice: str = DEFAULT_VOICE,
    speed: float = DEFAULT_SPEED,
    lang: str = DEFAULT_LANG,
) -> AsyncIterator[Dict[str, Any]]:
    text = sanitize_for_tts(text)
    if not text:
        return

    sentences = split_sentences(text) or [text]
    loop = asyncio.get_event_loop()

    for sentence in sentences:
        chunk = await loop.run_in_executor(
            None,
            lambda s=sentence: generate_sentence_chunk(
                s,
                voice=voice,
                speed=speed,
                lang=lang,
            ),
        )
        yield chunk


async def send_tts_to_ws(
    ws,
    text: str,
    voice: str = DEFAULT_VOICE,
    speed: float = DEFAULT_SPEED,
    lang: str = DEFAULT_LANG,
    interrupted=None,
) -> Dict[str, Any]:
    text = sanitize_for_tts(text)
    sentences = split_sentences(text) or [text]

    tts_start = time.time()
    sent_chunks = 0
    sample_rate = 24000

    await ws.send_json({
        "type": "audio_start",
        "sample_rate": sample_rate,
        "sentence_count": len(sentences),
        "voice": voice,
        "backend": "kokoro_onnx",
    })

    async for chunk in kokoro_stream(
        text,
        voice=voice,
        speed=speed,
        lang=lang,
    ):
        if interrupted is not None and interrupted.is_set():
            break

        sample_rate = int(chunk.get("sample_rate", sample_rate))

        await ws.send_json({
            "type": "audio_chunk",
            "audio": chunk["audio"],
            "sample_rate": sample_rate,
            "format": chunk.get("format", "int16_pcm_base64"),
            "backend": chunk.get("backend", "kokoro_onnx"),
            "voice": voice,
            "index": sent_chunks,
        })

        sent_chunks += 1

    tts_time = round(time.time() - tts_start, 2)

    if interrupted is None or not interrupted.is_set():
        await ws.send_json({
            "type": "audio_end",
            "tts_time": tts_time,
            "chunks": sent_chunks,
        })

    return {
        "chunks": sent_chunks,
        "sample_rate": sample_rate,
        "tts_time": tts_time,
    }


async def send_tts_to_raw_ws(
    wfile,
    ws_send_json_func,
    text: str,
    voice: str = DEFAULT_VOICE,
    speed: float = DEFAULT_SPEED,
    lang: str = DEFAULT_LANG,
    interrupted=None,
) -> Dict[str, Any]:
    text = sanitize_for_tts(text)
    sentences = split_sentences(text) or [text]

    tts_start = time.time()
    sent_chunks = 0
    sample_rate = 24000

    ws_send_json_func(wfile, {
        "type": "audio_start",
        "sample_rate": sample_rate,
        "sentence_count": len(sentences),
        "voice": voice,
        "backend": "kokoro_onnx",
    })

    async for chunk in kokoro_stream(
        text,
        voice=voice,
        speed=speed,
        lang=lang,
    ):
        if interrupted is not None and interrupted.is_set():
            break

        sample_rate = int(chunk.get("sample_rate", sample_rate))

        ws_send_json_func(wfile, {
            "type": "audio_chunk",
            "audio": chunk["audio"],
            "sample_rate": sample_rate,
            "format": chunk.get("format", "int16_pcm_base64"),
            "backend": chunk.get("backend", "kokoro_onnx"),
            "voice": voice,
            "index": sent_chunks,
        })

        sent_chunks += 1

    tts_time = round(time.time() - tts_start, 2)

    if interrupted is None or not interrupted.is_set():
        ws_send_json_func(wfile, {
            "type": "audio_end",
            "tts_time": tts_time,
            "chunks": sent_chunks,
        })

    return {
        "chunks": sent_chunks,
        "sample_rate": sample_rate,
        "tts_time": tts_time,
    }


def health_check_text(text: str = "Hello Jarvis.", voice: str = DEFAULT_VOICE) -> dict:
    async def _run():
        chunks = []
        async for chunk in kokoro_stream(text, voice=voice):
            chunks.append(chunk)

        return {
            "status": "ok" if chunks else "error",
            "chunks": len(chunks),
            "total_audio_base64_chars": sum(len(c.get("audio", "")) for c in chunks),
            "sample_rates": sorted({c.get("sample_rate") for c in chunks}),
            "backend": chunks[0].get("backend") if chunks else "none",
            "voice": voice,
            "note": "Health only generates audio. Playback happens in browser websocket client.",
        }

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()