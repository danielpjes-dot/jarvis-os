"""
JARVIS Plan Runner
==================
Redis consumer that executes plan tasks queued by planner_skill.
Bridges the gap between planner (queues tasks) and agent_loop (dispatches skills).

Architecture:
  planner_skill.exec_plan()
      → pushes {skill, tool, args, plan_id, task_id, depends_on} to Redis
          ↓
  plan_runner (this file — runs as daemon)
      → pops tasks respecting depends_on order
      → calls agent_loop.dispatch(decision)
      → streams results via agent_executor SSE (for shell/python tasks)
      → writes status back to Redis
      → on completion: calls planner_skill.promote_to_tested(plan_id)

Usage:
  python plan_runner.py              # daemon mode
  python plan_runner.py --once       # process one task and exit
  uvicorn plan_runner:app --port 8766  # HTTP status API
"""

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

# ── Config ─────────────────────────────────────────────────────────────────────

REDIS_HOST       = os.getenv("JARVIS_REDIS_HOST",    "localhost")
REDIS_PORT       = int(os.getenv("JARVIS_REDIS_PORT", 6379))
REDIS_TASKS_KEY  = "jarvis:tasks"
REDIS_PLANS_KEY  = "jarvis:plans"
REDIS_STATUS_KEY = "jarvis:task_status"   # hash: task_uid → status JSON
REDIS_RESULTS_KEY = "jarvis:task_results" # hash: task_uid → result string

SKILLS_DIR       = Path(os.getenv("JARVIS_SKILLS_DIR", "/mnt/e/coding/jarvis-os/skills"))
EXECUTOR_URL     = os.getenv("JARVIS_EXECUTOR_URL",    "http://localhost:8765")
AGENT_LOOP_URL   = os.getenv("JARVIS_LOOP_URL",        "http://localhost:8100")

POLL_INTERVAL    = 0.5   # seconds between Redis polls
DEP_TIMEOUT      = 300   # seconds to wait for a dependency to complete
MAX_RETRIES      = 2     # retry failed tasks this many times

# ── Redis ──────────────────────────────────────────────────────────────────────

def _redis():
    try:
        import redis
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        r.ping()
        return r
    except ImportError:
        raise RuntimeError("pip install redis")
    except Exception as e:
        raise RuntimeError(f"Redis not reachable: {e}")


def _set_status(r, task_uid: str, status: str, detail: str = ""):
    r.hset(REDIS_STATUS_KEY, task_uid, json.dumps({
        "status":    status,   # queued | waiting | running | done | failed
        "detail":    detail,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }))


def _get_status(r, task_uid: str) -> Optional[dict]:
    raw = r.hget(REDIS_STATUS_KEY, task_uid)
    return json.loads(raw) if raw else None


def _set_result(r, task_uid: str, result: str):
    r.hset(REDIS_RESULTS_KEY, task_uid, result)


def _get_result(r, task_uid: str) -> Optional[str]:
    return r.hget(REDIS_RESULTS_KEY, task_uid)


# ── Dependency resolver ────────────────────────────────────────────────────────

def _task_uid(task: dict) -> str:
    """Stable unique ID for a task within a plan."""
    return f"{task.get('plan_id', 'no_plan')}:{task.get('task_id', 0)}"


async def _wait_for_deps(r, task: dict) -> tuple[bool, str]:
    """
    Wait for all depends_on tasks to reach 'done' status.
    Returns (ok, error_msg).
    """
    deps      = task.get("depends_on", [])
    plan_id   = task.get("plan_id", "")
    if not deps:
        return True, ""

    deadline = time.monotonic() + DEP_TIMEOUT
    while time.monotonic() < deadline:
        all_done = True
        for dep_id in deps:
            dep_uid    = f"{plan_id}:{dep_id}"
            dep_status = _get_status(r, dep_uid)
            if dep_status is None or dep_status["status"] not in ("done",):
                if dep_status and dep_status["status"] == "failed":
                    return False, f"Dependency task {dep_id} failed"
                all_done = False
                break
        if all_done:
            return True, ""
        await asyncio.sleep(1.0)

    return False, f"Timed out waiting for dependencies {deps}"


# ── Skill dispatcher ───────────────────────────────────────────────────────────

def _load_skills() -> dict:
    """Load all skills from SKILLS_DIR (same logic as agent_loop)."""
    import importlib.util
    registry = {}
    if not SKILLS_DIR.exists():
        return registry
    for skill_file in sorted(SKILLS_DIR.glob("*_skill.py")):
        try:
            spec   = importlib.util.spec_from_file_location(skill_file.stem, skill_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            name = getattr(module, "SKILL_NAME", skill_file.stem)
            registry[name] = {
                "tool_map": getattr(module, "TOOL_MAP", {}),
                "description": getattr(module, "SKILL_DESCRIPTION", ""),
            }
        except Exception as e:
            print(f"[runner] skill load error {skill_file.name}: {e}")
    return registry


_skills_cache: dict = {}
_skills_loaded_at: float = 0


def get_skills(force_reload: bool = False) -> dict:
    global _skills_cache, _skills_loaded_at
    now = time.monotonic()
    if force_reload or not _skills_cache or (now - _skills_loaded_at) > 30:
        _skills_cache   = _load_skills()
        _skills_loaded_at = now
    return _skills_cache


def dispatch_task(task: dict) -> tuple[bool, str]:
    """
    Execute a task by calling the appropriate skill's TOOL_MAP.
    For shell/python tasks also runs through executor for streaming.
    Returns (success, result_str).
    """
    skill_name = task.get("skill")
    tool_name  = task.get("tool")
    args       = task.get("args", {})

    if not skill_name or not tool_name:
        return False, f"Task has no skill/tool: {task.get('task', '?')}"

    skills = get_skills()

    # Reload skills if plan just added new ones to SKILLS_DIR
    if skill_name not in skills:
        skills = get_skills(force_reload=True)

    if skill_name not in skills:
        return False, f"Unknown skill: {skill_name}"

    tool_map = skills[skill_name]["tool_map"]
    if tool_name not in tool_map:
        return False, f"Unknown tool '{tool_name}' in skill '{skill_name}'"

    try:
        result = tool_map[tool_name](args)
        return True, str(result)
    except Exception as e:
        return False, f"[{skill_name}.{tool_name}] raised: {e}"


# ── Shell/python task via executor ─────────────────────────────────────────────

async def dispatch_via_executor(task: dict) -> tuple[bool, str]:
    """
    For shell.shell and shell.run_command tasks, use the executor
    HTTP API for PTY-based execution with real streaming.
    Falls back to direct dispatch if executor unreachable.
    """
    import urllib.request
    import urllib.error

    skill = task.get("skill")
    tool  = task.get("tool")
    args  = task.get("args", {})

    # Only shell exec tasks go through executor
    if skill != "shell" or tool not in ("shell", "run_command"):
        return dispatch_task(task)

    cmd = args.get("cmd", "")
    if not cmd:
        return False, "No cmd in args"

    try:
        # Start execution
        payload = json.dumps({"task": cmd, "type": "shell"}).encode()
        req = urllib.request.Request(
            f"{EXECUTOR_URL}/execute",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            run_id = json.loads(resp.read())["run_id"]

        # Poll for result
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            poll_req = urllib.request.Request(
                f"{EXECUTOR_URL}/execute/result?run_id={run_id}&timeout=5",
                method="GET",
            )
            try:
                with urllib.request.urlopen(poll_req, timeout=10) as resp:
                    result = json.loads(resp.read())
                    summary = result.get("summary", {})
                    stdout  = "\n".join(
                        e["data"] for e in result.get("events", [])
                        if e["kind"] == "stdout"
                    )
                    return summary.get("success", False), stdout or str(summary)
            except urllib.error.HTTPError as e:
                if e.code == 408:
                    continue   # still running
                raise

        return False, "Executor timed out"

    except Exception:
        # Executor not reachable — fall back to direct skill dispatch
        return dispatch_task(task)


# ── Plan completion check ──────────────────────────────────────────────────────

def _check_plan_complete(r, plan_id: str) -> tuple[bool, int, int]:
    """
    Check if all tasks in a plan are done.
    Returns (all_done, done_count, total_count).
    """
    raw = r.hget(REDIS_PLANS_KEY, plan_id)
    if not raw:
        return False, 0, 0

    plan   = json.loads(raw)
    tasks  = plan.get("tasks", [])
    total  = len(tasks)
    done   = 0
    failed = 0

    for t in tasks:
        uid    = _task_uid(t)
        status = _get_status(r, uid)
        if status:
            if status["status"] == "done":
                done += 1
            elif status["status"] == "failed":
                failed += 1

    return (done + failed) == total, done, total


def _plan_summary(r, plan_id: str) -> str:
    """Build a human-readable plan completion summary."""
    raw = r.hget(REDIS_PLANS_KEY, plan_id)
    if not raw:
        return f"Plan {plan_id} not found in Redis"

    plan   = json.loads(raw)
    tasks  = plan.get("tasks", [])
    lines  = [f"Plan {plan_id} complete: {plan.get('goal', '?')}\n"]

    for t in tasks:
        uid    = _task_uid(t)
        status = _get_status(r, uid)
        result = _get_result(r, uid)
        s      = status["status"] if status else "unknown"
        icon   = "✓" if s == "done" else ("✗" if s == "failed" else "?")
        lines.append(f"  [{icon}] Task {t.get('task_id')}: {t.get('task','?')[:60]}")
        if result and s == "failed":
            lines.append(f"       Error: {result[:100]}")

    return "\n".join(lines)


# ── Main runner loop ───────────────────────────────────────────────────────────

async def run_once(r) -> Optional[dict]:
    """
    Pop one task from Redis, execute it, update status.
    Returns the task dict or None if queue empty.
    """
    raw = r.lpop(REDIS_TASKS_KEY)
    if not raw:
        return None

    task     = json.loads(raw)
    task_uid = _task_uid(task)
    plan_id  = task.get("plan_id", "")
    retries  = task.get("_retries", 0)

    print(f"[runner] task {task_uid}  {task.get('skill','?')}.{task.get('tool','?')}"
          f"  plan={plan_id}")

    # Wait for dependencies
    _set_status(r, task_uid, "waiting", f"deps={task.get('depends_on', [])}")
    ok, dep_err = await _wait_for_deps(r, task)
    if not ok:
        _set_status(r, task_uid, "failed", dep_err)
        _set_result(r, task_uid, dep_err)
        print(f"[runner] ✗ dep failed: {dep_err}")
        return task

    # Execute
    _set_status(r, task_uid, "running")
    start   = time.monotonic()

    skill = task.get("skill", "")
    tool  = task.get("tool", "")
    is_shell_exec = (skill == "shell" and tool in ("shell", "run_command"))

    try:
        if is_shell_exec:
            success, result = await dispatch_via_executor(task)
        else:
            success, result = dispatch_task(task)
    except Exception as e:
        success, result = False, str(e)

    elapsed = round(time.monotonic() - start, 2)

    if success:
        _set_status(r, task_uid, "done", f"elapsed={elapsed}s")
        _set_result(r, task_uid, result)
        print(f"[runner] ✓ {task_uid}  ({elapsed}s)")
    else:
        if retries < MAX_RETRIES:
            # Re-queue with retry counter
            task["_retries"] = retries + 1
            r.rpush(REDIS_TASKS_KEY, json.dumps(task))
            _set_status(r, task_uid, "queued", f"retry {retries+1}/{MAX_RETRIES}")
            print(f"[runner] ↺ {task_uid} retry {retries+1}")
        else:
            _set_status(r, task_uid, "failed", result[:200])
            _set_result(r, task_uid, result)
            print(f"[runner] ✗ {task_uid}: {result[:100]}")

    # Check if this completes the plan
    if plan_id:
        all_done, done, total = _check_plan_complete(r, plan_id)
        if all_done:
            summary = _plan_summary(r, plan_id)
            print(f"\n[runner] {'='*50}")
            print(summary)
            print(f"[runner] {'='*50}\n")
            # Publish completion event
            r.publish(f"jarvis:plan:{plan_id}:done", json.dumps({
                "plan_id": plan_id,
                "done": done,
                "total": total,
                "summary": summary,
            }))

    return task


async def daemon():
    """Main daemon loop — continuously pops and executes tasks from Redis."""
    print(f"[runner] JARVIS Plan Runner starting")
    print(f"[runner] Redis: {REDIS_HOST}:{REDIS_PORT}")
    print(f"[runner] Skills: {SKILLS_DIR}")
    print(f"[runner] Executor: {EXECUTOR_URL}")

    try:
        r = _redis()
        print(f"[runner] Redis connected ✓")
    except RuntimeError as e:
        print(f"[runner] ✗ {e}")
        sys.exit(1)

    # Initial skill load
    skills = get_skills()
    print(f"[runner] Loaded {len(skills)} skills: {', '.join(skills.keys())}")
    print(f"[runner] Polling every {POLL_INTERVAL}s...\n")

    idle_count = 0
    while True:
        try:
            task = await run_once(r)
            if task is None:
                idle_count += 1
                if idle_count % 60 == 0:  # log every 30s when idle
                    depth = r.llen(REDIS_TASKS_KEY)
                    print(f"[runner] idle  queue_depth={depth}")
                await asyncio.sleep(POLL_INTERVAL)
            else:
                idle_count = 0
        except Exception as e:
            print(f"[runner] loop error: {e}")
            await asyncio.sleep(2.0)


# ── FastAPI status API ─────────────────────────────────────────────────────────

try:
    from fastapi import FastAPI
    app = FastAPI(title="JARVIS Plan Runner")

    @app.get("/status")
    def status():
        r = _redis()
        return {
            "queue_depth": r.llen(REDIS_TASKS_KEY),
            "plans":       r.hlen(REDIS_PLANS_KEY),
            "skills":      list(get_skills().keys()),
        }

    @app.get("/plan/{plan_id}")
    def plan_status(plan_id: str):
        r = _redis()
        all_done, done, total = _check_plan_complete(r, plan_id)
        return {
            "plan_id":  plan_id,
            "done":     done,
            "total":    total,
            "complete": all_done,
            "summary":  _plan_summary(r, plan_id) if all_done else None,
        }

    @app.get("/plan/{plan_id}/tasks")
    def plan_tasks(plan_id: str):
        r = _redis()
        raw = r.hget(REDIS_PLANS_KEY, plan_id)
        if not raw:
            return {"error": "plan not found"}
        plan  = json.loads(raw)
        tasks = []
        for t in plan.get("tasks", []):
            uid    = _task_uid(t)
            status = _get_status(r, uid) or {}
            result = _get_result(r, uid)
            tasks.append({
                "task_id": t.get("task_id"),
                "task":    t.get("task"),
                "skill":   t.get("skill"),
                "tool":    t.get("tool"),
                "status":  status.get("status", "unknown"),
                "result":  result[:200] if result else None,
            })
        return {"plan_id": plan_id, "goal": plan.get("goal"), "tasks": tasks}

    @app.post("/reload-skills")
    def reload_skills():
        skills = get_skills(force_reload=True)
        return {"loaded": list(skills.keys())}

except ImportError:
    app = None


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--serve" in sys.argv:
        import uvicorn
        uvicorn.run("plan_runner:app", host="127.0.0.1", port=8766, reload=False)
    elif "--once" in sys.argv:
        r = _redis()
        asyncio.run(run_once(r))
    else:
        asyncio.run(daemon())
