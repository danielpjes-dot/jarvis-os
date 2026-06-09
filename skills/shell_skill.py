"""
JARVIS Skill — Shell execution and file staging.

Runs shell commands via the PTY WebSocket server and manages files
through the staging pipeline (dev → tested → approved).
"""

import asyncio
import json
import os
import shutil
import time
from pathlib import Path

SKILL_NAME = "shell"
SKILL_DESCRIPTION = "Run shell commands on the JARVIS host and read/write files in the staging pipeline (dev → tested → approved)"

# ── Config ────────────────────────────────────────────────────────────────────

PTY_PORT     = int(os.getenv("JARVIS_PTY_PORT", 8766))
STAGING_ROOT = Path(os.getenv("JARVIS_STAGING", "/mnt/e/coding/staging"))
PIPELINE     = ["dev", "tested", "approved"]

# ── PTY WebSocket helper ──────────────────────────────────────────────────────

async def _shell_async(cmd: str, timeout: float = 60.0) -> dict:
    """
    Send cmd to the PTY WebSocket server, collect streamed output.
    Expects frames: {type: stdout|stderr|done, data?, returncode?}
    Returns {stdout, stderr, returncode, success, elapsed_s}
    """
    try:
        import websockets
    except ImportError:
        return {
            "stdout": "",
            "stderr": "websockets not installed — run: pip install websockets",
            "returncode": -1,
            "success": False,
            "elapsed_s": 0,
        }

    import websockets as ws_lib

    uri = f"ws://localhost:{PTY_PORT}"
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    start = time.monotonic()

    try:
        async with ws_lib.connect(uri, open_timeout=5) as ws:
            await ws.send(json.dumps({"cmd": cmd}))
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    return {
                        "stdout": "\n".join(stdout_lines),
                        "stderr": f"Timed out after {timeout}s",
                        "returncode": -1,
                        "success": False,
                        "elapsed_s": round(time.monotonic() - start, 3),
                    }
                frame = json.loads(raw)
                ftype = frame.get("type")
                if ftype == "stdout":
                    stdout_lines.append(frame.get("data", ""))
                elif ftype == "stderr":
                    stderr_lines.append(frame.get("data", ""))
                elif ftype == "done":
                    rc = frame.get("returncode", 0)
                    return {
                        "stdout": "\n".join(stdout_lines),
                        "stderr": "\n".join(stderr_lines),
                        "returncode": rc,
                        "success": rc == 0,
                        "elapsed_s": round(time.monotonic() - start, 3),
                    }
    except OSError as e:
        return {
            "stdout": "",
            "stderr": f"PTY server not reachable at ws://localhost:{PTY_PORT}: {e}",
            "returncode": -1,
            "success": False,
            "elapsed_s": round(time.monotonic() - start, 3),
        }


def _run_shell(cmd: str, timeout: float = 60.0) -> dict:
    """Sync wrapper — runs the async PTY call in a new event loop."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Inside an already-running loop (e.g. FastAPI): schedule as task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _shell_async(cmd, timeout))
                return future.result()
        return loop.run_until_complete(_shell_async(cmd, timeout))
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1, "success": False, "elapsed_s": 0}


# ── File helpers ──────────────────────────────────────────────────────────────

def _validate_folder(folder: str):
    if folder not in PIPELINE:
        raise ValueError(f"Invalid folder '{folder}'. Must be one of: {PIPELINE}")


def _stage_path(folder: str, filename: str) -> Path:
    _validate_folder(folder)
    return STAGING_ROOT / folder / filename


def read_file(path: str) -> dict:
    """
    Read any file on the filesystem.
    - Absolute path (starts with / or drive letter): used as-is, e.g. '/mnt/e/coding/jarvis-os/agent_loop.py'
    - Relative path: resolved relative to STAGING_ROOT, e.g. 'dev/agent.py'
    Returns {success, path, content} or {success, error}.
    """
    full = Path(path) if Path(path).is_absolute() else STAGING_ROOT / path
    try:
        content = full.read_text(encoding="utf-8")
        return {"success": True, "path": str(full), "content": content}
    except FileNotFoundError:
        return {"success": False, "error": f"File not found: {full}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def write_file(filename: str, content: str, folder: str = "dev") -> dict:
    """
    Write content to staging/{folder}/{filename}.
    Always writes to dev/ by default — never directly to tested/ or approved/.
    Backs up existing file before overwriting.
    Returns {success, path} or {success, error}.
    """
    _validate_folder(folder)
    full = _stage_path(folder, filename)
    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        # Backup if exists
        if full.exists():
            backup = full.with_suffix(full.suffix + ".bak")
            shutil.copy2(full, backup)
        full.write_text(content, encoding="utf-8")
        return {"success": True, "path": str(full)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def promote_file(filename: str, from_folder: str, to_folder: str) -> dict:
    """
    Move a file one stage forward in the pipeline.
    Only valid moves: dev→tested, tested→approved.
    Returns {success, path} or {success, error}.
    """
    try:
        _validate_folder(from_folder)
        _validate_folder(to_folder)
        if PIPELINE.index(to_folder) != PIPELINE.index(from_folder) + 1:
            return {"success": False, "error": f"Can only promote one stage at a time ({from_folder} → {to_folder} is invalid)"}
        src  = _stage_path(from_folder, filename)
        dest = _stage_path(to_folder,   filename)
        if not src.exists():
            return {"success": False, "error": f"Source file not found: {src}"}
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        return {"success": True, "path": str(dest)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_stage(folder: str = "dev") -> dict:
    """List files in a staging folder."""
    try:
        _validate_folder(folder)
        base = STAGING_ROOT / folder
        base.mkdir(parents=True, exist_ok=True)
        files = sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file())
        return {"success": True, "folder": folder, "files": files}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Tool executors ────────────────────────────────────────────────────────────

DESTRUCTIVE_PATTERNS = ("rm -rf", "dd if=", "mkfs", ":(){:|:&};:", "> /dev/sd")

def exec_shell(cmd: str, confirmed: bool = False) -> str:
    """Execute a shell command via the PTY server."""
    # Guard destructive commands
    for pattern in DESTRUCTIVE_PATTERNS:
        if pattern in cmd and not confirmed:
            return (
                f"Blocked: '{pattern}' detected. "
                "Pass confirmed=true explicitly to allow destructive commands."
            )

    result = _run_shell(cmd)
    parts = []
    if result["stdout"]:
        parts.append(result["stdout"])
    if result["stderr"]:
        parts.append(f"[stderr] {result['stderr']}")
    parts.append(
        f"[{'✓' if result['success'] else '✗'} rc={result['returncode']} {result['elapsed_s']}s]"
    )
    return "\n".join(parts)


def exec_read_file(path: str) -> str:
    """Read any file — absolute path or relative to staging."""
    r = read_file(path)
    if r["success"]:
        return r["content"]
    return f"Error: {r['error']}"


def exec_write_file(filename: str, content: str, folder: str = "dev") -> str:
    """Write a file to staging (dev by default)."""
    r = write_file(filename, content, folder)
    if r["success"]:
        return f"Written to {r['path']}"
    return f"Error: {r['error']}"


def exec_promote(filename: str, from_folder: str, to_folder: str) -> str:
    """Promote a file one stage forward in the pipeline."""
    r = promote_file(filename, from_folder, to_folder)
    if r["success"]:
        return f"Promoted → {r['path']}"
    return f"Error: {r['error']}"


def exec_list_stage(folder: str = "dev") -> str:
    """List files in a staging folder."""
    r = list_stage(folder)
    if r["success"]:
        if not r["files"]:
            return f"staging/{folder}/ is empty"
        return f"staging/{folder}/:\n" + "\n".join(f"  {f}" for f in r["files"])
    return f"Error: {r['error']}"


# ── Tool definitions (OpenAI-style, same as radio.py) ────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": (
                "Run a shell command on the JARVIS host via the PTY server. "
                "Use for any system task: git, python scripts, file ops, service checks, installs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {
                        "type": "string",
                        "description": "Shell command to execute.",
                    },
                    "confirmed": {
                        "type": "boolean",
                        "description": "Set true to allow destructive commands (rm -rf, dd, mkfs). Default false.",
                    },
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read any file on the JARVIS host filesystem. "
                "Accepts absolute paths (e.g. '/mnt/e/coding/jarvis-os/agent_loop.py', '/mnt/d/Jarvis_vault/note.md') "
                "or paths relative to the staging root (e.g. 'dev/agent.py')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path or staging-relative path to the file.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write content to a file in the staging workspace. "
                "New files always go to dev/ first. "
                "Existing files are backed up before overwriting."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Filename (no folder prefix), e.g. 'agent.py'.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full file content to write.",
                    },
                    "folder": {
                        "type": "string",
                        "enum": ["dev", "tested", "approved"],
                        "description": "Target staging folder. Defaults to 'dev'.",
                    },
                },
                "required": ["filename", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "promote_file",
            "description": (
                "Move a file one stage forward in the pipeline: dev→tested or tested→approved. "
                "Only call after verifying the file works correctly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Filename to promote, e.g. 'agent.py'.",
                    },
                    "from_folder": {
                        "type": "string",
                        "enum": ["dev", "tested"],
                        "description": "Current stage.",
                    },
                    "to_folder": {
                        "type": "string",
                        "enum": ["tested", "approved"],
                        "description": "Target stage.",
                    },
                },
                "required": ["filename", "from_folder", "to_folder"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_stage",
            "description": "List files in a staging folder (dev, tested, or approved).",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "enum": ["dev", "tested", "approved"],
                        "description": "Staging folder to list. Defaults to 'dev'.",
                    }
                },
                "required": [],
            },
        },
    },
]

TOOL_MAP = {
    "shell":        lambda args: exec_shell(args["cmd"], args.get("confirmed", False)),
    "read_file":    lambda args: exec_read_file(args["path"]),
    "write_file":   lambda args: exec_write_file(args["filename"], args["content"], args.get("folder", "dev")),
    "promote_file": lambda args: exec_promote(args["filename"], args["from_folder"], args["to_folder"]),
    "list_stage":   lambda args: exec_list_stage(args.get("folder", "dev")),
}

KEYWORDS = {
    "shell":        ["run", "execute", "shell", "bash", "command", "script", "git", "python", "install", "check", "restart"],
    "read_file":    ["read", "open", "show", "cat", "view", "file", "load", "staging"],
    "write_file":   ["write", "save", "create", "generate", "file", "code", "staging", "dev"],
    "promote_file": ["promote", "move", "advance", "tested", "approved", "pipeline", "stage"],
    "list_stage":   ["list", "ls", "show files", "what's in", "staging", "dev", "tested", "approved"],
}
