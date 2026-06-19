"""Parlor — on-device, real-time multimodal AI (voice + vision).
Backend: llama-server (llama.cpp) instead of LiteRT-LM.
"""

import asyncio
import base64
import json
import os
import re
import time
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

import tts

LLAMA_SERVER = os.environ.get("LLAMA_SERVER", "http://127.0.0.1:8081")
SYSTEM_PROMPT = (
    "You are a friendly, conversational AI assistant. The user is talking to you "
    "through a microphone and showing you their camera. "
    "First transcribe exactly what the user said, then write your response in 1-4 short sentences."
    "Reply in JSON: {\"transcription\": \"...\", \"response\": \"...\"}"
)

SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')

tts_backend = None


def call_llama(messages: list[dict]) -> str:
    payload = {
        "model": "gemma4",
        "messages": messages,
        "stream": False,
        "temperature": 1.0,
        "top_k": 64,
        "top_p": 0.95,
    }
    req = urllib.request.Request(
        f"{LLAMA_SERVER}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


def load_models():
    global tts_backend
    print(f"Checking llama-server at {LLAMA_SERVER}...")
    try:
        with urllib.request.urlopen(f"{LLAMA_SERVER}/health", timeout=5) as r:
            print(f"llama-server ready: {r.read().decode()}")
    except Exception as e:
        print(f"WARNING: llama-server not reachable: {e}")
    tts_backend = tts.load()
    print("TTS loaded.")


@asynccontextmanager
async def lifespan(app):
    await asyncio.get_event_loop().run_in_executor(None, load_models)
    yield


app = FastAPI(lifespan=lifespan)


def split_sentences(text: str) -> list[str]:
    parts = SENTENCE_SPLIT_RE.split(text.strip())
    return [s.strip() for s in parts if s.strip()]


def parse_llm_response(raw: str) -> tuple[str, str]:
    """Extract transcription and response from JSON or plain text."""
    raw = raw.strip()
    # strip thinking tags
    if "<think>" in raw:
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    try:
        # strip markdown fences
        clean = re.sub(r"```json|```", "", raw).strip()
        data = json.loads(clean)
        return data.get("transcription", ""), data.get("response", raw)
    except Exception:
        return "", raw


@app.get("/")
async def root():
    return HTMLResponse(content=(Path(__file__).parent / "index.html").read_text())


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    async def heartbeat():
        try:
            while True:
                await asyncio.sleep(20)

                # lightweight keepalive
                await ws.send_text(json.dumps({
                    "type": "ping",
                    "ts": time.time()
                }))
        except Exception:
            pass

    heartbeat_task = asyncio.create_task(heartbeat())

    try:
        ...
    finally:
        heartbeat_task.cancel()

    conversation: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    interrupted = asyncio.Event()
    msg_queue = asyncio.Queue()

    async def receiver():
        try:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                if msg.get("type") == "interrupt":
                    interrupted.set()
                    print("Client interrupted")
                else:
                    await msg_queue.put(msg)
        except WebSocketDisconnect:
            await msg_queue.put(None)

    recv_task = asyncio.create_task(receiver())

    try:
        while True:
            msg = await msg_queue.get()
            if msg is None:
                break

            interrupted.clear()

            # Build content blocks for llama-server
            content = []

            if msg.get("audio"):
                content.append({
                    "type": "input_audio",
                    "input_audio": {
                        "data": msg["audio"],  # already base64
                        "format": "wav",
                    }
                })

            if msg.get("image"):
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{msg['image']}"
                    }
                })

            if msg.get("audio") and msg.get("image"):
                content.append({"type": "text", "text": "The user just spoke to you (audio) while showing their camera (image). Respond to what they said, referencing what you see if relevant."})
            elif msg.get("audio"):
                content.append({"type": "text", "text": "The user just spoke to you. Respond to what they said."})
            elif msg.get("image"):
                content.append({"type": "text", "text": "The user is showing you their camera. Describe what you see."})
            else:
                content.append({"type": "text", "text": msg.get("text", "Hello!")})

            conversation.append({"role": "user", "content": content})

            # LLM inference
            t0 = time.time()
            try:
                raw_response = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: call_llama(conversation)
                )
            except Exception as e:
                print(f"LLM error: {e}")
                await ws.send_text(json.dumps({"type": "error", "message": str(e)}))
                conversation.pop()  # remove failed user message
                continue

            llm_time = time.time() - t0

            transcription, text_response = parse_llm_response(raw_response)
            print(f"LLM ({llm_time:.2f}s) heard: {transcription!r} → {text_response}")

            # Add assistant turn to conversation history
            conversation.append({"role": "assistant", "content": raw_response})

            # Keep conversation from growing unbounded
            if len(conversation) > 20:
                conversation = conversation[:1] + conversation[-18:]

            if interrupted.is_set():
                print("Interrupted after LLM, skipping response")
                continue

            reply = {
                "type": "text",
                "text": text_response,
                "llm_time": round(llm_time, 2),
            }
            if transcription:
                reply["transcription"] = transcription
            await ws.send_text(json.dumps(reply))

            if interrupted.is_set():
                print("Interrupted before TTS, skipping audio")
                continue

            # Streaming TTS
            sentences = split_sentences(text_response) or [text_response]
            tts_start = time.time()

            await ws.send_text(json.dumps({
                "type": "audio_start",
                "sample_rate": tts_backend.sample_rate,
                "sentence_count": len(sentences),
            }))

            for i, sentence in enumerate(sentences):
                if interrupted.is_set():
                    print(f"Interrupted during TTS sentence {i+1}/{len(sentences)}")
                    break

                pcm = await asyncio.get_event_loop().run_in_executor(
                    None, lambda s=sentence: tts_backend.generate(s)
                )

                if interrupted.is_set():
                    break

                pcm_int16 = (pcm * 32767).clip(-32768, 32767).astype(np.int16)
                await ws.send_text(json.dumps({
                    "type": "audio_chunk",
                    "audio": base64.b64encode(pcm_int16.tobytes()).decode(),
                    "index": i,
                }))

            tts_time = time.time() - tts_start
            print(f"TTS ({tts_time:.2f}s): {len(sentences)} sentences")

            if not interrupted.is_set():
                await ws.send_text(json.dumps({
                    "type": "audio_end",
                    "tts_time": round(tts_time, 2),
                }))

    except WebSocketDisconnect:
        print("Client disconnected")
    finally:
        recv_task.cancel()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)