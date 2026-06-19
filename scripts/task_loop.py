#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path
from typing import Any


DEFAULT_VAULT = Path("/mnt/d/Jarvis_vault")
POLL_SECONDS = 10


def vault_root() -> Path:
    return Path(os.environ.get("JARVIS_VAULT", DEFAULT_VAULT))


def task_dir() -> Path:
    p = vault_root() / ".jarvis" / "tasks"
    p.mkdir(parents=True, exist_ok=True)
    return p


def tasks_path() -> Path:
    return task_dir() / "tasks.json"


def results_path() -> Path:
    return task_dir() / "results.jsonl"


def now_ts() -> float:
    return time.time()


def log_result(task_id: str, status: str, message: str, extra: dict[str, Any] | None = None) -> None:
    row = {
        "ts": now_ts(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "task_id": task_id,
        "status": status,
        "message": message,
        "extra": extra or {},
    }

    with results_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def default_tasks() -> list[dict[str, Any]]:
    return [
        {
            "id": "update_aaak_context",
            "type": "system",
            "enabled": True,
            "interval_seconds": 300,
            "action": "update_aaak_context",
            "args": {
                "minutes": 15,
                "model": "qwen3:8b",
            },
            "last_run": 0,
        }
    ]


def load_tasks() -> list[dict[str, Any]]:
    path = tasks_path()

    if not path.exists():
        tasks = default_tasks()
        save_tasks(tasks)
        return tasks

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("tasks"), list):
            return data["tasks"]
    except Exception as e:
        log_result("task_loop", "error", f"Failed to read tasks.json: {e}")

    return []


def save_tasks(tasks: list[dict[str, Any]]) -> None:
    tmp = tasks_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(tasks_path())


def should_run(task: dict[str, Any], ts: float) -> bool:
    if not task.get("enabled", True):
        return False

    interval = int(task.get("interval_seconds", 0))
    if interval <= 0:
        return False

    last_run = float(task.get("last_run", 0))
    return ts - last_run >= interval


def run_update_aaak_context(task: dict[str, Any]) -> str:
    from chat_context import update_aaak_context

    args = task.get("args") or {}
    minutes = int(args.get("minutes", 15))
    model = str(args.get("model", "qwen3:8b"))

    path = update_aaak_context(minutes=minutes, model=model)
    return f"AAAK context updated: {path}"


def run_task(task: dict[str, Any]) -> str:
    action = task.get("action")

    if action == "update_aaak_context":
        return run_update_aaak_context(task)

    raise ValueError(f"Unknown task action: {action}")


def main() -> None:
    print("[TASK_LOOP] started")
    print(f"[TASK_LOOP] vault={vault_root()}")
    print(f"[TASK_LOOP] tasks={tasks_path()}")

    while True:
        tasks = load_tasks()
        ts = now_ts()
        changed = False

        for task in tasks:
            task_id = str(task.get("id", "unknown"))

            if not should_run(task, ts):
                continue

            print(f"[TASK_LOOP] running {task_id}")

            try:
                message = run_task(task)
                task["last_run"] = now_ts()
                task["last_status"] = "ok"
                task["last_message"] = message
                changed = True

                log_result(task_id, "ok", message)
                print(f"[TASK_LOOP] ok {task_id}: {message}")

            except Exception as e:
                err = str(e)
                task["last_run"] = now_ts()
                task["last_status"] = "error"
                task["last_message"] = err
                changed = True

                log_result(
                    task_id,
                    "error",
                    err,
                    {"traceback": traceback.format_exc()},
                )
                print(f"[TASK_LOOP] error {task_id}: {err}")

        if changed:
            save_tasks(tasks)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()