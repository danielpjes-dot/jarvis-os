"""
JARVIS Skill — n8n workflow control.

Allows Jarvis to:
- check n8n health
- list workflows
- get workflow details
- call webhook-based workflows
- list executions
- get execution details
"""

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional
from pathlib import Path

SKILL_NAME = "n8n"
SKILL_DESCRIPTION = "Control n8n workflows and trigger automations"
SKILL_VERSION = "1.0.0"
SKILL_AUTHOR = "Sami Porokka"
SKILL_CATEGORY = "automation"
SKILL_TAGS = ["n8n", "workflow", "automation", "webhook", "integration"]
SKILL_REQUIREMENTS = []
SKILL_CAPABILITIES = [
    "health",
    "list_workflows",
    "get_workflow",
    "run_webhook",
    "list_executions",
    "get_execution",
    "add_task",
    "create_task",
    "send_event",
]

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
    "reads_files": False,
    "network_access": True,
    "entrypoint": "exec_n8n",
    "route": "tools",
    "intent_aliases": ["n8n", "workflow", "automation", "run workflow", "add task", "create task", "send task to n8n"],
    "keywords": ["n8n", "workflow", "automation", "webhook", "trigger workflow", "add task", "create task", "n8n task"],
    "direct_match": ["n8n", "run workflow", "trigger workflow", "add task to n8n", "create n8n task"],
    "response_style": {
        "default": "structured_status_ui",
        "avoid_raw_dump": True,
        "followup_hint": True,
    },
}

N8N_BASE_URL = (
    os.environ.get("N8N_EDITOR_URL")
    or os.environ.get("N8N_WEBHOOK_URL")
    or os.environ.get("N8N_BASE_URL")
    or "http://127.0.0.1:5678"
).rstrip("/")

# Jarvis events API — n8n calls this to push tasks/events back into Jarvis
JARVIS_EVENTS_URL = os.environ.get("JARVIS_API_URL", "http://127.0.0.1:7900")

# Default webhook paths for common task flows (override in .env.n8n.local)
N8N_TASK_WEBHOOK   = os.environ.get("N8N_TASK_WEBHOOK",   "/webhook/jarvis-task")
N8N_EVENT_WEBHOOK  = os.environ.get("N8N_EVENT_WEBHOOK",  "/webhook/jarvis-event")

N8N_WEBHOOK_URL = (
    os.environ.get("N8N_WEBHOOK_URL")
    or N8N_BASE_URL
).rstrip("/")

N8N_API_KEY = os.environ.get("N8N_API_KEY", "")
N8N_USER = os.environ.get("N8N_USER", "")
N8N_PASSWORD = os.environ.get("N8N_PASSWORD", "")

from pathlib import Path


def _load_env_file(path: str) -> None:
    env_path = Path(__file__).resolve().parent / path
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file("../infra/.env.n8n.local")
_load_env_file("../infra/.env.local")

def _headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Jarvis-n8n-skill/1.0",
    }
    if N8N_API_KEY:
        headers["X-N8N-API-KEY"] = N8N_API_KEY
    return headers


def _request(
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    if not path.startswith("/"):
        path = "/" + path

    url = f"{N8N_BASE_URL}{path}"

    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        if query:
            url += "?" + query

    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        method=method.upper(),
        headers=_headers(),
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw) if raw else {}
            except Exception:
                body = {"text": raw}

            return {
                "ok": True,
                "status": resp.status,
                "url": url,
                "data": body,
            }

    except Exception as e:
        return {
            "ok": False,
            "url": url,
            "error": str(e),
        }


def _status_result(title: str, message: str, ok: bool, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "ok": ok,
        "speech": {
            "text": message,
            "priority": "normal",
        },
        "ui": {
            "placement": "right-side-hud",
            "format": "status",
            "title": title,
            "summary": message,
            "ttl_seconds": 300,
        },
        "data": data or {
            "plain": f"{title}: {message}",
        },
    }


def exec_n8n(
    action: str,
    workflow_id: str = "",
    execution_id: str = "",
    webhook_path: str = "",
    payload: Optional[Dict[str, Any]] = None,
    active: Optional[bool] = None,
    status: str = "",
    limit: int = 20,
) -> Dict[str, Any]:
    action = (action or "").strip().lower()
    payload = payload or {}

    if action == "health":
        result = _request("GET", "/healthz")
        return _status_result(
            "n8n health",
            "n8n is reachable." if result.get("ok") else "n8n health check failed.",
            bool(result.get("ok")),
            result,
        )

    if action == "list_workflows":
        result = _request(
            "GET",
            "/api/v1/workflows",
            params={"active": str(active).lower() if active is not None else None},
        )
        return _status_result(
            "n8n workflows",
            "Workflow list fetched." if result.get("ok") else "Could not fetch n8n workflows.",
            bool(result.get("ok")),
            result,
        )

    if action == "get_workflow":
        if not workflow_id:
            return _status_result("n8n workflow", "Missing workflow_id.", False)
        result = _request("GET", f"/api/v1/workflows/{workflow_id}")
        return _status_result(
            "n8n workflow",
            "Workflow fetched." if result.get("ok") else "Could not fetch workflow.",
            bool(result.get("ok")),
            result,
        )

    if action == "run_webhook":
        if not webhook_path:
            return _status_result("n8n webhook", "Missing webhook_path.", False)

        result = _request("POST", webhook_path, payload=payload)
        return _status_result(
            "n8n webhook",
            "n8n webhook triggered." if result.get("ok") else "n8n webhook trigger failed.",
            bool(result.get("ok")),
            result,
        )

    if action == "list_executions":
        result = _request(
            "GET",
            "/api/v1/executions",
            params={
                "workflowId": workflow_id or None,
                "status": status or None,
                "limit": int(limit or 20),
            },
        )
        return _status_result(
            "n8n executions",
            "Executions fetched." if result.get("ok") else "Could not fetch executions.",
            bool(result.get("ok")),
            result,
        )

    if action == "get_execution":
        if not execution_id:
            return _status_result("n8n execution", "Missing execution_id.", False)
        result = _request("GET", f"/api/v1/executions/{execution_id}")
        return _status_result(
            "n8n execution",
            "Execution fetched." if result.get("ok") else "Could not fetch execution.",
            bool(result.get("ok")),
            result,
        )

    # ── Add task: trigger n8n task workflow, then n8n calls back Jarvis ──────
    if action in ("add_task", "create_task"):
        task_text = (payload or {}).get("task") or (payload or {}).get("goal") or ""
        if not task_text:
            return _status_result("n8n task", "Missing task/goal in payload.", False)

        wh_path = webhook_path or N8N_TASK_WEBHOOK
        task_payload = {
            "task":        task_text,
            "source":      "jarvis",
            "callback_url": f"{JARVIS_EVENTS_URL}/api/events",
            **(payload or {}),
        }
        result = _request("POST", wh_path, payload=task_payload)
        return _status_result(
            "n8n task",
            f"Task sent to n8n: {task_text[:60]}" if result.get("ok") else f"Failed to send task to n8n: {result.get('error', '')}",
            bool(result.get("ok")),
            result,
        )

    # ── Send event to n8n (notify n8n of Jarvis events) ──────────────────────
    if action == "send_event":
        event_type = (payload or {}).get("type", "jarvis_event")
        wh_path    = webhook_path or N8N_EVENT_WEBHOOK
        result = _request("POST", wh_path, payload={
            "type":    event_type,
            "source":  "jarvis",
            **(payload or {}),
        })
        return _status_result(
            "n8n event",
            "Event sent to n8n." if result.get("ok") else f"Failed: {result.get('error', '')}",
            bool(result.get("ok")),
            result,
        )

    return _status_result(
        "n8n",
        "Unknown action. Use health, list_workflows, get_workflow, run_webhook, list_executions, or get_execution.",
        False,
    )


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "n8n",
            "description": "Control n8n workflows. Use webhooks to trigger workflows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "health",
                            "list_workflows",
                            "get_workflow",
                            "run_webhook",
                            "list_executions",
                            "get_execution",
                            "add_task",
                            "create_task",
                            "send_event",
                        ],
                        "description": "add_task/create_task: send a task to n8n task workflow (n8n calls back /api/events when done). send_event: push a Jarvis event to n8n.",
                    },
                    "workflow_id": {"type": "string"},
                    "execution_id": {"type": "string"},
                    "webhook_path": {
                        "type": "string",
                        "description": "Webhook path, e.g. /webhook/invoice-processing",
                    },
                    "payload": {
                        "type": "object",
                        "description": "JSON payload sent to the n8n webhook",
                    },
                    "active": {"type": "boolean"},
                    "status": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "n8n": exec_n8n,
}

KEYWORDS = {
    "n8n": [
        "n8n",
        "workflow",
        "run workflow",
        "trigger workflow",
        "automation",
        "webhook",
    ],
}

SKILL_EXAMPLES = [
    {
        "command": "check n8n health",
        "tool": "n8n",
        "args": {"action": "health"},
    },
    {
        "command": "list n8n workflows",
        "tool": "n8n",
        "args": {"action": "list_workflows"},
    },
    {
        "command": "run invoice processing workflow",
        "tool": "n8n",
        "args": {
            "action": "run_webhook",
            "webhook_path": "/webhook/invoice-processing",
            "payload": {"company": "Poro-IT OÜ"},
        },
    },
]