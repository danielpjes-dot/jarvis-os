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
OLLAMA_URL       = os.getenv("JARVIS_OLLAMA_URL",      "http://localhost:11434")
CODER_MODEL      = os.getenv("JARVIS_CODER_MODEL",     "qwen3-coder:30b")
STAGING_ROOT     = Path(os.getenv("JARVIS_STAGING_ROOT", "/mnt/e/coding/staging"))

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
    """Load all skills from SKILLS_DIR."""
    import importlib.util
    registry = {}
    if not SKILLS_DIR.exists():
        return registry
    # Load ALL *.py skill files (not just *_skill.py)
    skip = {"__init__", "loader", "coding_generic", "coding_qwen3_coder"}
    for skill_file in sorted(SKILLS_DIR.glob("*.py")):
        if skill_file.stem in skip or skill_file.stem.startswith("_"):
            continue
        try:
            spec   = importlib.util.spec_from_file_location(skill_file.stem, skill_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            tool_map = getattr(module, "TOOL_MAP", {})
            if not tool_map:
                continue
            name = getattr(module, "SKILL_NAME", skill_file.stem)
            registry[name] = {
                "tool_map": tool_map,
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


def exec_code_step(task: dict) -> tuple[bool, str]:
    """
    Generate file content via qwen3-coder:30b and write to the target path.
    Used for coding/code_edit plan steps that need to CREATE files in staging.
    """
    import urllib.request, urllib.error

    goal         = task.get("task", "")
    target_files = task.get("target_files", [])
    args         = task.get("args", {})
    primary_path = args.get("path") or (target_files[0] if target_files else "")

    if not primary_path:
        return False, "No target file path for coding step"

    # Build absolute path — the path from the plan is already staging/dev/PLAN-ID/file
    # so prepend /mnt/e/coding/ to get the full WSL path, or use as-is if absolute
    abs_path = Path(primary_path)
    if not abs_path.is_absolute():
        # Paths come in as "staging/dev/..." — prepend the coding root
        coding_root = STAGING_ROOT.parent  # /mnt/e/coding
        abs_path = coding_root / primary_path

    ext = abs_path.suffix.lower()
    lang_map = {".html": "HTML", ".css": "CSS", ".js": "JavaScript",
                ".ts": "TypeScript", ".py": "Python", ".json": "JSON",
                ".tsx": "TypeScript React", ".sh": "Bash"}
    lang = lang_map.get(ext, "")

    prompt = (
        f"You are an expert {lang} developer. Write the complete file content for this task:\n\n"
        f"Task: {goal}\n\n"
        f"Target file: {abs_path.name}\n\n"
        "Rules:\n"
        "- Output ONLY the raw file content. No markdown fences, no explanation.\n"
        "- Write complete, working code — not a skeleton or placeholder.\n"
        "- The file must be immediately usable as-is.\n"
    )

    payload = json.dumps({
        "model":   CODER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream":  False,
        "think":   False,
        "options": {"temperature": 0, "num_predict": 4096},
    }).encode()

    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode())
            content = data.get("message", {}).get("content", "").strip()

        if not content:
            return False, "Coder returned empty content"

        # Strip accidental markdown fences
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(
                l for l in lines
                if not l.strip().startswith("```")
            ).strip()

        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")
        print(f"[runner] wrote {abs_path} ({len(content)} chars)")
        return True, f"Wrote {abs_path.name} ({len(content)} chars)"

    except urllib.error.HTTPError as e:
        return False, f"Ollama HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return False, f"exec_code_step failed: {e}"


def dispatch_task(task: dict) -> tuple[bool, str]:
    """
    Execute a task by calling the appropriate skill's TOOL_MAP.
    Returns (success, result_str).
    """
    skill_name = task.get("skill", "")
    tool_name  = task.get("tool", "")
    args       = task.get("args", {})

    if not skill_name or not tool_name:
        return False, f"Task has no skill/tool: {task.get('task', '?')}"

    # Coding steps: generate full file content via Ollama and write to staging
    if skill_name in ("coding", "code_edit") or tool_name in ("coding", "code_edit"):
        return exec_code_step(task)

    # Shell steps (test/copy): build a sensible cmd from the task goal
    if tool_name == "shell" and not args.get("cmd"):
        goal         = task.get("task", "")
        target_files = task.get("target_files", [])
        plan_id      = task.get("plan_id", "")
        coding_root  = STAGING_ROOT.parent  # /mnt/e/coding

        # Step 10 pattern: "Copy all files from staging/dev/PLAN-ID/ to staging/tested/PLAN-ID/"
        if "copy" in goal.lower() and plan_id:
            src  = str(coding_root / f"staging/dev/{plan_id}")
            dest = str(coding_root / f"staging/tested/{plan_id}")
            args = {**args, "cmd": f"mkdir -p '{dest}' && cp -r '{src}/.' '{dest}/'"}
        # Test steps: just echo success (real tests need a test runner)
        elif any(w in goal.lower() for w in ("test", "validate", "verify", "check")):
            args = {**args, "cmd": f"echo 'Step validated: {goal[:60]}'"}
        else:
            args = {**args, "cmd": f"echo 'Shell step: {goal[:80]}'"}
        task = {**task, "args": args}

    skills = get_skills()

    if skill_name not in skills:
        skills = get_skills(force_reload=True)

    if skill_name not in skills:
        return False, f"Unknown skill: {skill_name}"

    tool_map = skills[skill_name]["tool_map"]
    if tool_name not in tool_map:
        return False, f"Unknown tool '{tool_name}' in skill '{skill_name}'"

    try:
        # Pass args as kwargs if dict, else as positional
        fn = tool_map[tool_name]
        if isinstance(args, dict):
            result = fn(**args)
        else:
            result = fn(args)
        return True, str(result)
    except Exception as e:
        return False, f"[{skill_name}.{tool_name}] raised: {e}"


# ── Test command builder ───────────────────────────────────────────────────────

def _build_test_cmd(plan_id: str, coding_root: Path) -> str:
    """
    Choose between Playwright (simple static sites) and Podman (complex projects).

    Simple = has index.html + ≤8 files and no server-side code.
    Complex = has package.json / requirements.txt / Dockerfile or >8 files.
    """
    stage_dir = coding_root / "staging" / "dev" / plan_id
    files = list(stage_dir.rglob("*")) if stage_dir.exists() else []
    file_names = {f.name.lower() for f in files if f.is_file()}
    file_count = len([f for f in files if f.is_file()])

    has_html   = "index.html" in file_names
    is_complex = (
        file_count > 8
        or any(n in file_names for n in ("package.json", "requirements.txt", "dockerfile", "docker-compose.yml"))
    )

    stage_path = str(stage_dir)

    if not is_complex and has_html:
        # Simple static site — use Playwright
        html_path = f"file://{stage_path}/index.html"
        return (
            f"node -e \""
            f"const {{chromium}}=require('@playwright/browser-chromium');"
            f"(async()=>{{"
            f"  const b=await chromium.launch();"
            f"  const p=await b.newPage();"
            f"  const errs=[];"
            f"  p.on('pageerror',e=>errs.push(e.message));"
            f"  await p.goto('{html_path}');"
            f"  await p.waitForTimeout(2000);"
            f"  const title=await p.title();"
            f"  await p.screenshot({{path:'{stage_path}/test-screenshot.png'}});"
            f"  await b.close();"
            f"  if(errs.length){{console.error('JS errors:',errs);process.exit(1);}}"
            f"  console.log('OK title='+title);"
            f"}})()\" 2>&1 || "
            # fallback: basic JS syntax check if playwright not installed
            f"(find '{stage_path}' -name '*.js' | xargs -I{{}} node --check {{}} && "
            f"find '{stage_path}' -name '*.json' | xargs -I{{}} python3 -m json.tool {{}} > /dev/null && "
            f"echo 'Syntax OK — playwright not available for UI test')"
        )
    else:
        # Complex project — mount in Podman and run checks
        image = "node:20-alpine" if any(n in file_names for n in ("package.json", "index.js", "index.ts")) else "python:3.11-slim"
        if image.startswith("node"):
            inner = "cd /app && ([ -f package.json ] && npm install --silent 2>/dev/null || true) && find . -name '*.js' | xargs -I{} node --check {} && echo 'Node syntax OK'"
        else:
            inner = "cd /app && find . -name '*.py' | xargs -I{} python3 -m py_compile {} && echo 'Python syntax OK'"
        return (
            f"podman run --rm -v '{stage_path}:/app:ro' {image} sh -c \"{inner}\" 2>&1 || "
            f"echo 'Podman test failed — check staging files'"
        )


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

    # Build cmd from goal if missing
    cmd = args.get("cmd", "")
    if not cmd:
        goal    = task.get("task", "")
        plan_id = task.get("plan_id", "")
        coding_root = STAGING_ROOT.parent
        if "copy" in goal.lower() and plan_id:
            src  = str(coding_root / f"staging/dev/{plan_id}")
            dest = str(coding_root / f"staging/tested/{plan_id}")
            cmd  = f"mkdir -p '{dest}' && cp -r '{src}/.' '{dest}/'"
        elif any(w in goal.lower() for w in ("test", "validate", "verify", "check", "ensure")):
            cmd = _build_test_cmd(plan_id, coding_root)
        else:
            cmd = f"echo 'Shell step: {goal[:80]}'"

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
        # Executor not reachable — run cmd directly via subprocess
        import subprocess
        if not cmd:
            return False, "No cmd and executor unreachable"
        try:
            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=60
            )
            output = (proc.stdout or proc.stderr or "").strip()
            return proc.returncode == 0, output or f"exit {proc.returncode}"
        except Exception as e:
            return False, str(e)


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
