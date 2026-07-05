# skills/plan.py
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional


VAULT_DIR = Path(os.getenv("VAULT_DIR", "/mnt/d/Jarvis_vault"))
PLANNER_DIR = VAULT_DIR / ".jarvis" / "planner"
ACTIVE_PLAN_FILE = PLANNER_DIR / "active_plan.json"


def _safe_plan_id(plan_id: str) -> str:
    plan_id = str(plan_id).strip()
    if not plan_id:
        raise ValueError("Missing plan_id")
    if "/" in plan_id or "\\" in plan_id or ".." in plan_id:
        raise ValueError("Unsafe plan_id")
    return plan_id


def _plan_dir(plan_id: str) -> Path:
    return PLANNER_DIR / "plans" / _safe_plan_id(plan_id)


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _find_plan_file(plan_id: str) -> Path:
    pdir = _plan_dir(plan_id)
    candidates = [
        pdir / "plan.json",
        pdir / "active_plan.json",
        pdir / f"{plan_id}.json",
    ]

    for p in candidates:
        if p.exists():
            return p

    jsons = sorted(pdir.glob("*.json"))
    if jsons:
        return jsons[0]

    raise FileNotFoundError(f"No plan JSON found for {plan_id}")


def list_plans(limit: int = 20) -> Dict[str, Any]:
    plans_root = PLANNER_DIR / "plans"
    items: List[Dict[str, Any]] = []

    if plans_root.exists():
        for pdir in sorted(plans_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not pdir.is_dir():
                continue

            plan_id = pdir.name
            try:
                pfile = _find_plan_file(plan_id)
                data = _read_json(pfile)
            except Exception:
                data = {}

            items.append({
                "plan_id": plan_id,
                "title": data.get("title") or data.get("goal") or data.get("task") or "(untitled)",
                "status": data.get("status") or data.get("state") or "unknown",
                "steps": len(data.get("steps") or []),
                "modified": pdir.stat().st_mtime,
            })

            if len(items) >= int(limit):
                break

    active = None
    if ACTIVE_PLAN_FILE.exists():
        try:
            active_data = _read_json(ACTIVE_PLAN_FILE)
            active = active_data.get("plan_id")
        except Exception:
            active = None

    return {
        "ok": True,
        "active_plan_id": active,
        "count": len(items),
        "plans": items,
    }


def show_plan(plan_id: Optional[str] = None) -> Dict[str, Any]:
    if not plan_id:
        if not ACTIVE_PLAN_FILE.exists():
            return {"ok": False, "error": "No active plan and no plan_id provided"}
        data = _read_json(ACTIVE_PLAN_FILE)
        return {"ok": True, "source": str(ACTIVE_PLAN_FILE), "plan": data}

    pfile = _find_plan_file(plan_id)
    data = _read_json(pfile)
    return {"ok": True, "source": str(pfile), "plan": data}


def edit_plan(plan_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(updates, dict):
        return {"ok": False, "error": "updates must be a JSON object"}

    pfile = _find_plan_file(plan_id)
    data = _read_json(pfile)

    protected = {"plan_id"}
    for key, value in updates.items():
        if key in protected:
            continue
        data[key] = value

    _write_json(pfile, data)

    if ACTIVE_PLAN_FILE.exists():
        try:
            active = _read_json(ACTIVE_PLAN_FILE)
            if active.get("plan_id") == plan_id:
                _write_json(ACTIVE_PLAN_FILE, data)
        except Exception:
            pass

    return {
        "ok": True,
        "message": f"Updated plan {plan_id}",
        "source": str(pfile),
        "plan": data,
    }


def delete_plan(plan_id: str, archive: bool = True) -> Dict[str, Any]:
    plan_id = _safe_plan_id(plan_id)
    pdir = _plan_dir(plan_id)

    if not pdir.exists():
        return {"ok": False, "error": f"Plan not found: {plan_id}"}

    if archive:
        archive_dir = PLANNER_DIR / "deleted_plans"
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / plan_id

        if target.exists():
            target = archive_dir / f"{plan_id}_{int(pdir.stat().st_mtime)}"

        shutil.move(str(pdir), str(target))
        deleted_path = str(target)
    else:
        shutil.rmtree(pdir)
        deleted_path = str(pdir)

    if ACTIVE_PLAN_FILE.exists():
        try:
            active = _read_json(ACTIVE_PLAN_FILE)
            if active.get("plan_id") == plan_id:
                ACTIVE_PLAN_FILE.unlink()
        except Exception:
            pass

    return {
        "ok": True,
        "message": f"Deleted plan {plan_id}",
        "archived": archive,
        "path": deleted_path,
    }


def rerun_plan(plan_id: Optional[str] = None) -> Dict[str, Any]:
    """Re-queue an existing plan under a new versioned ID (FOO → FOO-2 → FOO-3)."""
    if not plan_id:
        if not ACTIVE_PLAN_FILE.exists():
            return {"ok": False, "error": "No active plan and no plan_id provided"}
        try:
            data = _read_json(ACTIVE_PLAN_FILE)
            plan_id = data.get("plan_id")
        except Exception as e:
            return {"ok": False, "error": str(e)}
        if not plan_id:
            return {"ok": False, "error": "Could not determine plan_id from active plan"}

    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from plan_runner import rerun_plan as _rerun
        return _rerun(plan_id)
    except Exception as e:
        return {"ok": False, "error": f"rerun failed: {e}"}


def run(args: Dict[str, Any] | None = None) -> Dict[str, Any]:
    args = args or {}
    action = str(args.get("action", "list")).lower().strip()

    try:
        if action == "list":
            return list_plans(limit=int(args.get("limit", 20)))

        if action == "show":
            return show_plan(args.get("plan_id"))

        if action == "edit":
            return edit_plan(
                plan_id=args["plan_id"],
                updates=args.get("updates") or {},
            )

        if action == "delete":
            return delete_plan(
                plan_id=args["plan_id"],
                archive=bool(args.get("archive", True)),
            )

        if action == "rerun":
            return rerun_plan(args.get("plan_id"))

        return {
            "ok": False,
            "error": f"Unknown action: {action}",
            "valid_actions": ["list", "show", "edit", "delete", "rerun"],
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}


SKILL = {
    "name": "plan",
    "description": "List, show, edit, and delete Jarvis planner plans.",
    "intent_aliases": [
        "list plans",
        "show plan",
        "edit plan",
        "delete plan",
        "remove plan",
        "current plan",
        "active plan",
        "rerun plan",
        "retry plan",
        "run plan again",
    ],
    "keywords": [
        "plan",
        "plans",
        "planner",
        "active plan",
        "delete plan",
        "edit plan",
        "show plan",
        "rerun plan",
        "retry plan",
    ],
    "args_schema": {
        "action": "list | show | edit | delete | rerun",
        "plan_id": "optional for show, required for edit/delete",
        "updates": "JSON object for edit",
        "limit": "optional for list",
        "archive": "optional bool for delete, default true",
    },
    "run": run,
}