"""
JARVIS Skill — Podman sandboxed code and test execution.

Auto-detects language/image from workspace contents.
Supports pytest, npm test, cargo test, go test, and arbitrary commands.
Returns structured UI result consistent with other JARVIS skills.
"""

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Skill metadata
# ---------------------------------------------------------------------------

SKILL_NAME = "podman"
SKILL_DESCRIPTION = "Run code and tests in isolated Podman containers"
SKILL_VERSION = "1.0.0"
SKILL_AUTHOR = "Sami Porokka"
SKILL_CATEGORY = "dev"
SKILL_TAGS = ["podman", "containers", "testing", "pytest", "sandbox", "ci"]
SKILL_REQUIREMENTS = ["podman"]
SKILL_CAPABILITIES = ["run_tests", "run_command", "detect_environment"]

SKILL_META = {
    "name": SKILL_NAME,
    "description": SKILL_DESCRIPTION,
    "version": SKILL_VERSION,
    "author": SKILL_AUTHOR,
    "category": SKILL_CATEGORY,
    "tags": SKILL_TAGS,
    "requirements": SKILL_REQUIREMENTS,
    "capabilities": SKILL_CAPABILITIES,
    "writes_files": False,
    "reads_files": True,
    "network_access": True,
    "entrypoint": "exec_podman",
    "route": "tools",
    "intent_aliases": ["run tests", "test code", "podman", "run container"],
    "keywords": [
        "test",
        "tests",
        "run tests",
        "pytest",
        "podman",
        "container",
        "sandbox",
        "unit test",
        "integration test",
        "run code",
    ],
    "direct_match": ["run tests", "podman run", "test my code"],
    "response_style": {
        "default": "structured_test_ui",
        "avoid_raw_dump": True,
        "followup_hint": True,
    },
}

# ---------------------------------------------------------------------------
# Image detection map
# ---------------------------------------------------------------------------

# (manifest_file, image, test_command)
MANIFEST_MAP: List[Tuple[str, str, str]] = [
    ("requirements.txt",  "python:3.12-slim",      "pip install pytest -q && pip install -r requirements.txt -q && pytest --tb=short -q"),
    ("pyproject.toml",    "python:3.12-slim",      "pip install pytest -q && pip install -e . -q 2>/dev/null || true && pytest --tb=short -q"),
    ("setup.py",          "python:3.12-slim",      "pip install pytest -q && pip install -e . -q 2>/dev/null || true && pytest --tb=short -q"),
    ("package.json",      "node:20-slim",           "npm install --silent 2>/dev/null && npm test"),
    ("Cargo.toml",        "rust:1.78-slim",         "cargo test 2>&1"),
    ("go.mod",            "golang:1.22-alpine",     "go test ./... 2>&1"),
    ("composer.json",     "php:8.3-cli-alpine",    "composer install -q 2>/dev/null && ./vendor/bin/phpunit 2>&1 || php -r 'echo \"No PHPUnit found.\";'"),
    ("Gemfile",           "ruby:3.3-slim",          "bundle install -q 2>/dev/null && bundle exec rspec 2>&1 || bundle exec rake test 2>&1"),
]

# Extension fallback when no manifest found
EXTENSION_MAP: Dict[str, Tuple[str, str]] = {
    ".py":   ("python:3.12-slim",   "pip install pytest -q && pytest --tb=short -q"),
    ".js":   ("node:20-slim",        "node ."),
    ".ts":   ("node:20-slim",        "npx ts-node ."),
    ".rs":   ("rust:1.78-slim",      "cargo test 2>&1"),
    ".go":   ("golang:1.22-alpine",  "go test ./... 2>&1"),
    ".rb":   ("ruby:3.3-slim",       "ruby -e 'puts \"No runner configured.\"'"),
    ".php":  ("php:8.3-cli-alpine",  "php -l ."),
}

DEFAULT_IMAGE   = "python:3.12-slim"
DEFAULT_COMMAND = "pip install pytest -q && pytest --tb=short -q"

OUTPUT_MAX_CHARS = 8000   # truncate container output beyond this
UI_SNIPPET_CHARS = 2000   # chars shown in UI summary

# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------

def _detect_environment(path: str) -> Tuple[str, str, str]:
    """
    Returns (image, test_command, detected_by) for a given workspace path.
    detected_by is a human-readable string explaining why this image was chosen.
    """
    workspace = Path(path).expanduser().resolve()

    if not workspace.exists():
        return DEFAULT_IMAGE, DEFAULT_COMMAND, "default (path not found)"

    # 1. Manifest files
    for manifest, image, command in MANIFEST_MAP:
        if (workspace / manifest).exists():
            return image, command, f"manifest:{manifest}"

    # 2. Dominant extension
    counts: Dict[str, int] = {}
    for f in workspace.rglob("*"):
        if f.is_file() and f.suffix in EXTENSION_MAP:
            counts[f.suffix] = counts.get(f.suffix, 0) + 1

    if counts:
        dominant = max(counts, key=lambda k: counts[k])
        image, command = EXTENSION_MAP[dominant]
        return image, command, f"extension:{dominant} ({counts[dominant]} files)"

    return DEFAULT_IMAGE, DEFAULT_COMMAND, "default (no language detected)"


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------

def _parse_pytest_output(output: str) -> Dict[str, Any]:
    """Extract pass/fail counts from pytest output."""
    passed = failed = errors = skipped = 0

    # e.g. "5 passed, 2 failed, 1 error in 3.21s"
    summary_match = re.search(
        r"(\d+) passed|(\d+) failed|(\d+) error|(\d+) skipped", output
    )

    passed_m  = re.search(r"(\d+) passed",  output)
    failed_m  = re.search(r"(\d+) failed",  output)
    error_m   = re.search(r"(\d+) error",   output)
    skipped_m = re.search(r"(\d+) skipped", output)

    if passed_m:  passed  = int(passed_m.group(1))
    if failed_m:  failed  = int(failed_m.group(1))
    if error_m:   errors  = int(error_m.group(1))
    if skipped_m: skipped = int(skipped_m.group(1))

    total = passed + failed + errors

    return {
        "passed":  passed,
        "failed":  failed,
        "errors":  errors,
        "skipped": skipped,
        "total":   total,
    }


def _parse_generic_output(output: str, exit_code: int) -> Dict[str, Any]:
    """Generic pass/fail for non-pytest runners."""
    return {
        "passed":  0 if exit_code != 0 else 1,
        "failed":  1 if exit_code != 0 else 0,
        "errors":  0,
        "skipped": 0,
        "total":   1,
    }


def _build_speech(counts: Dict[str, Any], runner: str, exit_code: int) -> str:
    if runner == "pytest" and counts["total"] > 0:
        parts = []
        if counts["passed"]:  parts.append(f"{counts['passed']} passed")
        if counts["failed"]:  parts.append(f"{counts['failed']} failed")
        if counts["errors"]:  parts.append(f"{counts['errors']} errors")
        if counts["skipped"]: parts.append(f"{counts['skipped']} skipped")
        status = "✅" if counts["failed"] == 0 and counts["errors"] == 0 else "❌"
        return f"{status} Tests: {', '.join(parts)}"
    if exit_code == 0:
        return "✅ Command completed successfully."
    return f"❌ Command exited with code {exit_code}."


# ---------------------------------------------------------------------------
# Podman execution
# ---------------------------------------------------------------------------

def _podman_available() -> bool:
    try:
        result = subprocess.run(
            ["podman", "--version"],
            capture_output=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _run_podman(
    image: str,
    workspace: str,
    command: str,
    timeout: int = 120,
    network: bool = False,
) -> Tuple[int, str]:
    """
    Run a command inside a Podman container.
    Returns (exit_code, combined_output).
    """
    workspace_path = str(Path(workspace).expanduser().resolve())

    network_flag = "bridge" if network else "none"

    podman_cmd = [
        "podman", "run", "--rm",
        "--network", network_flag,
        "--memory", "512m",
        "--cpus", "1.0",
        "--security-opt", "no-new-privileges",
        "-v", f"{workspace_path}:/workspace:z",
        "-w", "/workspace",
        image,
        "sh", "-c", command,
    ]

    try:
        result = subprocess.run(
            podman_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        # Truncate very long output
        if len(output) > OUTPUT_MAX_CHARS:
            half = OUTPUT_MAX_CHARS // 2
            output = (
                output[:half]
                + f"\n\n[... {len(output) - OUTPUT_MAX_CHARS} chars truncated ...]\n\n"
                + output[-half:]
            )
        return result.returncode, output

    except subprocess.TimeoutExpired:
        return 124, f"[TIMEOUT] Container exceeded {timeout}s limit and was killed."
    except FileNotFoundError:
        return 127, "[ERROR] podman not found. Is Podman installed and on PATH?"
    except Exception as e:
        return 1, f"[ERROR] {e}"


# ---------------------------------------------------------------------------
# Result builders
# ---------------------------------------------------------------------------

def _build_test_result(
    path: str,
    image: str,
    detected_by: str,
    command: str,
    exit_code: int,
    output: str,
    timeout: int,
    network: bool,
) -> Dict[str, Any]:

    is_pytest = "pytest" in command
    runner = "pytest" if is_pytest else "generic"

    counts = (
        _parse_pytest_output(output)
        if is_pytest
        else _parse_generic_output(output, exit_code)
    )

    speech_text = _build_speech(counts, runner, exit_code)
    snippet = output[:UI_SNIPPET_CHARS] + ("..." if len(output) > UI_SNIPPET_CHARS else "")
    success = exit_code == 0

    return {
        "ok": True,
        "speech": {
            "text": speech_text,
            "priority": "high" if not success else "normal",
        },
        "ui": {
            "placement": "tab",
            "format": "test_result",
            "title": f"Test Run — {Path(path).name}",
            "summary": speech_text,
            "items": [
                {"label": "Image",      "value": image},
                {"label": "Detected",   "value": detected_by},
                {"label": "Exit code",  "value": str(exit_code)},
                {"label": "Passed",     "value": str(counts["passed"])},
                {"label": "Failed",     "value": str(counts["failed"])},
                {"label": "Errors",     "value": str(counts["errors"])},
                {"label": "Skipped",    "value": str(counts["skipped"])},
                {"label": "Network",    "value": "enabled" if network else "isolated"},
                {"label": "Timeout",    "value": f"{timeout}s"},
            ],
            "output_snippet": snippet,
            "success": success,
            "ttl_seconds": 900,
            "closable": True,
            "actions": [
                {"type": "close_tab", "label": "Close results"},
            ],
        },
        "action": {
            "type": "open_tab",
            "payload": {
                "tab_id": "test_result",
                "label": "TESTS",
            },
        },
        "data": {
            "path":        path,
            "image":       image,
            "detected_by": detected_by,
            "command":     command,
            "exit_code":   exit_code,
            "counts":      counts,
            "success":     success,
            "plain":       output,
            "runner":      runner,
        },
    }


def _build_run_result(
    path: str,
    image: str,
    command: str,
    exit_code: int,
    output: str,
) -> Dict[str, Any]:

    success = exit_code == 0
    speech_text = (
        "✅ Command completed successfully."
        if success
        else f"❌ Command exited with code {exit_code}."
    )
    snippet = output[:UI_SNIPPET_CHARS] + ("..." if len(output) > UI_SNIPPET_CHARS else "")

    return {
        "ok": True,
        "speech": {
            "text": speech_text,
            "priority": "high" if not success else "normal",
        },
        "ui": {
            "placement": "tab",
            "format": "run_result",
            "title": f"Run — {Path(path).name}",
            "summary": speech_text,
            "items": [
                {"label": "Image",     "value": image},
                {"label": "Command",   "value": command},
                {"label": "Exit code", "value": str(exit_code)},
            ],
            "output_snippet": snippet,
            "success": success,
            "ttl_seconds": 600,
            "closable": True,
            "actions": [
                {"type": "close_tab", "label": "Close output"},
            ],
        },
        "action": {
            "type": "open_tab",
            "payload": {
                "tab_id": "run_result",
                "label": "RUN",
            },
        },
        "data": {
            "path":      path,
            "image":     image,
            "command":   command,
            "exit_code": exit_code,
            "success":   success,
            "plain":     output,
        },
    }


def _error_result(title: str, message: str, error: str = "") -> Dict[str, Any]:
    return {
        "ok": False,
        "speech": {
            "text": message,
            "priority": "high",
        },
        "ui": {
            "placement": "right-side-hud",
            "format": "status",
            "title": title,
            "summary": message,
            "ttl_seconds": 300,
        },
        "data": {
            "plain": f"{title}: {message}",
        },
        "error": error or message,
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def exec_podman(
    action: str,
    path: str = ".",
    image: Optional[str] = None,
    command: Optional[str] = None,
    timeout: int = 120,
    network: bool = False,
) -> Dict[str, Any]:
    """
    Main entrypoint for the Podman skill.

    action  : "test" | "run" | "shell"
    path    : workspace directory to mount (default: current dir)
    image   : override auto-detected image
    command : override auto-detected test/run command
    timeout : max seconds before container is killed (default 120)
    network : allow network access inside container (default False)
    """

    action = (action or "").strip().lower()

    if action not in {"test", "run", "shell"}:
        return _error_result(
            "Podman",
            "Available actions are: test, run, shell.",
            "invalid_action",
        )

    if not _podman_available():
        return _error_result(
            "Podman",
            "Podman is not available. Please install Podman and ensure it is on PATH.",
            "podman_not_found",
        )

    # Resolve workspace
    workspace = str(Path(path).expanduser().resolve())
    if not Path(workspace).exists():
        return _error_result(
            "Podman",
            f"Workspace path does not exist: {workspace}",
            "path_not_found",
        )

    # Detect or use provided image + command
    detected_image, detected_command, detected_by = _detect_environment(workspace)
    final_image   = image   or detected_image
    final_command = command or detected_command

    # --- shell: just return the podman command string, no execution ---
    if action == "shell":
        network_flag = "bridge" if network else "none"
        shell_cmd = (
            f"podman run --rm "
            f"--network {network_flag} "
            f"--memory 512m --cpus 1.0 "
            f"--security-opt no-new-privileges "
            f"-v {workspace}:/workspace:z "
            f"-w /workspace "
            f"-it {final_image} sh"
        )
        return {
            "ok": True,
            "speech": {
                "text": f"Shell command ready for {final_image}.",
                "priority": "normal",
            },
            "ui": {
                "placement": "right-side-hud",
                "format": "code",
                "title": "Podman Shell",
                "summary": shell_cmd,
                "ttl_seconds": 600,
                "closable": True,
            },
            "data": {
                "plain":   shell_cmd,
                "image":   final_image,
                "command": shell_cmd,
            },
        }

    # --- test: run auto-detected or provided test command ---
    if action == "test":
        exit_code, output = _run_podman(
            image=final_image,
            workspace=workspace,
            command=final_command,
            timeout=timeout,
            network=network,
        )
        return _build_test_result(
            path=workspace,
            image=final_image,
            detected_by=detected_by,
            command=final_command,
            exit_code=exit_code,
            output=output,
            timeout=timeout,
            network=network,
        )

    # --- run: execute an arbitrary command ---
    if action == "run":
        if not command:
            return _error_result(
                "Podman run",
                "A command is required for the run action.",
                "command_required",
            )
        exit_code, output = _run_podman(
            image=final_image,
            workspace=workspace,
            command=command,
            timeout=timeout,
            network=network,
        )
        return _build_run_result(
            path=workspace,
            image=final_image,
            command=command,
            exit_code=exit_code,
            output=output,
        )


# ---------------------------------------------------------------------------
# Skill tool definition
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "podman",
            "description": (
                "Run code or tests inside an isolated Podman container. "
                "Auto-detects language and image from workspace contents. "
                "Actions: test (run test suite), run (arbitrary command), shell (get shell command)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["test", "run", "shell"],
                        "description": "Action to perform.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative path to workspace directory. Defaults to current directory.",
                    },
                    "image": {
                        "type": "string",
                        "description": "Override auto-detected Docker/Podman image, e.g. python:3.11-slim.",
                    },
                    "command": {
                        "type": "string",
                        "description": "Override auto-detected command to run inside the container.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Maximum seconds before the container is killed. Default 120.",
                    },
                    "network": {
                        "type": "boolean",
                        "description": "Allow network access inside the container. Default false (isolated).",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "podman": exec_podman,
}

KEYWORDS = {
    "podman": [
        "test",
        "run tests",
        "pytest",
        "podman",
        "container",
        "sandbox",
        "unit test",
        "run code",
        "cargo test",
        "npm test",
        "go test",
    ],
}

SKILL_EXAMPLES = [
    {
        "command": "run tests in /home/sami/jarvis-os",
        "tool": "podman",
        "args": {"action": "test", "path": "/home/sami/jarvis-os"},
    },
    {
        "command": "test my code in /workspace/myproject",
        "tool": "podman",
        "args": {"action": "test", "path": "/workspace/myproject"},
    },
    {
        "command": "run pytest with network on /home/sami/jarvis-os",
        "tool": "podman",
        "args": {"action": "test", "path": "/home/sami/jarvis-os", "network": True},
    },
    {
        "command": "run python script in /home/sami/scripts",
        "tool": "podman",
        "args": {
            "action": "run",
            "path": "/home/sami/scripts",
            "command": "python main.py",
        },
    },
    {
        "command": "give me a shell for /home/sami/jarvis-os",
        "tool": "podman",
        "args": {"action": "shell", "path": "/home/sami/jarvis-os"},
    },
    {
        "command": "test with rust image",
        "tool": "podman",
        "args": {
            "action": "test",
            "path": "/home/sami/myproject",
            "image": "rust:1.78-slim",
        },
    },
]
