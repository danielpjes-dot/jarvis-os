"""
chatterbox_skill.py — JARVIS OS TTS Skill
Drop-in replacement for Kokoro ONNX using Chatterbox Multilingual TTS
(resemble-ai/chatterbox, downloadable weights, RTX 3090 inference)

Install:
    pip install chatterbox-tts sounddevice soundfile numpy

Model weights auto-download on first run to ~/.cache/chatterbox/
For voice cloning: provide a 5-30s WAV reference at VOICE_REFERENCE_PATH
"""

import os
import io
import logging
import hashlib
import asyncio
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf


SKILL_NAME = "chatterbox_tts"
SKILL_DESCRIPTION = "Speak text aloud using Chatterbox Multilingual TTS on the JARVIS server (RTX 3090)"
SKILL_VERSION = "1.0.0"
SKILL_AUTHOR = "Sami Porokka"
SKILL_CATEGORY = "tts"
SKILL_TAGS = ["tts", "speak", "voice", "speech", "audio"]
SKILL_REQUIREMENTS = ["chatterbox-tts", "sounddevice", "soundfile", "numpy"]

SKILL_META = {
    "name": SKILL_NAME,
    "description": SKILL_DESCRIPTION,
    "version": SKILL_VERSION,
    "author": SKILL_AUTHOR,
    "category": SKILL_CATEGORY,
    "tags": SKILL_TAGS,
    "requirements": SKILL_REQUIREMENTS,
    "writes_files": False,
    "reads_files": False,
    "network_access": False,
    "entrypoint": "exec_chatterbox_tts",
}

logger = logging.getLogger("jarvis.chatterbox")

# ── Config ────────────────────────────────────────────────────────────────────
DEVICE          = os.getenv("TTS_DEVICE", "cuda")          # "cuda" | "cpu"
LANGUAGE        = os.getenv("TTS_LANGUAGE", "en")          # "en" | "et" | "fi" | etc.
VOICE_REF_PATH  = os.getenv("TTS_VOICE_REF", "")          # Path to .wav for voice clone
EXAGGERATION    = float(os.getenv("TTS_EXAGGERATION", "0.5"))   # 0.0–1.0 expressiveness
CFG_WEIGHT      = float(os.getenv("TTS_CFG_WEIGHT", "0.5"))     # Classifier-free guidance
SAMPLE_RATE     = 24000
CACHE_DIR       = Path.home() / ".cache" / "jarvis" / "tts_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_ENABLED   = os.getenv("TTS_CACHE", "true").lower() == "true"

# ── Lazy model loader ─────────────────────────────────────────────────────────
_model = None

def _load_model():
    global _model
    if _model is not None:
        return _model
    try:
        from chatterbox.tts import ChatterboxTTS
        logger.info(f"Loading Chatterbox TTS on {DEVICE}...")
        _model = ChatterboxTTS.from_pretrained(device=DEVICE)
        logger.info("Chatterbox TTS ready")
    except ImportError:
        raise RuntimeError(
            "chatterbox-tts not installed. Run: pip install chatterbox-tts"
        )
    return _model


# ── Cache helpers ─────────────────────────────────────────────────────────────
def _cache_key(text: str, lang: str, voice_ref: str) -> str:
    payload = f"{text}|{lang}|{voice_ref}|{EXAGGERATION}|{CFG_WEIGHT}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]

def _cache_get(key: str) -> Optional[np.ndarray]:
    path = CACHE_DIR / f"{key}.wav"
    if path.exists():
        audio, _ = sf.read(str(path), dtype="float32")
        return audio
    return None

def _cache_put(key: str, audio: np.ndarray):
    path = CACHE_DIR / f"{key}.wav"
    sf.write(str(path), audio, SAMPLE_RATE)


# ── Core synthesis ────────────────────────────────────────────────────────────
def synthesize(
    text: str,
    language: str = LANGUAGE,
    voice_ref: str = VOICE_REF_PATH,
    exaggeration: float = EXAGGERATION,
    cfg_weight: float = CFG_WEIGHT,
) -> np.ndarray:
    """Synthesize text to float32 numpy array at SAMPLE_RATE."""
    if not text.strip():
        return np.zeros(0, dtype=np.float32)

    if CACHE_ENABLED:
        key = _cache_key(text, language, voice_ref)
        cached = _cache_get(key)
        if cached is not None:
            logger.debug(f"TTS cache hit: {key}")
            return cached

    model = _load_model()

    kwargs = {
        "exaggeration": exaggeration,
        "cfg_weight": cfg_weight,
    }

    if voice_ref and Path(voice_ref).exists():
        audio_prompt, _ = sf.read(voice_ref, dtype="float32")
        kwargs["audio_prompt"] = audio_prompt
        logger.debug(f"Voice cloning from: {voice_ref}")

    wav = model.generate(text, **kwargs)

    if hasattr(wav, "cpu"):
        audio = wav.squeeze().cpu().numpy()
    elif hasattr(wav, "numpy"):
        audio = wav.squeeze().numpy()
    else:
        audio = np.array(wav, dtype=np.float32).squeeze()

    if CACHE_ENABLED:
        _cache_put(key, audio)

    return audio


# ── Playback ──────────────────────────────────────────────────────────────────
def speak(text: str, blocking: bool = True, **kwargs) -> None:
    """Play synthesized speech through default audio output."""
    audio = synthesize(text, **kwargs)
    if audio.size == 0:
        return
    sd.play(audio, samplerate=SAMPLE_RATE)
    if blocking:
        sd.wait()


async def speak_async(text: str, **kwargs) -> None:
    """Non-blocking async wrapper for the agent loop."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: speak(text, blocking=True, **kwargs))


# ── Save / bytes helpers ──────────────────────────────────────────────────────
def synthesize_to_file(text: str, output_path: str, **kwargs) -> str:
    """Synthesize and save to WAV file. Returns path."""
    audio = synthesize(text, **kwargs)
    sf.write(output_path, audio, SAMPLE_RATE)
    logger.info(f"TTS saved to: {output_path}")
    return output_path


def synthesize_to_bytes(text: str, fmt: str = "wav", **kwargs) -> bytes:
    """Synthesize and return raw bytes (for streaming HTTP responses)."""
    audio = synthesize(text, **kwargs)
    buf = io.BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format=fmt.upper())
    return buf.getvalue()


# ── Skill executor (loader interface) ─────────────────────────────────────────
def exec_chatterbox_tts(text: str, language: str = None, voice_ref: str = None) -> str:
    """Speak text aloud via Chatterbox TTS on the JARVIS server."""
    try:
        speak(
            text,
            language=language or LANGUAGE,
            voice_ref=voice_ref or VOICE_REF_PATH,
        )
        return f"Speaking: {text}"
    except Exception as e:
        logger.error(f"exec_chatterbox_tts error: {e}", exc_info=True)
        return f"TTS error: {e}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "chatterbox_tts",
            "description": "Speak text aloud using Chatterbox TTS on the JARVIS server. Use for responses that should be heard, announcements, or when the user asks Jarvis to say something.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to speak aloud.",
                    },
                    "language": {
                        "type": "string",
                        "description": "Language code (e.g. 'en', 'et', 'fi'). Defaults to TTS_LANGUAGE env var.",
                    },
                    "voice_ref": {
                        "type": "string",
                        "description": "Path to a WAV file for voice cloning. Optional.",
                    },
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "chatterbox_tts": exec_chatterbox_tts,
}

KEYWORDS = {
    "chatterbox_tts": [
        "speak",
        "say",
        "read aloud",
        "tts",
        "voice",
        "tell me",
        "announce",
        "read out",
        "say out loud",
    ],
}

SKILL_EXAMPLES = [
    {"command": "say hello world", "tool": "chatterbox_tts", "args": {"text": "Hello world"}},
    {"command": "speak the weather", "tool": "chatterbox_tts", "args": {"text": "The weather is sunny today"}},
    {"command": "tts: good morning", "tool": "chatterbox_tts", "args": {"text": "Good morning"}},
]


# ── JARVIS skill class (kept for direct use / plan_runner) ────────────────────
class ChatterboxSkill:
    """
    JARVIS skill interface — mirrors Kokoro skill API so react_server.py
    can swap with zero changes.

    Usage in react_server.py:
        from skills.chatterbox_skill import ChatterboxSkill
        tts = ChatterboxSkill()
        await tts.handle(text)
    """

    name = "chatterbox_tts"
    triggers = ["speak", "say", "tts", "voice"]

    def __init__(self):
        self.language = LANGUAGE
        self.voice_ref = VOICE_REF_PATH
        logger.info(
            f"ChatterboxSkill init | lang={self.language} | "
            f"voice_clone={'yes' if self.voice_ref else 'no'} | device={DEVICE}"
        )

    async def handle(self, text: str, **kwargs) -> dict:
        """Main entry point called by JARVIS plan_runner / react_server."""
        try:
            await speak_async(
                text,
                language=kwargs.get("language", self.language),
                voice_ref=kwargs.get("voice_ref", self.voice_ref),
                exaggeration=kwargs.get("exaggeration", EXAGGERATION),
                cfg_weight=kwargs.get("cfg_weight", CFG_WEIGHT),
            )
            return {"status": "ok", "text": text}
        except Exception as e:
            logger.error(f"ChatterboxSkill error: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    async def stream_bytes(self, text: str) -> bytes:
        """For WebSocket streaming to mobile client."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: synthesize_to_bytes(text)
        )

    def set_voice(self, wav_path: str):
        """Hot-swap voice reference (voice cloning)."""
        if Path(wav_path).exists():
            self.voice_ref = wav_path
            logger.info(f"Voice reference updated: {wav_path}")
        else:
            logger.warning(f"Voice reference not found: {wav_path}")

    def set_language(self, lang: str):
        """Switch language at runtime (e.g. 'et' for Estonian)."""
        self.language = lang
        logger.info(f"TTS language set to: {lang}")


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    text = " ".join(sys.argv[1:]) or "Hello from JARVIS. Chatterbox TTS is online."
    print(f"Speaking: {text}")
    speak(text)
    print("Done.")
