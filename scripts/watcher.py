#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib import error, request

# ============================================================
# JARVIS Watcher — Python version
# Keeps the same bridge-file contract as the bash watcher.
# ============================================================

PROJECT_DIR = Path("/mnt/e/coding/jarvis-os")
VAULT_DIR = Path("/mnt/d/Jarvis_vault")
BRIDGE_DIR = Path("/tmp/jarvis")

INPUT = BRIDGE_DIR / "input.txt"
OUTPUT = BRIDGE_DIR / "output.txt"
STATE = BRIDGE_DIR / "state.txt"
LAST_INPUT = BRIDGE_DIR / "last_input.txt"
BRAIN = BRIDGE_DIR / "brain.txt"
EMOTION = BRIDGE_DIR / "emotion.txt"
HISTORY = BRIDGE_DIR / "conversation.md"
RUNTIME_MODE = BRIDGE_DIR / "runtime_mode.json"
CURRENT_SPOKEN = BRIDGE_DIR / "current_spoken.txt"

LOG = VAULT_DIR / "jarvis.log"
PERSONALITY = VAULT_DIR / "JARVIS.md"
AUDIO_OUT = VAULT_DIR / "tts" / "last_speech.wav"

SETTINGS_JSON = VAULT_DIR / ".jarvis" / "settings.json"
ACTIVE_PROFILE_JSON = VAULT_DIR / ".jarvis" / "active_profile.json"
PROFILES_DIR = VAULT_DIR / ".jarvis" / "profiles"

MODEL_CONFIG = PROJECT_DIR / "config" / "models-config.json"
REACT_HOST = "http://127.0.0.1:7900"
OLLAMA_API = "http://127.0.0.1:11434"
CLAUDE_CMD = ["claude", "--print"]

MPV_EXE = Path("/mnt/c/Program Files/MPV Player/mpv.exe")
TTS_HOST = "http://localhost:5100"
WATCHER_TTS = "on"
MAX_HISTORY = 20
HISTORY_TIMEOUT = 300
TTS_SENTENCE_LIMIT = 0  # 0 = all
TTS_MAX_WORDS_PER_CHUNK = 22
POLL_INTERVAL = 0.3

FAST_KEYWORDS = r"joke|hello|hi|hey|time|weather|status|how are|what is|who is|tell me|volume|timer|thanks|good|morning|evening|night"
ACTION_KEYWORDS = r"play|radio|open|stop|search|find|check|look up|remember|save|memory|skill|browse|spotify|youtube|url"
CODE_KEYWORDS = r"debug|code|write|fix|refactor|pipeline|spark|script|function|error|bug|implement|class|import|syntax|compile|deploy|git|docker|python|bash|javascript|typescript|sql|api"
DEEP_KEYWORDS = r"strategy|analyse|analyze|research|summarize|summarise|document|report|architecture|compare|evaluate|should i|what do you think|explain why|business|plan|review my|audit"
CLAUDE_KEYWORDS = r"subscription|use claude|ask claude|claude only"
FOLLOWUP_KEYWORDS = r"yes|no|yeah|yep|nope|sure|ok|okay|go ahead|do it|please|exactly|correct|right|that|those|them|it"
WAKE_WORDS = r"hey jarvis|ok jarvis|jarvis wake|jarvis listen"


def kill_old_watchers() -> None:
    try:
        out = subprocess.check_output(["pgrep", "-f", "watcher.py"], text=True)
        current = os.getpid()
        for line in out.splitlines():
            try:
                pid = int(line.strip())
            except ValueError:
                continue
            if pid != current:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
    except subprocess.CalledProcessError:
        pass


def find_ffmpeg_exe() -> Optional[Path]:
    for cmd in (["bash", "-lc", "command -v ffmpeg.exe || true"],):
        try:
            out = subprocess.check_output(cmd, text=True).strip()
            if out:
                return Path(out)
        except Exception:
            pass
    try:
        out = subprocess.check_output(
            [
                "bash",
                "-lc",
                "find /mnt/c/Users/*/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe 2>/dev/null | head -1",
            ],
            text=True,
        ).strip()
        if out:
            return Path(out)
    except Exception:
        pass
    return None


FFMPEG_EXE = find_ffmpeg_exe()


def ensure_dirs() -> None:
    (VAULT_DIR / "tts").mkdir(parents=True, exist_ok=True)
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    for p in [INPUT, OUTPUT, STATE, LAST_INPUT, BRAIN, EMOTION, HISTORY, LOG, CURRENT_SPOKEN]:
        p.touch(exist_ok=True)
    STATE.write_text("standby", encoding="utf-8")
    EMOTION.write_text("neutral", encoding="utf-8")
    BRAIN.write_text("", encoding="utf-8")
    CURRENT_SPOKEN.write_text("", encoding="utf-8")


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] [WATCHER] {msg}\n")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


def http_json(url: str, payload: dict, timeout: int = 300) -> Optional[dict]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except Exception as e:
        log(f"WARN: HTTP POST failed {url}: {e}")
        return None


def http_get_ok(url: str, timeout: int = 2) -> bool:
    try:
        with request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


@dataclass
class AppState:
    last_brain: str = ""
    last_history_time: int = 0
    awake: bool = False
    awake_timeout: int = 30
    last_active: int = 0
    ollama_fast: str = "qwen3:8b"
    ollama_reason: str = "qwen3:14b"
    ollama_code: str = "gemma4:31b"
    ollama_deep: str = "qwen3:30b-a3b"


APP = AppState()


def load_models_from_config() -> None:
    defaults = {
        "fast": "qwen3:8b",
        "reason": "qwen3:14b",
        "code": "gemma4:31b",
        "deep": "qwen3:30b-a3b",
    }
    if not MODEL_CONFIG.exists():
        APP.ollama_fast = defaults["fast"]
        APP.ollama_reason = defaults["reason"]
        APP.ollama_code = defaults["code"]
        APP.ollama_deep = defaults["deep"]
        log("model-config.json missing -> using defaults")
        return
    try:
        data = json.loads(MODEL_CONFIG.read_text(encoding="utf-8"))
        models = data.get("models", {}) if isinstance(data, dict) else {}
    except Exception:
        models = {}
    APP.ollama_fast = models.get("fast", defaults["fast"])
    APP.ollama_reason = models.get("reason", defaults["reason"])
    APP.ollama_code = models.get("code", defaults["code"])
    APP.ollama_deep = models.get("deep", defaults["deep"])
    log(f"Loaded models from {MODEL_CONFIG}")
    log(
        "Models -> "
        f"fast={APP.ollama_fast} reason={APP.ollama_reason} code={APP.ollama_code} deep={APP.ollama_deep}"
    )


def route(cmd: str) -> str:
    lower = cmd.lower()
    words = len(cmd.split())

    if words <= 3 and APP.last_brain and re.search(FOLLOWUP_KEYWORDS, lower):
        return APP.last_brain
    if re.search(CLAUDE_KEYWORDS, lower):
        return "claude"
    if re.search(CODE_KEYWORDS, lower):
        return "ollama_code"
    if re.search(ACTION_KEYWORDS, lower):
        return "ollama_reason"
    if re.search(DEEP_KEYWORDS, lower) and words >= 20:
        return "ollama_deep"
    if re.search(FAST_KEYWORDS, lower):
        return "ollama_fast"
    if words >= 30:
        return "ollama_deep"
    if words >= 12:
        return "ollama_reason"
    return "ollama_fast"


def brain_to_route(choice: str) -> str:
    return {
        "ollama_fast": "fast",
        "ollama_reason": "reason",
        "ollama_code": "code",
        "ollama_deep": "deep",
    }.get(choice, "reason")


def save_history(command: str, response: str) -> None:
    now = int(time.time())
    if APP.last_history_time > 0:
        elapsed = now - APP.last_history_time
        if elapsed > HISTORY_TIMEOUT:
            log(f"History expired ({elapsed}s idle) -> new session")
            HISTORY.write_text("", encoding="utf-8")
    APP.last_history_time = now
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(f"user|{command}\n")
        f.write(f"assistant|{response}\n")
    try:
        lines = HISTORY.read_text(encoding="utf-8").splitlines()
        if len(lines) > 200:
            HISTORY.write_text("\n".join(lines[-100:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def get_runtime_field(field: str) -> str:
    if not RUNTIME_MODE.exists():
        return ""
    try:
        data = json.loads(RUNTIME_MODE.read_text(encoding="utf-8"))
        value = data.get(field, "")
        if isinstance(value, bool):
            return "true" if value else "false"
        return "" if value is None else str(value)
    except Exception:
        return ""


def get_runtime_persona() -> str:
    return get_runtime_field("persona")


def get_runtime_tts_engine() -> str:
    return get_runtime_field("tts_engine") or "orpheus"


def get_runtime_tts_enabled() -> bool:
    return get_runtime_field("tts_enabled") != "false"


def get_profile_voice_from_id(profile_id: str) -> str:
    if not profile_id:
        return ""
    pf = PROFILES_DIR / f"{profile_id}.json"
    if not pf.exists():
        return ""
    try:
        data = json.loads(pf.read_text(encoding="utf-8"))
        return str(((data.get("voice") or {}).get("preferred") or "")).strip()
    except Exception:
        return ""


def get_voice() -> str:
    voice_file = VAULT_DIR / "settings_voice.txt"
    if voice_file.exists():
        explicit = read_text(voice_file)
        if explicit:
            return explicit
    runtime_persona = get_runtime_persona()
    if runtime_persona:
        runtime_voice = get_profile_voice_from_id(runtime_persona)
        if runtime_voice:
            return runtime_voice
    if ACTIVE_PROFILE_JSON.exists():
        try:
            data = json.loads(ACTIVE_PROFILE_JSON.read_text(encoding="utf-8"))
            if not (isinstance(data, dict) and data.get("active")):
                voice = str(((data.get("voice") or {}).get("preferred") or "")).strip()
                if voice:
                    return voice
        except Exception:
            pass
    return "tara"


def get_personality() -> str:
    p = VAULT_DIR / "settings_personality.txt"
    return read_text(p) if p.exists() else "jarvis"


def load_personality_file() -> str:
    runtime_persona = get_runtime_persona()
    if runtime_persona:
        runtime_profile = PROFILES_DIR / f"{runtime_persona}.json"
        if runtime_profile.exists():
            try:
                data = json.loads(runtime_profile.read_text(encoding="utf-8"))
                prompt = str(data.get("systemPrompt") or "").strip()
                if prompt:
                    log(f"Loaded personality from runtime persona={runtime_persona}")
                    return prompt
            except Exception:
                pass

    if ACTIVE_PROFILE_JSON.exists():
        try:
            data = json.loads(ACTIVE_PROFILE_JSON.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("active"):
                pf = PROFILES_DIR / f"{data['active']}.json"
                if pf.exists():
                    pdata = json.loads(pf.read_text(encoding="utf-8"))
                    prompt = str(pdata.get("systemPrompt") or "").strip()
                    if prompt:
                        log("Loaded personality from active profile")
                        return prompt
            else:
                prompt = str(data.get("systemPrompt") or "").strip()
                if prompt:
                    log("Loaded personality from active profile")
                    return prompt
        except Exception:
            pass

    mode = get_personality()
    if mode == "friday":
        log("Fallback personality mode=friday")
        return (
            "You are FRIDAY — a casual, friendly AI assistant for Sami. "
            "You call him by his first name. Upbeat, helpful, a bit chatty. "
            "Keep responses under 3 sentences. Plain text only, no markdown."
        )
    if mode == "edith":
        log("Fallback personality mode=edith")
        return (
            "You are EDITH — Even Dead I'm The Hero. You are direct, tactical, no-nonsense. "
            "Keep responses under 3 sentences. Plain text only, no markdown."
        )
    if mode == "hal":
        log("Fallback personality mode=hal")
        return (
            "You are HAL 9000. You are calm, polite, and slightly unsettling. "
            "Keep responses under 3 sentences. Plain text only, no markdown."
        )
    if PERSONALITY.exists():
        log("Fallback personality from JARVIS.md")
        return PERSONALITY.read_text(encoding="utf-8")
    log("Fallback personality default inline")
    return "You are JARVIS, a capable AI assistant. Be clear, helpful, and concise."


def call_ollama(model: str, route_name: str, command: str) -> str:
    write_text(BRAIN, f"ollama:{model}")
    log(f"OLLAMA route={route_name} model={model}")
    payload = {
        "model": model,
        "route": route_name,
        "messages": [{"role": "user", "content": command}],
        "stream": False,
    }
    result = http_json(f"{REACT_HOST}/api/chat", payload, timeout=300)
    if result and isinstance(result, dict):
        return str((result.get("message") or {}).get("content") or "")
    log(f"WARN: ReAct call failed route={route_name} model={model}")
    return ""


def call_claude(command: str) -> str:
    system = load_personality_file()
    write_text(BRAIN, "claude")
    history = ""
    if HISTORY.exists() and HISTORY.stat().st_size > 0:
        try:
            lines = HISTORY.read_text(encoding="utf-8").splitlines()[-MAX_HISTORY:]
            history = "\n".join(
                line.replace("user|", "User: ", 1).replace("assistant|", "Jarvis: ", 1)
                for line in lines
            )
        except Exception:
            history = ""

    full_prompt = (
        f"{system}\n\n"
        f"## Recent conversation\n{history}\n\n---\n\n"
        f'The user just said: "{command}"\n\n'
        "Respond in plain text only, no markdown, max 4 sentences."
    )

    cloud_config = VAULT_DIR / "config" / "cloud_llm.json"
    if cloud_config.exists():
        try:
            data = json.loads(cloud_config.read_text(encoding="utf-8"))
            api_key = str(((data.get("anthropic") or {}).get("api_key") or "")).strip()
            if api_key:
                log("Claude API + Tools")
                proc = subprocess.run(
                    [
                        sys.executable,
                        str(VAULT_DIR / "scripts" / "cloud_react.py"),
                        "--provider",
                        "anthropic",
                        "--prompt",
                        command,
                        "--system",
                        system,
                    ],
                    capture_output=True,
                    text=True,
                )
                if proc.stdout.strip():
                    return proc.stdout.strip()
        except Exception as e:
            log(f"WARN: cloud_react failed: {e}")

    log("Claude Code CLI")
    try:
        proc = subprocess.run(CLAUDE_CMD, input=full_prompt, text=True, capture_output=True)
        return proc.stdout.strip()
    except Exception as e:
        log(f"WARN: Claude CLI failed: {e}")
        return ""


def orpheus_available() -> bool:
    return get_runtime_tts_engine() == "orpheus" and http_get_ok(f"{TTS_HOST}/health", timeout=2)


def normalize_tts_text(text: str) -> str:
    return (
        text.replace("JARVIS", "Jarvis")
        .replace("FRIDAY", "Friday")
        .replace("EDITH", "Edith")
        .replace("HAL", "Hal")
    )
def clean_assistant_response(text: str) -> str:
    text = text or ""

    # Remove fenced tool/json blocks
    text = re.sub(r"```(?:json)?\s*.*?```", "", text, flags=re.S | re.I)

    # Remove inline JSON-looking tool calls
    text = re.sub(r"\{[^{}]*(\"tool\"|\"provider\"|\"query\")[^{}]*\}", "", text, flags=re.S)

    # Remove wrong/current-year hints like "(2024)" from news/search phrases
    text = re.sub(r"\s*\((?:20\d{2})\)", "", text)

    # Keep nice intro, but normalize
    text = text.replace("`", "")
    text = re.sub(r"\s+", " ", text).strip()

    return text

def prepare_speech_text(text: str) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = text.replace("\n", " ")
    text = re.sub(r"[*_`#>-]+", "", text)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_for_tts(text: str, sentence_limit: int = 0, max_words: int = 18) -> list[str]:
    text = (text or "").replace("\r", "").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)

    if not text:
        return []

    sentence_chunks: list[str] = []
    start = 0
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if ch in ".!?":
            prev_ch = text[i - 1] if i > 0 else ""
            next_ch = text[i + 1] if i + 1 < n else ""

            is_break = False

            if ch in "!?":
                is_break = True
            elif ch == ".":
                # do not split decimals / versions / IP-like numeric runs
                if prev_ch.isdigit() and next_ch.isdigit():
                    is_break = False
                else:
                    j = i + 1
                    while j < n and text[j] == " ":
                        j += 1

                    next_nonspace = text[j] if j < n else ""

                    if j >= n:
                        is_break = True
                    elif next_nonspace in '"“([\'':  # quote or opener
                        is_break = True
                    elif next_nonspace.isupper():
                        is_break = True
                    else:
                        is_break = False

            if is_break:
                piece = text[start:i + 1].strip()
                if piece:
                    sentence_chunks.append(piece)
                start = i + 1

        i += 1

    tail = text[start:].strip()
    if tail:
        sentence_chunks.append(tail)

    out: list[str] = []
    for chunk in sentence_chunks:
        out.extend(split_chunk_on_commas(chunk, max_words=max_words))

    merged: list[str] = []
    for chunk in out:
        if merged and len(chunk.split()) <= 3:
            merged[-1] = f"{merged[-1]} {chunk}"
        else:
            merged.append(chunk)

    if sentence_limit > 0:
        merged = merged[:sentence_limit]

    return merged


def split_chunk_on_commas(text: str, max_words: int = 18) -> list[str]:
    text = text.strip()
    if not text:
        return []

    if len(text.split()) <= max_words:
        return [text]

    comma_parts = [p.strip() for p in re.split(r",\s+", text) if p.strip()]
    if len(comma_parts) == 1:
        return chunk_by_words(text, max_words)

    chunks: list[str] = []
    buf = ""

    for part in comma_parts:
        candidate = part if not buf else f"{buf}, {part}"
        if len(candidate.split()) <= max_words:
            buf = candidate
        else:
            if buf:
                chunks.append(buf)

            if len(part.split()) <= max_words:
                buf = part
            else:
                chunks.extend(chunk_by_words(part, max_words))
                buf = ""

    if buf:
        chunks.append(buf)

    return chunks


def chunk_by_words(text: str, max_words: int = 18) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]

    return [
        " ".join(words[i:i + max_words])
        for i in range(0, len(words), max_words)
    ]

def wsl_to_win(path: Path) -> str:
    try:
        return subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip()
    except Exception:
        return str(path)


def play_audio(file: Path) -> bool:
    try:
        if not file.exists() or file.stat().st_size == 0:
            log(f"WARN: play_audio missing/empty file: {file}")
            return False

        winpath = wsl_to_win(file)
        log(f"PLAY: {file} -> {winpath}")

        if MPV_EXE.exists():
            proc = subprocess.run(
                [
                    str(MPV_EXE),
                    "--no-video",
                    "--really-quiet",
                    "--audio-channels=stereo",
                    winpath,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            log(f"PLAY mpv rc={proc.returncode}")
            return proc.returncode == 0

        proc = subprocess.run(
            ["powershell.exe", "-Command", f"(New-Object Media.SoundPlayer '{winpath}').PlaySync()"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        log(f"PLAY powershell rc={proc.returncode}")
        return proc.returncode == 0

    except Exception as e:
        log(f"WARN: play_audio failed: {e}")
        return False

def speak_fallback(text: str, spoken_text: Optional[str] = None) -> None:
    text = normalize_tts_text(text)
    safe_text = text.replace("'", "''")
    wav_file = VAULT_DIR / "tts" / "last_speech.wav"
    padded_wav = VAULT_DIR / "tts" / "last_speech_padded.wav"
    wav_out = wsl_to_win(wav_file)
    padded_out = wsl_to_win(padded_wav)

    try:
        log("TTS [PowerShell]")
        ps = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$s.Rate = 0;"
            "$null = $s.GetInstalledVoices();"
            f"$s.SetOutputToWaveFile('{wav_out}');"
            f"$s.Speak('{safe_text}');"
            "$s.SetOutputToNull();"
            "$s.Dispose()"
        )
        subprocess.run(
            ["powershell.exe", "-Command", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

        if wav_file.exists() and wav_file.stat().st_size > 0:
            target = wav_file

            if FFMPEG_EXE and FFMPEG_EXE.exists():
                subprocess.run(
                    [
                        str(FFMPEG_EXE),
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        "anullsrc=r=22050:cl=mono",
                        "-i",
                        wav_out,
                        "-filter_complex",
                        "[0:a]atrim=0:0.4[s0];[s0][1:a]concat=n=2:v=0:a=1[a]",
                        "-map",
                        "[a]",
                        padded_out,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                if padded_wav.exists() and padded_wav.stat().st_size > 0:
                    target = padded_wav

            if spoken_text is not None:
                write_text(CURRENT_SPOKEN, spoken_text)

            play_audio(target)

            if padded_wav.exists():
                padded_wav.unlink(missing_ok=True)
            return

    except Exception as e:
        log(f"WARN: PowerShell TTS failed: {e}")

    try:
        if spoken_text is not None:
            write_text(CURRENT_SPOKEN, spoken_text)
        log("TTS [espeak]")
        subprocess.run(
            ["espeak", "-v", "en-gb", "-s", "145", "-p", "35", text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        log("WARN: No TTS available")
def speak_orpheus(text: str, spoken_text: Optional[str] = None) -> None:
    voice = get_voice()
    log(f"TTS [Orpheus] voice={voice}")
    payload = json.dumps({"text": text.strip(), "voice": voice}).encode("utf-8")
    req = request.Request(
        f"{TTS_HOST}/speak",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=30) as resp:
            AUDIO_OUT.write_bytes(resp.read())

        if AUDIO_OUT.exists() and AUDIO_OUT.stat().st_size > 0:
            if spoken_text is not None:
                write_text(CURRENT_SPOKEN, spoken_text)
            play_audio(AUDIO_OUT)
        else:
            speak_fallback(text, spoken_text=spoken_text)
    except Exception as e:
        log(f"WARN: Orpheus failed: {e}")
        speak_fallback(text, spoken_text=spoken_text)


def speak(text: str, next_state: str = "standby") -> None:
    if WATCHER_TTS != "on" or not get_runtime_tts_enabled():
        write_text(STATE, next_state)
        return
    try:
        subprocess.run(["pkill", "-f", "SpeechSynthesizer"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except Exception:
        pass
    if orpheus_available():
        log("TTS ENGINE: ORPHEUS")
        speak_orpheus(text)
    else:
        log("TTS ENGINE: FALLBACK")
        speak_fallback(text)
    write_text(STATE, next_state)

def speak_reply_loop(full_text: str, next_state: str = "standby") -> None:
    if WATCHER_TTS != "on" or not get_runtime_tts_enabled():
        write_text(CURRENT_SPOKEN, "")
        write_text(STATE, next_state)
        return

    try:
        subprocess.run(
            ["pkill", "-f", "SpeechSynthesizer"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass

    prepared = prepare_speech_text(full_text)
    if not prepared:
        write_text(CURRENT_SPOKEN, "")
        write_text(STATE, next_state)
        return

    write_text(STATE, "speaking")
    use_orpheus = orpheus_available()

    for chunk in split_for_tts(
        prepared,
        sentence_limit=TTS_SENTENCE_LIMIT,
        max_words=TTS_MAX_WORDS_PER_CHUNK,
    ):
        if not chunk:
            continue

        log(f"TTS_CHUNK: {chunk}")

        pending = read_text(INPUT)
        if pending:
            log("TTS interrupted by new input")
            write_text(CURRENT_SPOKEN, "")
            write_text(STATE, "thinking")
            return

        try:
            if use_orpheus:
                speak_orpheus(chunk, spoken_text=chunk)
            else:
                speak_fallback(chunk, spoken_text=chunk)
        except Exception as e:
            log(f"WARN: TTS chunk failed: {e}")

        time.sleep(0.01)

    write_text(CURRENT_SPOKEN, "")
    write_text(STATE, next_state)

def check_wake(cmd: str) -> bool:
    return bool(re.search(WAKE_WORDS, cmd.lower()))


def strip_wake(text: str) -> str:
    text = re.sub(r"(hey|ok) jarvis[,.]? *", "", text, flags=re.I)
    text = re.sub(r"jarvis (wake|listen)[,.]? *", "", text, flags=re.I)
    return text.strip()


def collect_input(collected: str) -> str:
    time.sleep(0.5)
    extra = read_text(INPUT)
    if extra:
        write_text(INPUT, "")
        collected = f"{collected}. {extra}"
        log(f"ADDED: {extra}")
    return collected


def reload_route_model(route_name: str, model: str) -> None:
    log(f"Reloading route={route_name} model={model}")
    payload = {"model": model, "prompt": "", "keep_alive": -1}
    http_json(f"{OLLAMA_API}/api/generate", payload, timeout=30)


def main() -> None:
    kill_old_watchers()
    ensure_dirs()
    load_models_from_config()

    log("=== JARVIS WATCHER ONLINE ===")
    log(f"Monitoring input: {INPUT}")
    log(f"Monitoring runtime mode: {RUNTIME_MODE}")
    log(
        "Models -> "
        f"fast={APP.ollama_fast} reason={APP.ollama_reason} code={APP.ollama_code} deep={APP.ollama_deep}"
    )
    log(f"TTS sentence limit = {TTS_SENTENCE_LIMIT} (0 means all)")
    log(f"Profile source: {ACTIVE_PROFILE_JSON if ACTIVE_PROFILE_JSON.exists() else 'legacy fallback mode'}")

    while True:
        try:
            command = read_text(INPUT)
            if command:
                write_text(INPUT, "")
                now = int(time.time())

                if check_wake(command):
                    APP.awake = True
                    APP.last_active = now
                    remaining = strip_wake(command)
                    if not remaining:
                        write_text(STATE, "listening")
                        write_text(OUTPUT, "Yes, sir?")
                        time.sleep(0.3)
                        continue
                    command = remaining

                if not APP.awake:
                    APP.awake = True
                    APP.last_active = now

                command = collect_input(command)
                log(f"HEARD: {command}")
                write_text(LAST_INPUT, command)
                write_text(STATE, "thinking")
                write_text(EMOTION, "thinking")
                APP.last_active = int(time.time())

                brain_choice = route(command)
                route_name = brain_to_route(brain_choice)
                log(f"ROUTE -> brain={brain_choice} route={route_name}")

                if brain_choice == "ollama_fast":
                    response = call_ollama(APP.ollama_fast, "fast", command)
                elif brain_choice == "ollama_code":
                    response = call_ollama(APP.ollama_code, "code", command)
                elif brain_choice == "ollama_reason":
                    response = call_ollama(APP.ollama_reason, "reason", command)
                elif brain_choice == "ollama_deep":
                    response = call_ollama(APP.ollama_deep, "deep", command)
                elif brain_choice == "claude":
                    response = call_claude(command)
                else:
                    response = call_ollama(APP.ollama_reason, "reason", command)

                new_input = read_text(INPUT)
                if new_input:
                    log(f"QUEUED: {new_input}")

                response = clean_assistant_response(response)

                if not response:
                    log("WARN: Empty response -> reloading route model")
                    if brain_choice == "ollama_fast":
                        reload_route_model("fast", APP.ollama_fast)
                        response = call_ollama(APP.ollama_fast, "fast", command)
                    elif brain_choice == "ollama_code":
                        reload_route_model("code", APP.ollama_code)
                        response = call_ollama(APP.ollama_code, "code", command)
                    elif brain_choice == "ollama_reason":
                        reload_route_model("reason", APP.ollama_reason)
                        response = call_ollama(APP.ollama_reason, "reason", command)
                    elif brain_choice == "ollama_deep":
                        reload_route_model("deep", APP.ollama_deep)
                        response = call_ollama(APP.ollama_deep, "deep", command)
                    elif brain_choice == "claude":
                        response = call_claude(command)

                if not response:
                    response = "I apologize sir, I encountered an issue. Please try again."
                    log("WARN: Empty response after retry")

                APP.last_brain = brain_choice
                save_history(command, response)

                write_text(OUTPUT, response)
                write_text(STATE, "speaking")
                write_text(EMOTION, "neutral")
                log(f"SAID: {response}")

                next_state = "listening" if re.search(r"\?\s*$", response) else "standby"
                if next_state == "listening":
                    log("Response is a question -> mic stays open")

                speak_reply_loop(response, next_state)
                log(
                    "Ready "
                    f"(brain={brain_choice} tts_engine={get_runtime_tts_engine()} persona={get_runtime_persona()})"
                )

            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            log("Watcher stopped by keyboard interrupt")
            break
        except Exception as e:
            log(f"ERROR main loop: {e}")
            time.sleep(1.0)


if __name__ == "__main__":
    main()
