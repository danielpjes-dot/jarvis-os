"""
JARVIS Agent Executor
=====================
Runs shell and Python tasks, streams output via SSE, returns final summary.

Trigger via:
  HTTP:  POST /execute         { "task": "...", "type": "shell"|"python" }
         GET  /execute/stream  ?run_id=<id>   (SSE)
  CLI:   python agent_executor.py "your task" [--type shell|python]
"""

import asyncio
import json
import subprocess
import sys
import textwrap
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

try:
    import uvicorn
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import StreamingResponse
    from pydantic import BaseModel
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

# ─── In-memory run store ────────────────────────────────────────────────────

_runs: dict[str, dict] = {}   # run_id -> { events: [], done: bool, summary: dict }


def _new_run(run_id: str) -> dict:
    run = {"events": [], "done": False, "summary": None, "lock": asyncio.Lock()}
    _runs[run_id] = run
    return run


def _emit(run: dict, kind: str, data: str | dict):
    """Append an event to the run's event list."""
    run["events"].append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": kind,          # stdout | stderr | info | error | done
        "data": data,
    })


# ─── Core execution logic ────────────────────────────────────────────────────

async def _run_shell(run: dict, command: str):
    """Execute a shell command, streaming stdout/stderr line by line."""
    _emit(run, "info", f"$ {command}")
    start = time.monotonic()

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _stream(stream, kind: str):
        while True:
            line = await stream.readline()
            if not line:
                break
            _emit(run, kind, line.decode(errors="replace").rstrip("\n"))

    await asyncio.gather(
        _stream(proc.stdout, "stdout"),
        _stream(proc.stderr, "stderr"),
    )
    await proc.wait()

    elapsed = round(time.monotonic() - start, 3)
    success = proc.returncode == 0
    summary = {
        "type": "shell",
        "command": command,
        "returncode": proc.returncode,
        "success": success,
        "elapsed_s": elapsed,
    }
    _emit(run, "done", summary)
    run["summary"] = summary
    run["done"] = True


async def _run_python(run: dict, code: str):
    """Execute Python code in a subprocess, streaming output."""
    _emit(run, "info", "Running Python snippet...")
    start = time.monotonic()

    # Dedent so pasted code with leading spaces works
    code = textwrap.dedent(code)

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _stream(stream, kind: str):
        while True:
            line = await stream.readline()
            if not line:
                break
            _emit(run, kind, line.decode(errors="replace").rstrip("\n"))

    await asyncio.gather(
        _stream(proc.stdout, "stdout"),
        _stream(proc.stderr, "stderr"),
    )
    await proc.wait()

    elapsed = round(time.monotonic() - start, 3)
    success = proc.returncode == 0
    summary = {
        "type": "python",
        "returncode": proc.returncode,
        "success": success,
        "elapsed_s": elapsed,
    }
    _emit(run, "done", summary)
    run["summary"] = summary
    run["done"] = True


async def execute(task: str, task_type: str = "shell") -> dict:
    """
    Core entry point. Returns run_id immediately; execution runs in background.
    Await run completion via poll_run() or stream via sse_stream().
    """
    run_id = str(uuid.uuid4())
    run = _new_run(run_id)

    if task_type == "python":
        coro = _run_python(run, task)
    else:
        coro = _run_shell(run, task)

    asyncio.create_task(coro)
    return {"run_id": run_id}


async def poll_run(run_id: str, timeout: float = 60.0) -> dict:
    """Wait for a run to complete and return its full event log + summary."""
    run = _runs.get(run_id)
    if not run:
        raise KeyError(f"Unknown run_id: {run_id}")

    deadline = time.monotonic() + timeout
    while not run["done"]:
        if time.monotonic() > deadline:
            raise TimeoutError(f"Run {run_id} did not complete within {timeout}s")
        await asyncio.sleep(0.1)

    return {
        "run_id": run_id,
        "summary": run["summary"],
        "events": run["events"],
    }


async def sse_stream(run_id: str) -> AsyncGenerator[str, None]:
    """
    Yield SSE-formatted events for a run.
    Streams in real-time as events are emitted, then closes on 'done'.
    """
    run = _runs.get(run_id)
    if not run:
        yield f"event: error\ndata: {json.dumps({'error': 'unknown run_id'})}\n\n"
        return

    cursor = 0
    while True:
        events = run["events"]
        while cursor < len(events):
            ev = events[cursor]
            cursor += 1
            yield f"event: {ev['kind']}\ndata: {json.dumps(ev)}\n\n"
            if ev["kind"] == "done":
                return
        if run["done"] and cursor >= len(run["events"]):
            return
        await asyncio.sleep(0.05)


# ─── FastAPI app ─────────────────────────────────────────────────────────────

if HAS_FASTAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(title="JARVIS Agent Executor", lifespan=lifespan)

    class ExecuteRequest(BaseModel):
        task: str
        type: str = "shell"   # "shell" | "python"

    @app.post("/execute")
    async def http_execute(req: ExecuteRequest):
        """Start a task. Returns run_id for streaming or polling."""
        result = await execute(req.task, req.type)
        return result

    @app.get("/execute/stream")
    async def http_stream(run_id: str):
        """SSE stream of events for a run."""
        if run_id not in _runs:
            raise HTTPException(status_code=404, detail="Unknown run_id")
        return StreamingResponse(
            sse_stream(run_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/execute/result")
    async def http_result(run_id: str, timeout: float = 30.0):
        """Block until done, return full result JSON."""
        try:
            result = await poll_run(run_id, timeout=timeout)
            return result
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown run_id")
        except TimeoutError as e:
            raise HTTPException(status_code=408, detail=str(e))

    @app.get("/execute/runs")
    async def http_list_runs():
        """List all run IDs and their done status."""
        return {
            rid: {"done": r["done"], "success": r["summary"]["success"] if r["summary"] else None}
            for rid, r in _runs.items()
        }


# ─── CLI entry point ─────────────────────────────────────────────────────────

async def _cli_main():
    import argparse

    parser = argparse.ArgumentParser(description="JARVIS Agent Executor CLI")
    parser.add_argument("task", help="Shell command or Python code to run")
    parser.add_argument("--type", choices=["shell", "python"], default="shell",
                        help="Execution type (default: shell)")
    parser.add_argument("--serve", action="store_true",
                        help="Start the HTTP server instead of running a task")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    if args.serve:
        if not HAS_FASTAPI:
            print("FastAPI/uvicorn not installed. pip install fastapi uvicorn")
            sys.exit(1)
        uvicorn.run("agent_executor:app", host=args.host, port=args.port, reload=False)
        return

    # Run task, print events as they arrive, then print summary
    run_id = (await execute(args.task, args.type))["run_id"]
    run = _runs[run_id]

    print(f"[executor] run_id={run_id}  type={args.type}")
    print("─" * 60)

    cursor = 0
    while True:
        events = run["events"]
        while cursor < len(events):
            ev = events[cursor]
            cursor += 1
            kind = ev["kind"]
            data = ev["data"]
            if kind == "stdout":
                print(data)
            elif kind == "stderr":
                print(f"\033[33m{data}\033[0m", file=sys.stderr)
            elif kind == "info":
                print(f"\033[36m[info]\033[0m {data}")
            elif kind == "error":
                print(f"\033[31m[error]\033[0m {data}", file=sys.stderr)
            elif kind == "done":
                break
        if run["done"]:
            break
        await asyncio.sleep(0.05)

    print("─" * 60)
    s = run["summary"]
    status = "\033[32m✓ success\033[0m" if s["success"] else f"\033[31m✗ failed (rc={s['returncode']})\033[0m"
    print(f"[executor] {status}  elapsed={s['elapsed_s']}s")


if __name__ == "__main__":
    # If --serve flag present, hand off to uvicorn (blocking)
    if "--serve" in sys.argv:
        if not HAS_FASTAPI:
            print("FastAPI/uvicorn not installed. pip install fastapi uvicorn")
            sys.exit(1)
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("task", nargs="?", default="")
        p.add_argument("--type", default="shell")
        p.add_argument("--serve", action="store_true")
        p.add_argument("--port", type=int, default=8765)
        p.add_argument("--host", default="127.0.0.1")
        args = p.parse_args()
        uvicorn.run("agent_executor:app", host=args.host, port=args.port, reload=False)
    else:
        asyncio.run(_cli_main())
