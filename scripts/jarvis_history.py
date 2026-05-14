from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional

VAULT = Path("/mnt/d/Jarvis_vault")
HISTORY_DIR = VAULT / ".jarvis" / "history" / "plans"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def make_plan_id() -> str:
    date = datetime.now().strftime("%Y%m%d")
    day_dir = HISTORY_DIR
    day_dir.mkdir(parents=True, exist_ok=True)

    existing = list(day_dir.glob(f"PLAN-{date}-*"))
    number = len(existing) + 1
    return f"PLAN-{date}-{number:03d}"


def plan_dir(plan_id: str) -> Path:
    d = HISTORY_DIR / plan_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "patches").mkdir(exist_ok=True)
    (d / "reviews").mkdir(exist_ok=True)
    return d


def save_json(plan_id: str, filename: str, data: Dict[str, Any]) -> None:
    path = plan_dir(plan_id) / filename
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def append_event(
    event_type: str,
    message: str,
    *,
    plan_id: Optional[str] = None,
    task_id: Optional[str] = None,
    route: Optional[str] = None,
    model: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    event = {
        "ts": now_iso(),
        "event_type": event_type,
        "message": message,
        "plan_id": plan_id,
        "task_id": task_id,
        "route": route,
        "model": model,
        "payload": payload or {},
    }

    if plan_id:
        path = plan_dir(plan_id) / "events.jsonl"
    else:
        path = VAULT / ".jarvis" / "history" / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # Also mirror latest live events for HUD
    live_path = Path("/tmp/jarvis/react_events.jsonl")
    live_path.parent.mkdir(parents=True, exist_ok=True)
    with live_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    return event