#!/usr/bin/env python3
import json
from pathlib import Path
from dataclasses import asdict
import os
from typing import TypedDict, List, Dict, Any

class PlanStep(TypedDict):
    id: int
    status: str
    goal: str

class PlanState(TypedDict):
    plan_id: str
    current_step: int
    steps: List[PlanStep]
    user_request: str
    
VAULT_DIR = Path(
    os.environ.get(
        "JARVIS_VAULT_DIR",
        "D:/Jarvis_vault" if os.name == "nt" else "/mnt/d/Jarvis_vault",
    )
)
PLANNER_DIR = Path(VAULT_DIR) / ".jarvis" / "planner"
PLANS_DIR = PLANNER_DIR / "plans"
PLANNER_MEMORY_PATH = PLANNER_DIR / "planner_memory.md"


def save_plan(state: PlanState) -> None:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)

    path = PLANS_DIR / f"{state.plan_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(asdict(state), f, indent=2, ensure_ascii=False)


def load_plan(plan_id: str) -> PlanState:
    path = PLANS_DIR / f"{plan_id}.json"

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    steps = [PlanStep(**step) for step in raw.get("steps", [])]

    return PlanState(
        plan_id=raw["plan_id"],
        steps=steps,
        current_step=raw.get("current_step", 0),
        context=raw.get("context", {}),
    )


def list_plans() -> list[str]:
    if not PLANS_DIR.exists():
        return []

    return sorted(
        path.stem for path in PLANS_DIR.glob("*.json")
    )


def append_planner_memory(entry: str, max_chars: int = 16000) -> None:
    PLANNER_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    old = ""
    if PLANNER_MEMORY_PATH.exists():
        old = PLANNER_MEMORY_PATH.read_text(
            encoding="utf-8",
            errors="ignore",
        )

    text = (old.rstrip() + "\n\n" + entry.strip()).strip()

    if len(text) > max_chars:
        text = text[-max_chars:]

    PLANNER_MEMORY_PATH.write_text(text + "\n", encoding="utf-8")


def load_planner_memory(max_chars: int = 4000) -> str:
    if not PLANNER_MEMORY_PATH.exists():
        return ""

    text = PLANNER_MEMORY_PATH.read_text(
        encoding="utf-8",
        errors="ignore",
    ).strip()

    if not text:
        return ""

    if len(text) > max_chars:
        text = text[-max_chars:]

    return f"Previous planning memory:\n{text}"