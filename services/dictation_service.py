from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import sounddevice as sd
import soundfile as sf


class DictationService:
    def __init__(self, vault_dir: Path):
        self.vault_dir = Path(vault_dir)
        self.base_dir = self.vault_dir / ".jarvis" / "dictation"
        self.audio_dir = self.base_dir / "audio"
        self.transcript_dir = self.base_dir / "transcripts"
        self.index_path = self.base_dir / "index" / "transcripts.jsonl"
        self.active_state_path = self.base_dir / "active_state.json"

        self.sample_rate = int(os.environ.get("JARVIS_DICTATE_SAMPLE_RATE", "16000"))
        self.channels = int(os.environ.get("JARVIS_DICTATE_CHANNELS", "1"))
        self.model_size = os.environ.get("JARVIS_WHISPER_MODEL", "base")

        self._recording = False
        self._thread: Optional[threading.Thread] = None
        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue()
        self._session_id: Optional[str] = None
        self._wav_path: Optional[Path] = None

    def _now_iso(self) -> str:
        return datetime.utcnow().isoformat(timespec="seconds") + "Z"

    def _date_dir(self) -> str:
        return datetime.utcnow().strftime("%Y-%m-%d")

    def _stamp(self) -> str:
        return datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    def _ensure_dirs(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

    def _write_state(self, data: Dict[str, Any]) -> None:
        self._ensure_dirs()
        self.active_state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def status(self) -> Dict[str, Any]:
        state = {}
        if self.active_state_path.exists():
            try:
                state = json.loads(self.active_state_path.read_text(encoding="utf-8"))
            except Exception:
                state = {}

        return {
            "ok": True,
            "recording": self._recording,
            "session_id": self._session_id,
            "wav_path": str(self._wav_path) if self._wav_path else None,
            "state": state,
        }

    def start(self, title: str = "Dictation") -> Dict[str, Any]:
        if self._recording:
            return {
                "ok": False,
                "speech": "Dictation is already recording.",
                "status": self.status(),
            }

        self._ensure_dirs()

        session_id = "dict_" + str(uuid.uuid4())[:8]
        date_dir = self._date_dir()
        stamp = self._stamp()

        audio_day_dir = self.audio_dir / date_dir
        audio_day_dir.mkdir(parents=True, exist_ok=True)

        wav_path = audio_day_dir / f"{stamp}_{session_id}.wav"

        self._session_id = session_id
        self._wav_path = wav_path
        self._recording = True
        self._audio_queue = queue.Queue()

        self._write_state(
            {
                "session_id": session_id,
                "title": title,
                "started_at": self._now_iso(),
                "recording": True,
                "wav_path": str(wav_path),
                "sample_rate": self.sample_rate,
                "channels": self.channels,
            }
        )

        self._thread = threading.Thread(
            target=self._record_audio_worker,
            args=(wav_path,),
            daemon=True,
        )
        self._thread.start()

        return {
            "ok": True,
            "speech": f"Started dictation: {title}",
            "session_id": session_id,
            "wav_path": str(wav_path),
        }

    def _record_audio_worker(self, wav_path: Path) -> None:
        def callback(indata, frames, time_info, status):
            if status:
                print(f"[DICTATE] audio status: {status}", flush=True)
            if self._recording:
                self._audio_queue.put(indata.copy())

        with sf.SoundFile(
            str(wav_path),
            mode="w",
            samplerate=self.sample_rate,
            channels=self.channels,
            subtype="PCM_16",
        ) as file:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=callback,
            ):
                while self._recording:
                    try:
                        chunk = self._audio_queue.get(timeout=0.5)
                        file.write(chunk)
                    except queue.Empty:
                        continue

    def stop(self) -> Dict[str, Any]:
        if not self._recording:
            return {
                "ok": False,
                "speech": "Dictation is not recording.",
                "status": self.status(),
            }

        self._recording = False

        if self._thread:
            self._thread.join(timeout=5)

        wav_path = self._wav_path
        session_id = self._session_id

        self._write_state(
            {
                "session_id": session_id,
                "recording": False,
                "stopped_at": self._now_iso(),
                "wav_path": str(wav_path) if wav_path else None,
            }
        )

        if not wav_path or not wav_path.exists():
            return {
                "ok": False,
                "speech": "Recording stopped, but WAV file was not found.",
            }

        transcript_result = self.transcribe_and_index(
            wav_path=wav_path,
            session_id=session_id or "unknown",
        )

        return {
            "ok": True,
            "speech": "Dictation stopped, transcribed, and indexed.",
            "session_id": session_id,
            "wav_path": str(wav_path),
            **transcript_result,
        }

    def transcribe_and_index(self, wav_path: Path, session_id: str) -> Dict[str, Any]:
        from faster_whisper import WhisperModel

        model = WhisperModel(
            self.model_size,
            device=os.environ.get("JARVIS_WHISPER_DEVICE", "cpu"),
            compute_type=os.environ.get("JARVIS_WHISPER_COMPUTE", "int8"),
        )

        segments, info = model.transcribe(str(wav_path), beam_size=5)

        segment_items: List[Dict[str, Any]] = []
        text_parts: List[str] = []

        for seg in segments:
            item = {
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
            }
            segment_items.append(item)
            text_parts.append(item["text"])

        transcript = " ".join(text_parts).strip()

        stamp = wav_path.stem
        date_dir = self._date_dir()
        transcript_day_dir = self.transcript_dir / date_dir
        transcript_day_dir.mkdir(parents=True, exist_ok=True)

        json_path = transcript_day_dir / f"{stamp}.json"
        md_path = transcript_day_dir / f"{stamp}.md"

        payload = {
            "id": session_id,
            "timestamp": self._now_iso(),
            "source": "microphone",
            "wav_path": str(wav_path),
            "language": getattr(info, "language", None),
            "duration": getattr(info, "duration", None),
            "transcript": transcript,
            "segments": segment_items,
        }

        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(
            f"# Dictation {session_id}\n\n"
            f"Time: {payload['timestamp']}\n\n"
            f"WAV: `{wav_path}`\n\n"
            f"## Transcript\n\n{transcript}\n",
            encoding="utf-8",
        )

        self._append_index(payload, json_path, md_path)

        return {
            "transcript": transcript,
            "json_path": str(json_path),
            "md_path": str(md_path),
            "language": payload["language"],
            "duration": payload["duration"],
        }

    def _append_index(self, payload: Dict[str, Any], json_path: Path, md_path: Path) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

        index_item = {
            "id": payload["id"],
            "timestamp": payload["timestamp"],
            "source": payload["source"],
            "wav_path": payload["wav_path"],
            "json_path": str(json_path),
            "md_path": str(md_path),
            "language": payload.get("language"),
            "duration": payload.get("duration"),
            "transcript": payload.get("transcript", ""),
        }

        with self.index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(index_item, ensure_ascii=False) + "\n")

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        if not self.index_path.exists():
            return {"ok": True, "results": []}

        query_lower = query.lower()
        results = []

        for line in self.index_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue

            transcript = item.get("transcript", "")
            if query_lower in transcript.lower():
                results.append(item)

        return {
            "ok": True,
            "results": results[-limit:],
        }

    def read_last(self) -> Dict[str, Any]:
        if not self.index_path.exists():
            return {"ok": False, "speech": "No dictation index found."}

        lines = [line for line in self.index_path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
        if not lines:
            return {"ok": False, "speech": "No dictations found."}

        item = json.loads(lines[-1])
        return {
            "ok": True,
            "item": item,
            "speech": item.get("transcript", ""),
        }