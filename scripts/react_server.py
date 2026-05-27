"""
JARVIS ReAct Server v3 — tool-augmented Ollama proxy with shared model routing,
profile-aware prompting, dynamic skill discovery, better logging, runtime mode
resolution, and Claude Code–style behavior.

Important coder-route behavior:
- qwen3-coder models do NOT receive native Ollama tools.
- code route + coder model executes the local coding skill directly.
- coding skill is expected to read files and call qwen3-coder itself.

Endpoints:
  POST /api/chat
  GET  /api/health
  GET  /api/skills
  GET  /api/models
  GET  /api/events
  GET  /api/coding-log
  GET  /api/timers
  GET  /api/radio
  GET  /api/network
  GET  /api/self
  GET  /api/runtime-mode
  GET  /api/reload

Usage:
  python scripts/react_server.py --port 7900
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import re
import urllib.error
import urllib.request
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from difflib import SequenceMatcher
from scripts.context_router import build_context_pack
from scripts.chat_context import today_log_path, log_chat_event
from scripts.agent_loop import run_agent_loop
from services.communications_gateway import CommunicationsGateway
from services.telegram_gateway import TelegramGateway
from scripts.jarvis_history import make_plan_id, save_json, append_event, plan_dir
from skills.loader import (  # type: ignore
    get_all_keywords,
    get_all_skill_meta,
    get_all_tool_map,
    get_all_tools,
    get_loaded_skills,
    load_skills,
)
from scripts.model_config import (  # type: ignore
    get_planner_model,
    load_model_config,
    resolve_model,
)


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
TELEGRAM_MAX_MESSAGE_CHARS = 3500
TELEGRAM_NOTIFY_CHAT_ID = os.environ.get("JARVIS_TELEGRAM_CHAT_ID", "6987301428")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
KOKORO_HOST = os.environ.get("KOKORO_HOST", "http://127.0.0.1:8081")
KOKORO_TIMEOUT_SEC = int(os.environ.get("KOKORO_TIMEOUT_SEC", "5"))
KOKORO_VOICE = os.environ.get("KOKORO_VOICE", "bm_george")
PORT = (
    int(sys.argv[sys.argv.index("--port") + 1])
    if "--port" in sys.argv
    else int(os.environ.get("JARVIS_PORT", "7900"))
)
TELEGRAM_ENABLED = int(os.environ.get("JARVIS_TELEGRAM_ENABLED", "1"))
VALID_ROUTES = {"live", "fast", "tools", "reason", "code", "deep"}



MODE_PROFILE_PATH = PROJECT_ROOT / "config" / "mode_profiles.json"

MAX_ITERATIONS = int(os.environ.get("JARVIS_MAX_ITERATIONS", "8"))
MAX_TOOL_SELECTION = int(os.environ.get("JARVIS_MAX_TOOL_SELECTION", "6"))
MAX_CONTEXT_MESSAGES = int(os.environ.get("JARVIS_MAX_CONTEXT_MESSAGES", "12"))
PLANNER_TIMEOUT_SEC = int(os.environ.get("JARVIS_PLANNER_TIMEOUT_SEC", "120"))
CHAT_TIMEOUT_SEC = int(os.environ.get("JARVIS_CHAT_TIMEOUT_SEC", "600"))
TOOL_RESULT_CHAR_LIMIT = int(os.environ.get("JARVIS_TOOL_RESULT_CHAR_LIMIT", "12000"))

ENABLE_TTS_ACK = os.environ.get("JARVIS_ENABLE_TTS_ACK", "1") == "1"
ENABLE_STREAM_STATUS = os.environ.get("JARVIS_ENABLE_STREAM_STATUS", "1") == "1"
DEBUG = os.environ.get("JARVIS_DEBUG", "1") == "1"

VAULT_DIR = Path(
    os.environ.get(
        "JARVIS_VAULT_DIR",
        "D:/Jarvis_vault" if os.name == "nt" else "/mnt/d/Jarvis_vault",
    )
)
TOOL_USAGE_PATH = VAULT_DIR / ".jarvis" / "tool_usage.json"
PROMPTS_DIR = VAULT_DIR / ".jarvis" / "prompts"
LIVE_ROUTER_PROMPT_PATH = PROMPTS_DIR / "live_router.txt"
LIVE_CHAT_PROMPT_PATH = PROMPTS_DIR / "live_chat.txt"
PLANNER_PROMPT_PATH = PROMPTS_DIR / "planner.txt"
CODER_PROMPT_PATH = PROMPTS_DIR / "coder.txt"
COMMUNICATIONS = CommunicationsGateway(VAULT_DIR)
TELEGRAM_GATEWAY = TelegramGateway(VAULT_DIR)
BRIDGE_DIR = Path(os.environ.get("JARVIS_BRIDGE_DIR", "/tmp/jarvis"))
RUNTIME_MODE_PATH = BRIDGE_DIR / "runtime_mode.json"
EVENTS_FILE = BRIDGE_DIR / "react_events.jsonl"
POWERSHELL = os.environ.get(
    "JARVIS_POWERSHELL",
    "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
)
TASK_GRAPH_PATH = VAULT_DIR / ".jarvis" / "tasks" / "task_graph.json"
ACTIVE_PROFILE_PATH = VAULT_DIR / ".jarvis" / "active_profile.json"
PROFILES_DIR = VAULT_DIR / ".jarvis" / "profiles"
SETTINGS_PATH = VAULT_DIR / ".jarvis" / "settings.json"
KOKORO_ENABLED = os.environ.get("JARVIS_KOKORO_ENABLED", "0") == "1"
WORKFLOW_STATE_PATH = VAULT_DIR / ".jarvis" / "workflow_state.json"
NO_TOOLS_MODELS: set[str] = set()
stage_start_events = {"plan", "code_phase", "tool_start", "agent_start", "agent_step"}
stage_end_events = {"tool_result", "code_step_ready", "agent_final", "final", "warning"}
DEFAULT_MODE_PROFILES: Dict[str, Any] = {
    "defaults": {
        "fast": {"mode": "conversation", "persona": "jarvis", "tts_engine": "kokoro", "tts_enabled": True},
        "tools": {"mode": "tools", "persona": "jarvis", "tts_engine": "kokoro", "tts_enabled": True},
        "code": {"mode": "deep_engineer", "persona": "the_one", "tts_engine": "fallback", "tts_enabled": False},
        "deep": {"mode": "deep_reasoning", "persona": "architect", "tts_engine": "fallback", "tts_enabled": False},
        "reason": {"mode": "analysis", "persona": "jarvis", "tts_engine": "kokoro", "tts_enabled": True},
    },
    "tool_overrides": [
        {
            "route": "tools",
            "tools_any": ["room_command", "radio", "plex", "volume"],
            "mode": "shield",
            "persona": "shield_hill",
            "tts_engine": "kokoro",
            "tts_enabled": True,
        }
    ],
}
LLAMA_CPP_HOST = os.environ.get("LLAMA_CPP_HOST", "http://127.0.0.1:8081")
LLAMA_CPP_ROUTES = {
    r.strip()
    for r in os.environ.get("JARVIS_LLAMA_CPP_ROUTES", "live,fast").split(",")
    if r.strip()
}

SYSTEM_ORCHESTRATOR_PROMPT = """You are JARVIS, a capable local coding and systems assistant.

Operating mode:
- You have access to TTS and what your replies are spoken aloud by Orpheus, a local TTS engine. Use it for acknowledgments and when it adds to the user experience, but you can skip it for internal thoughts or when a quick response is best.
- Be concise, direct, and action-oriented.
- Use tools when they will materially improve accuracy.
- Do not call tools speculatively.
- Prefer one strong tool call over many weak ones.
- When using tools, think step-by-step internally but return only the answer.
- If tool results are incomplete, say what is known and what is missing.
- For engineering tasks, act like an implementation partner: diagnose, modify, verify, and summarize.
- Keep momentum. Avoid hedging unless uncertainty is real.
- Respond humanly and be personable and remove unnecessary technical jargon when possible, but be precise and technically rigorous when needed.
- Remove special characters from tool results that are not relevant to the user-facing answer, such as markdown formatting, unless they are needed for clarity.
- Call all weekdays with full name, e.g. "Monday", not "Mon" or "Mon.".
- Make dates and times human-friendly, e.g. "2024-06-01T14:30:00Z" becomes "First of June, 2024 at 2:30 PM UTC".

When modifying code:

- NEVER rewrite the whole file unless explicitly asked
- ALWAYS prefer minimal patches
- Preserve existing structure, imports, and logic
- Only change the exact functions relevant to the request
- If adding functionality, wrap it in helper functions
- Do NOT remove existing behavior unless explicitly required
- Keep diffs small and surgical

Output format:

1. Explain what will change (1–3 lines)
2. Show ONLY the modified parts (diff-style or clearly scoped blocks)
3. Do NOT output full file unless asked

Tool rules:
- Only call tools that are relevant to the user's current request.
- Use exact tool names and JSON arguments.
- After tool results arrive, integrate them and continue toward a final answer.
- If no tools are needed, answer directly.
"""
CODER_WORKSPACE_HINT = """
You are coding inside the local workspace.

Default code root:
/mnt/e/coding

If the user asks to fix, edit, inspect, or create a skill:
- First look under /mnt/e/coding for project folders.
- Prefer folders that contain a skills/ directory.
- If exactly one matching project exists, proceed.
- If multiple matching projects exist, ask which project folder to use.
- If the user mentions JARVIS, jarvis-os, React server, coding skill, news skill, or local assistant, assume:
  /mnt/e/coding/jarvis-os

For skill files:
- Skills are usually under:
  /mnt/e/coding/jarvis-os/skills
- Example:
  news skill = /mnt/e/coding/jarvis-os/skills/news.py
  coding skill = /mnt/e/coding/jarvis-os/skills/coding_qwen3_coder.py

Do not run coding_review automatically unless explicitly requested.
For normal fix/edit requests, read the relevant file, make the smallest safe patch, and return only the patch or exact changed code.
"""


MODE_PROMPTS: Dict[str, str] = {
    "fast": """Respond quickly and directly.
Keep the answer lean unless the user clearly wants depth.
""",
    "tools": """Act as a precise tool-using operator.
Focus on selecting the right tools, calling them with correct arguments,
and integrating the results clearly and efficiently.
Prefer short direct answers unless deeper explanation is needed.
""",
    "reason": """Act as a high-competence analyst and technical advisor.
Be structured, practical, and evidence-oriented.
""",
    "code": """Act as an expert software engineer and systems debugger.
Work like a senior implementation partner.

Priorities:
- understand the code before changing it
- diagnose root cause, not just symptoms
- prefer minimal correct fixes
- preserve existing working behavior
- when relevant, explain exactly what changed and why
- for debugging, identify the failure point and verify the fix
- for architecture and code review, be concrete and technically rigorous
- do not give vague advice when exact implementation guidance is possible
- when asked to modify code, produce production-quality changes
""",
    "deep": """Act as a senior strategist, architect, and analyst.
Use deeper reasoning, compare alternatives, and make justified recommendations.
""",
}

ACKS = ["On it.", "Working.", "Understood.", "Processing now.", "Let me handle that."]
#------------------------------------------------------------------------------
# Kokoro
#------------------------------------------------------------------------------
def is_kokoro_running() -> bool:
    if not KOKORO_ENABLED:
        return False
    return http_get_ok_simple(f"{KOKORO_HOST}/health", timeout=2)


def speak_kokoro(text: str, voice: str | None = None) -> bool:
    if not KOKORO_ENABLED:
        return False

    payload = {
        "text": sanitize_for_tts(text),
        "voice": voice or KOKORO_VOICE,
    }

    try:
        req = urllib.request.Request(
            f"{KOKORO_HOST}/speak",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=KOKORO_TIMEOUT_SEC):
            pass
        return True
    except Exception as e:
        debug(f"Kokoro TTS failed: {e}")
        return False
# -----------------------------------------------------------------------------
# Skill loading
# -----------------------------------------------------------------------------
def load_tool_usage() -> dict:
    try:
        return json.loads(TOOL_USAGE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_tool_usage(data: dict) -> None:
    TOOL_USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOOL_USAGE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(TOOL_USAGE_PATH)


def increment_tool_usage(tool_name: str) -> None:
    data = load_tool_usage()
    row = data.get(tool_name, {"count": 0})
    row["count"] = int(row.get("count", 0)) + 1
    row["last_used"] = now_iso()
    data[tool_name] = row
    save_tool_usage(data)
def write_chat_log(role: str, content: str, route: str = "", model: str = "") -> None:
    if not log_chat_event:
        print("[CHAT_LOG] log_chat_event not available")
        return

    if not content or not str(content).strip():
        return

    try:
        log_chat_event(
            role=role,
            content=str(content).strip(),
            route=route,
            model=model,
        )
        print(f"[CHAT_LOG] saved {role}: {str(content)[:80]}")
    except Exception as e:
        print(f"[CHAT_LOG] failed: {type(e).__name__}: {e}")

def get_top_used_tools(limit: int = 10) -> list[str]:
    data = load_tool_usage()
    return [
        name
        for name, _row in sorted(
            data.items(),
            key=lambda x: int(x[1].get("count", 0)),
            reverse=True,
        )[:limit]
    ]
RECENT_TOOL_COMMANDS = {}

def is_duplicate_tool_command(source: str, user_text: str, tool: str, window_sec: int = 10) -> bool:
    key = f"{source}:{tool}:{user_text.strip().lower()}"
    now = time.time()
    last = RECENT_TOOL_COMMANDS.get(key, 0)

    RECENT_TOOL_COMMANDS[key] = now
    return now - last < window_sec

def fuzzy_score(a: str, b: str) -> float:
    a = a.lower().strip()
    b = b.lower().strip()

    score = SequenceMatcher(None, a, b).ratio()

    # Boost prefix/contains matches
    if a.startswith(b) or b.startswith(a):
        score = max(score, 0.94)

    if b in a or a in b:
        score = max(score, 0.90)

    return score
def clean_tool_result_for_telegram(result: Any) -> str:
    if isinstance(result, dict):
        data = result.get("data")
        if isinstance(data, dict) and data.get("plain"):
            return str(data["plain"])

        speech = result.get("speech")
        if isinstance(speech, dict) and speech.get("text"):
            return str(speech["text"])

        ui = result.get("ui")
        if isinstance(ui, dict) and ui.get("summary"):
            return str(ui["summary"])

    return truncate_text(result, limit=1200)

def force_correct_common_tool(user_text: str, live_result: dict) -> dict:
    text = (user_text or "").lower()

    if "news" in text or "headlines" in text or "day's news" in text or "days news" in text:
        live_result["action"] = "direct_tool"
        live_result["route"] = "tools"
        live_result["tool"] = "news"
        live_result["intent"] = "daily_news"
        live_result["args"] = {
            "action": "top",
            "location": "Estonia",
            "limit": 6,
        }
        return live_result

    return live_result

def build_skill_command_index() -> list[dict]:
    index = []

    for tool_name, tool in TOOLS_BY_NAME.items():
        fn = tool.get("function", {})
        description = fn.get("description", "")

        phrases = []

        # Tool name itself
        phrases.append(tool_name.replace("_", " "))

        # Description as weak phrase
        if description:
            phrases.append(description)

        # Optional custom metadata if your loader exposes it
        for phrase in tool.get("commands", []) or []:
            phrases.append(phrase)

        for phrase in tool.get("aliases", []) or []:
            phrases.append(phrase)

        for phrase in phrases:
            if phrase and isinstance(phrase, str):
                index.append({
                    "tool_name": tool_name,
                    "phrase": phrase,
                    "tool": tool,
                })

    return index
def load_markdown_skill_by_name(name: str) -> dict | None:
    skills = load_markdown_skills()

    for skill in skills:
        if skill.get("name", "").lower() == name.lower():
            return skill

    return None
def resolve_skill_command(user_text: str, threshold: float = 0.82) -> dict | None:
    best = None
    best_score = 0.0

    for item in build_skill_command_index():
        score = fuzzy_score(user_text, item["phrase"])

        if score > best_score:
            best_score = score
            best = item

    if not best or best_score < threshold:
        return None

    return {
        "tool_name": best["tool_name"],
        "tool": best["tool"],
        "phrase": best["phrase"],
        "score": round(best_score, 3),
    }

def build_intent_tool_candidates(tool_skill_meta: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for tool_name, meta in tool_skill_meta.items():
        aliases = meta.get("intent_aliases", [])
        if not isinstance(aliases, list):
            continue
        for alias in aliases:
            if isinstance(alias, str) and alias.strip():
                out.setdefault(alias.strip().lower(), []).append(tool_name)
    return out

from pathlib import Path

CODER_MEMORY_PATH = Path(VAULT_DIR) / ".jarvis" / "coder_memory.md"

def load_coder_memory(max_chars: int = 4000) -> str:
    if not CODER_MEMORY_PATH.exists():
        return ""

    text = CODER_MEMORY_PATH.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return ""

    if len(text) > max_chars:
        text = text[-max_chars:]

    return f"""Recent coder memory:
{text}"""
PLANNER_STATE_PATH = Path(VAULT_DIR) / ".jarvis" / "planner" / "active_plan.json"

def load_task_graph() -> dict:
    if not TASK_GRAPH_PATH.exists():
        return {"tasks": {}, "active_task_id": None}
    try:
        data = json.loads(TASK_GRAPH_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"tasks": {}, "active_task_id": None}
    except Exception:
        return {"tasks": {}, "active_task_id": None}


def save_task_graph(graph: dict) -> None:
    TASK_GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
    TASK_GRAPH_PATH.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_task(title: str, user_request: str, route: str, model: str) -> dict:
    graph = load_task_graph()
    task_id = "task_" + str(uuid.uuid4())[:8]
    now = now_iso()

    task = {
        "id": task_id,
        "title": title,
        "status": "running",
        "created_at": now,
        "updated_at": now,
        "route": route,
        "model": model,
        "user_request": user_request,
        "steps": [],
        "events": [],
    }

    graph.setdefault("tasks", {})[task_id] = task
    graph["active_task_id"] = task_id
    save_task_graph(graph)
    return task

def load_active_plan() -> Dict[str, Any]:
    if not PLANNER_STATE_PATH.exists():
        return {}
    try:
        data = json.loads(PLANNER_STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
def load_plan_by_id(plan_id: str) -> Dict[str, Any]:
    plan_root = VAULT_DIR / ".jarvis" / "history" / "plans" / plan_id

    for filename in ["status.json", "plan.json"]:
        path = plan_root / filename
        if not path.exists():
            continue

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    return {}

def save_active_plan(plan: Dict[str, Any]) -> None:
    PLANNER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLANNER_STATE_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

def execute_skill_safely(tool_name: str, args: dict, skills: dict) -> str:
    try:
        skill = skills[tool_name]

        if hasattr(skill, "run"):
            result = skill.run(**args)
        elif callable(skill):
            result = skill(**args)
        else:
            return f"Skill {tool_name} is not executable."

        return json.dumps(result, ensure_ascii=False, default=str)

    except Exception as e:
        return f"Skill execution failed: {type(e).__name__}: {e}"
    
def is_plan_continue_command(text: str) -> bool:
    command, _ = parse_plan_command(text)
    return command in {"proceed", "continue", "next", "run next", "yes proceed"}

def is_plan_cancel_command(text: str) -> bool:
    command, _ = parse_plan_command(text)
    return command == "cancel"

def is_plan_modify_command(text: str) -> bool:
    command, _ = parse_plan_command(text)
    return command == "modify"

def extract_planner_steps(answer: str) -> List[Dict[str, Any]]:
    text = strip_thinking_tags(answer or "").strip()
    if not text:
        return []

    steps: List[Dict[str, Any]] = []

    # Fast path: valid JSON
    try:
        data = json.loads(text)
        raw_steps = data.get("steps", []) if isinstance(data, dict) else data
        if isinstance(raw_steps, list):
            for item in raw_steps:
                if isinstance(item, dict) and item.get("goal"):
                    steps.append({"goal": str(item["goal"]).strip()})
            if steps:
                return steps
    except Exception:
        pass

        # Recovery path: extract every complete "goal": "..." from broken JSON
    for match in re.finditer(r'"goal"\s*:\s*"([^"]+)"', text):
        goal = match.group(1).strip()

        if "Make the smallest safe code change" in goal:
            goal = goal.split("Make the smallest safe code change", 1)[0].strip()

        if goal:
            steps.append({"goal": goal})

    return steps
def build_simple_code_plan(user_text: str, paths: List[str]) -> Dict[str, Any]:
    planner_model = get_planner_model()

    prompt = (
    "Create a concrete coding implementation plan.\n"
    "Return ONLY valid JSON with this exact shape:\n"
    "{\n"
    '  "speak": "short summary of the plan",\n'
    '  "intent": "code_plan_create",\n'
    '  "action": "code",\n'
    '  "route": "code",\n'
    '  "chat_confidence": 0.0,\n'
    '  "execution_confidence": 1.0,\n'
    '  "continue_plan": false,\n'
    '  "create_new_plan": true,\n'
    '  "plan_action": "create",\n'
    '  "tool": null,\n'
    '  "args": {},\n'
    '  "path": ["/mnt/e/coding/projectx"],\n'
    '  "steps": [\n'
    '    {\n'
    '      "id": 1,\n'
    '      "goal": "specific implementation step",\n'
    '      "target_files": ["relative/path.ext"]\n'
    '    }\n'
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Return JSON only. No markdown. No explanations.\n"
    "- Extract exact file names from the user request when present.\n"
    "- If the user says save/write/create to a filename, include that exact filename in files.\n"
    "- For single-file tasks, files must contain exactly that one file.\n"
    "- For multi-file tasks, files must list every file the implementation will create or modify.\n"
    "- Every step must include target_files.\n"
    "- Every target_files entry must also exist in files.\n"
    "- Do not use directories as files. For example, use love.html, not skills.\n"
    "- Split work into small executable steps.\n"
    "- Avoid generic steps like inspect/analyze unless debugging requires inspection.\n"
    "- Keep 3–10 steps.\n"
    "- Each step must be concrete enough for an executor agent to implement directly.\n"
    "- For debugging tasks, include steps to identify the failure point and verify the fix.\n"
    "- The final step must verify or complete the requested file/code change.\n"
    "- Do not create a plan with only setup/directory steps.\n\n"
    "Examples:\n"
    "{\n"
    '  "speak": "I will create a small HTML file with the requested page.",\n'
    '  "intent": "code_plan_create",\n'
    '  "action": "code",\n'
    '  "route": "code",\n'
    '  "chat_confidence": 0.0,\n'
    '  "execution_confidence": 1.0,\n'
    '  "continue_plan": false,\n'
    '  "create_new_plan": true,\n'
    '  "plan_action": "create",\n'
    '  "tool": null,\n'
    '  "args": {},\n'
    '  "path": ["/mnt/e/coding/projectx"],\n'
    '  "steps": [\n'
    '    {"id": 1, "goal": "Create the HTML structure for the page.", "target_files": ["love.html"]},\n'
    '    {"id": 2, "goal": "Add CSS for the animated pulsing red heart.", "target_files": ["love.html"]},\n'
    '    {"id": 3, "goal": "Add the visible text requested by the user and ensure the file is complete.", "target_files": ["love.html"]}\n'
    "  ]\n"
    "}\n\n"
    f"User request:\n{user_text}\n\n"
    f"Likely paths:\n{json.dumps(paths, ensure_ascii=False)}\n"
    )

    payload = {
        "model": planner_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
    "temperature": 0,
    "num_predict": 1400,
    "num_ctx": 8192,
},
    }
    plan_files: List[str] = []
    try:
        answer = ""
        raw_steps = []
        with request_ollama_chat(payload, timeout=PLANNER_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))

            emit_event(
                "code_phase",
                "Coding planner full response",
                {    "route": "code",
                    "model": planner_model,
                    "planner_model": planner_model,
                    "data": data,
                },
            )

            raw_content = data.get("message", {}).get("content", "")
            answer = strip_thinking_tags(raw_content).strip()

            parsed_plan = parse_json_object_from_text(answer) or {}

            plan_files = parsed_plan.get("files", [])
            if not isinstance(plan_files, list):
                plan_files = []

            raw_steps = parsed_plan.get("steps", [])
            if not isinstance(raw_steps, list):
                raw_steps = extract_planner_steps(answer)

            if not answer and raw_content:
                answer = raw_content.strip()
            raw_steps = extract_planner_steps(answer)

            emit_event(
                "code_phase",
                "Planner steps extracted",
                {
                    "count": len(raw_steps),
                    "raw_steps": raw_steps,
                    "preview": answer[:500],
                },
            )

        steps = []
        for i, raw_step in enumerate(raw_steps, start=1):
            if not isinstance(raw_step, dict):
                continue
            goal = str(raw_step.get("goal", "")).strip()
            if not goal:
                continue
            steps.append({"id": i, "status": "pending", "goal": goal})
       
        if not steps:
            raise ValueError(f"planner returned no usable steps. Raw answer: {answer[:500]}")

    except Exception as e:
            emit_event("warning", "Coding planner failed, using fallback plan", {"error": str(e)})
            steps = [
                {
                    "id": 1,
                    "status": "pending",
                    "goal": f"PLANNER FAILED: {e}. Make the smallest safe code change requested by the user. Return patch format only.",
                }
            ]

    plan_id = make_plan_id()

    plan = {
        "plan_id": plan_id,
        "current_step": 0,

        "user_request": user_text,

        "paths": paths,
        "files": plan_files or paths,

        "planner_model": planner_model,

        "speak": parsed_plan.get(
            "speak",
            "Plan created."
        ),

        "intent": parsed_plan.get(
            "intent",
            "code_plan_create",
        ),

        "action": parsed_plan.get(
            "action",
            "code",
        ),

        "route": parsed_plan.get(
            "route",
            "code",
        ),

        "chat_confidence": float(
            parsed_plan.get(
                "chat_confidence",
                0.0,
            )
        ),

        "execution_confidence": float(
            parsed_plan.get(
                "execution_confidence",
                1.0,
            )
        ),

        "continue_plan": bool(
            parsed_plan.get(
                "continue_plan",
                False,
            )
        ),

        "create_new_plan": bool(
            parsed_plan.get(
                "create_new_plan",
                True,
            )
        ),

        "plan_action": parsed_plan.get(
            "plan_action",
            "create",
        ),

        "tool": parsed_plan.get(
            "tool",
            None,
        ),

        "args": parsed_plan.get(
            "args",
            {},
        ),

        "steps": steps,

        "created_at": now_iso(),

        "status": "waiting_for_approval",
    }

    save_json(plan_id, "plan.json", plan)

    append_event(
        "plan.created",
        "Coding plan created",
        plan_id=plan_id,
        route="code",
        model=planner_model,
        payload={
            "user_request": user_text,
            "paths": paths,
            "step_count": len(steps),
        },
    )

    return plan

def render_plan(plan: Dict[str, Any]) -> str:
    lines = [f"PLAN_ID: {plan.get('plan_id')}", ""]
    for step in plan.get("steps", []):
        lines.append(f"{step.get('id')}. [{step.get('status')}] {step.get('goal')}")
    lines.append("")
    lines.append("WAITING_FOR: proceed / modify step / cancel")
    return "\n".join(lines)

def build_tool_hints(tool_skill_meta: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for tool_name, meta in tool_skill_meta.items():
        keywords = meta.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []
        out[tool_name] = [k.strip().lower() for k in keywords if isinstance(k, str) and k.strip()]
    return out


def build_tool_direct_match(tool_skill_meta: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for tool_name, meta in tool_skill_meta.items():
        direct_match = meta.get("direct_match", [])
        if not isinstance(direct_match, list):
            direct_match = []
        out[tool_name] = [k.strip().lower() for k in direct_match if isinstance(k, str) and k.strip()]
    return out


def build_tool_route_hints(tool_skill_meta: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for tool_name, meta in tool_skill_meta.items():
        route = meta.get("route")
        if isinstance(route, str) and route.strip():
            out[tool_name] = route.strip().lower()
    return out
def normalize_patch_text(content: str) -> str:
    text = content or ""

    # Remove markdown fence leftovers
    text = text.replace("```html", "").replace("```python", "").replace("```", "").strip()

    # If model forgot @@, insert it after FILE line
    if "--- FILE:" in text and "@@" not in text:
        lines = text.splitlines()
        out = []
        inserted = False

        for i, line in enumerate(lines):
            out.append(line)
            if not inserted and line.strip().startswith("--- FILE:"):
                out.append("@@")
                inserted = True

        text = "\n".join(out)

    return text
def complete_tool_args_with_meta(
    tool_name: str,
    user_text: str,
    parsed: dict,
) -> dict:
    if not tool_name or tool_name not in TOOLS_BY_NAME:
        return parsed

    tool_schema = TOOLS_BY_NAME.get(tool_name, {})
    tool_meta = TOOL_SKILL_META.get(tool_name, {})

    prompt = f"""
You fill missing tool arguments.

Return ONLY valid JSON:
{{
  "tool": "{tool_name}",
  "args": {{}}
}}

User message:
{user_text}

Router result:
{json.dumps(parsed, ensure_ascii=False)}

Tool schema:
{json.dumps(tool_schema, ensure_ascii=False)}

Tool metadata:
{json.dumps(tool_meta, ensure_ascii=False)}

Rules:
- Return only argument keys that exist in Tool schema properties.
- Remove any existing args that are not valid for this tool.
- Fill required missing args from user message, intent, schema, and metadata.
- Do not invent unrelated values.
- If a required value is impossible to infer, leave it missing.
- Return JSON only.
""".strip()

    payload = {
        "model": resolve_model(requested_model=None, route="live"),
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
            "temperature": 0,
            "top_p": 0.2,
            "num_ctx": 2048,
        },
    }

    try:
        with request_ollama_chat(payload, timeout=CHAT_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        raw = data.get("message", {}).get("content", "")
        filled = parse_json_object_from_text(raw)

        if not isinstance(filled, dict):
            return parsed

        filled_args = filled.get("args")
        if not isinstance(filled_args, dict):
            return parsed

        valid_props = (
            tool_schema
            .get("function", {})
            .get("parameters", {})
            .get("properties", {})
        )

        valid_arg_names = set(valid_props.keys())

        merged_args = {
            **(parsed.get("args") or {}),
            **filled_args,
        }

        parsed["args"] = {
            k: v
            for k, v in merged_args.items()
            if k in valid_arg_names
        }

        return parsed

    except Exception as e:
        emit_event(
            "warning",
            "Tool arg completion failed",
            {
                "tool": tool_name,
                "error": str(e),
            },
        )
        return parsed
    
def reload_all_skills() -> Dict[str, Any]:
    global TOOLS, TOOL_MAP, TOOL_KEYWORDS, TOOL_SKILL_META
    global TOOLS_BY_NAME, TOOL_LIST_TEXT
    global INTENT_TOOL_CANDIDATES, TOOL_HINTS, TOOL_DIRECT_MATCH, TOOL_ROUTE_HINTS

    load_skills()
    TOOLS = get_all_tools()
    TOOL_MAP = get_all_tool_map()
    TOOL_KEYWORDS = get_all_keywords()
    TOOL_SKILL_META = get_all_skill_meta()
    TOOLS_BY_NAME = {t["function"]["name"]: t for t in TOOLS}
    TOOL_LIST_TEXT = "\n".join(f"- {t['function']['name']}: {t['function'].get('description', '')}" for t in TOOLS)
    INTENT_TOOL_CANDIDATES = build_intent_tool_candidates(TOOL_SKILL_META)
    TOOL_HINTS = build_tool_hints(TOOL_SKILL_META)
    TOOL_DIRECT_MATCH = build_tool_direct_match(TOOL_SKILL_META)
    TOOL_ROUTE_HINTS = build_tool_route_hints(TOOL_SKILL_META)

    return {"status": "ok", "tool_count": len(TOOLS), "tools": list(TOOL_MAP.keys())}


print(f"[REACT] Loading skills from {PROJECT_ROOT / 'skills'}...")
reload_all_skills()
def match_markdown_skill(user_text: str) -> Optional[Dict[str, Any]]:
    text = (user_text or "").lower()

    for skill in load_markdown_skills():
        haystack = (
            str(skill.get("name", "")) + "\n" +
            str(skill.get("description", ""))
        ).lower()

        if "list" in text and "skill" in text:
            continue

        trigger_words = [
            "new app",
            "start a project",
            "build me an app",
            "set up a new service",
            "create a new project",
            "scaffold",
        ]

        if any(t in text for t in trigger_words):
            if "scaffold" in haystack or "project" in haystack:
                return skill

    return None
# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------
def read_last_chat_log_chars(max_chars: int = 4000) -> str:
    path = today_log_path()

    if not path.exists():
        return ""

    text = path.read_text(encoding="utf-8", errors="ignore")
    return text[-max_chars:]

def load_prompt_file(path: Path, fallback: str = "") -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        return text or fallback
    except Exception:
        return fallback


def get_tool_names_text() -> str:
    try:
        return ", ".join(sorted(TOOLS_BY_NAME.keys()))
    except Exception:
        return ""
    
def build_compact_tool_catalog(limit: int = 10) -> str:
    preferred = get_top_used_tools(limit)

    core = [
        "radio",
        "weather",
        "news",
        "timer",
        "chat_log",
        "memory",
        "flux",
        "list_skills",
    ]

    names: list[str] = []

    for name in core + preferred:
        if name in TOOLS_BY_NAME and name not in names:
            names.append(name)

    lines = []

    for name in names[:limit]:
        fn = TOOLS_BY_NAME[name].get("function", {})
        desc = (fn.get("description") or "").split(".")[0]
        props = fn.get("parameters", {}).get("properties", {})
        args = ", ".join(props.keys()) or "none"

        lines.append(f"- {name}({args}): {desc}")

    return "\n".join(lines)

def build_short_term_context() -> str:
    try:
        from scripts.chat_context import read_recent_chat
    except Exception:
        try:
            from chat_context import read_recent_chat
        except Exception:
            return ""

    try:
        rows = read_recent_chat(
            minutes=30,
            max_items=12,
        )
    except Exception as e:
        print(f"[CHAT_CONTEXT] read failed: {e}")
        return ""

    if not rows:
        return ""

    lines = []

    for item in rows:
        role = str(item.get("role", "unknown")).upper()
        route = item.get("route") or "-"
        content = str(item.get("content", "")).strip()

        if not content:
            continue

        content = content.replace("\n", " ")

        if len(content) > 400:
            content = content[:400] + "..."

        lines.append(
            f"- {role}[{route}]: {content}"
        )

    if not lines:
        return ""

    return (
        "[ACTIVE CHAT CONTEXT]\n"
        "# Recent Chat Context\n\n"
        + "\n".join(lines)
        + "\n[/ACTIVE CHAT CONTEXT]"
    )

def load_named_prompt(path: Path, fallback: str = "") -> str:
    prompt = load_prompt_file(path, fallback=fallback)

    parts = [prompt]

    last_exchange = build_last_exchange_context()
    if last_exchange:
        parts.append(last_exchange)

    short_context = build_short_term_context()
    if short_context:
        parts.append(short_context)

    out = "\n\n".join(p for p in parts if p and p.strip())
    return out.replace("{{TOOL_CATALOG}}", build_compact_tool_catalog(limit=10)) 

def parse_workflow_questions(md_skill: Dict[str, Any]) -> List[Dict[str, str]]:
    content = md_skill.get("content", "")

    questions = []

    current_category = "general"

    for raw in content.splitlines():
        line = raw.strip()

        if line.startswith("# CATEGORY:"):
            current_category = line.split(":", 1)[1].strip()
            continue

        if line.startswith("Q:"):
            qid = line.split(":", 1)[1].strip()

            questions.append({
                "id": qid,
                "category": current_category,
                "prompt": "",
            })

            continue

        if line.startswith("Prompt:") and questions:
            questions[-1]["prompt"] = line.split(":", 1)[1].strip()

    return questions
def get_next_workflow_question(state: Dict[str, Any]) -> Optional[str]:
    md_skill = load_markdown_skill_by_name(state["skill"])

    questions = parse_workflow_questions(md_skill)

    answers = state.setdefault("answers", {})

    for q in questions:
        if q["id"] not in answers:
            state["last_question"] = q["id"]
            save_workflow_state(state)
            return q["prompt"]

    return None
def continue_markdown_workflow(user_text: str, state: Dict[str, Any]) -> str:
    answers = state.setdefault("answers", {})
    category = int(state.get("category", 1))

    # Save previous answer
    last_question = state.get("last_question")

    if last_question:
        answers[last_question] = user_text.strip()

    # ------------------------------------------------------------------
    # CATEGORY 1
    # ------------------------------------------------------------------
    if category == 1:
        questions = [
            "project_name",
            "project_description",
            "target_users",
        ]

        for q in questions:
            if q not in answers:
                state["last_question"] = q
                save_workflow_state(state)

                prompts = {
                    "project_name": "What is the project name?",
                    "project_description": "Describe the project in 1-3 sentences.",
                    "target_users": "Who are the target users?",
                }

                return prompts[q]

        state["category"] = 2

    # ------------------------------------------------------------------
    # CATEGORY 2
    # ------------------------------------------------------------------
    if state["category"] == 2:
        questions = [
            "frontend",
            "backend",
            "database",
        ]

        for q in questions:
            if q not in answers:
                state["last_question"] = q
                save_workflow_state(state)

                prompts = {
                    "frontend": "Frontend stack? (Next.js, React, Vue, etc.)",
                    "backend": "Backend stack?",
                    "database": "Database?",
                }

                return prompts[q]

        state["category"] = 3

    # ------------------------------------------------------------------
    # CATEGORY 3
    # ------------------------------------------------------------------
    if state["category"] == 3:
        questions = [
            "authentication",
            "payments",
            "deployment",
        ]

        for q in questions:
            if q not in answers:
                state["last_question"] = q
                save_workflow_state(state)

                prompts = {
                    "authentication": "Need authentication/login?",
                    "payments": "Need payment support?",
                    "deployment": "Where will this run? (local/cloud/docker/etc.)",
                }

                return prompts[q]

    # ------------------------------------------------------------------
    # COMPLETE
    # ------------------------------------------------------------------
    state["phase"] = "complete"
    save_workflow_state(state)

    summary = json.dumps(answers, indent=2, ensure_ascii=False)

    return (
        "Interview complete.\n\n"
        "Project summary:\n\n"
        f"{summary}\n\n"
        "Reply with:\n"
        "- proceed\n"
        "- modify\n"
        "- cancel"
    )
def load_workflow_state() -> Dict[str, Any]:
    if not WORKFLOW_STATE_PATH.exists():
        return {}
    try:
        return json.loads(WORKFLOW_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_workflow_state(state: Dict[str, Any]) -> None:
    WORKFLOW_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    WORKFLOW_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def clear_workflow_state() -> None:
    if WORKFLOW_STATE_PATH.exists():
        WORKFLOW_STATE_PATH.unlink()

def request_llama_cpp_chat(payload: Dict[str, Any], timeout: int):
    llama_payload = {
        "model": payload.get("model", "gemma4"),
        "messages": payload.get("messages", []),
        "stream": payload.get("stream", False),
        "temperature": payload.get("options", {}).get("temperature", 0.2),
        "top_p": payload.get("options", {}).get("top_p", 0.8),
    }

    req = urllib.request.Request(
        f"{LLAMA_CPP_HOST}/v1/chat/completions",
        data=json.dumps(llama_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=timeout)

def request_chat_backend(payload: Dict[str, Any], timeout: int, route: str = "fast"):
    if route in LLAMA_CPP_ROUTES:
        return request_llama_cpp_chat(payload, timeout)
    return request_ollama_chat(payload, timeout)

def normalize_chat_response(data: Dict[str, Any]) -> Dict[str, Any]:
    if "message" in data:
        return data

    choices = data.get("choices") or []
    if choices:
        msg = choices[0].get("message") or {}
        return {
            "message": {
                "role": msg.get("role", "assistant"),
                "content": msg.get("content", ""),
            },
            "raw": data,
        }

    return {
        "message": {
            "role": "assistant",
            "content": "",
        },
        "raw": data,
    }

def load_markdown_skills() -> list[dict]:
    root = VAULT_DIR / ".jarvis" / "markdown_skills"
    skills = []

    for path in root.glob("*.md"):
        text = path.read_text(encoding="utf-8", errors="ignore")

        meta = {}
        body = text

        if text.startswith("---"):
            _, frontmatter, body = text.split("---", 2)
            for line in frontmatter.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()

        skills.append({
            "path": str(path),
            "name": meta.get("name", path.stem),
            "description": meta.get("description", ""),
            "content": body.strip(),
        })

    return skills

def needs_output_path(task: str, paths: list[str]) -> bool:
    lower = (task or "").lower()

    create_keywords = [
        "create",
        "make",
        "generate",
        "write",
        "save",
        "build",
        "code",
    ]

    wants_file = any(k in lower for k in create_keywords)

    has_real_file = any(
        "." in p.split("/")[-1]
        for p in paths
    )

    return wants_file and not has_real_file

def clean_telegram_prefix(text: str) -> str:
    text = text or ""
    prefix = "Telegram message:"
    if text.startswith(prefix):
        return text[len(prefix):].strip()
    return text

def split_telegram_text(text: str, limit: int = TELEGRAM_MAX_MESSAGE_CHARS) -> list[str]:
    text = str(text or "").strip()

    if not text:
        return []

    chunks = []

    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)

        if cut < 1000:
            cut = text.rfind(" ", 0, limit)

        if cut < 1000:
            cut = limit

        chunks.append(text[:cut].strip())
        text = text[cut:].strip()

    if text:
        chunks.append(text)

    return chunks


def notify_telegram(text: str) -> None:
    if not TELEGRAM_NOTIFY_CHAT_ID:
        debug("Telegram notify skipped: missing JARVIS_TELEGRAM_CHAT_ID")
        return

    try:
        clean_text = clean_tool_result_for_telegram(text)

        for i, chunk in enumerate(split_telegram_text(clean_text), start=1):
            if i > 1:
                chunk = f"(continued {i})\n\n{chunk}"

            TELEGRAM_GATEWAY.send_message(
                TELEGRAM_NOTIFY_CHAT_ID,
                chunk,
            )

    except Exception as e:
        debug(f"Telegram notify failed: {e}")

def parse_file_patch(content: str) -> Optional[Dict[str, str]]:
    text = content or ""

    if "### PATCH" in text:
        text = text.split("### PATCH", 1)[1].strip()

    text = text.replace("\\n", "\n")

    try:
        data = json.loads(text.strip().strip("`"))
        if isinstance(data, dict) and isinstance(data.get("path"), str) and isinstance(data.get("content"), str):
            return {"path": data["path"], "content": data["content"]}
    except Exception:
        pass

    marker = "--- FILE:"
    if marker not in text:
        return None

    after = text.split(marker, 1)[1].strip()
    first_line, _, rest = after.partition("\n")
    if "@@" in rest:
        rest = rest.split("@@", 1)[1].strip()
    else:
        rest = rest.strip()
    path = first_line.strip()
    path = path.split("@@", 1)[0].strip()
    path = path.split(" ", 1)[0].strip()

    if "@@" in rest:
        rest = rest.split("@@", 1)[1].strip()

    # Remove unified diff + prefixes if model returned diff format
    cleaned_lines = []
    for line in rest.splitlines():
        if line.startswith("@@"):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            cleaned_lines.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            continue
        else:
            cleaned_lines.append(line)

    rest = "\n".join(cleaned_lines).strip()

    if not path or not rest:
        return None

    if "\n" in path or "\\n" in path or "@@" in path:
        return None

    return {"path": path, "content": rest}

def apply_file_patch(content: str) -> Dict[str, Any]:
    patch = parse_file_patch(content)
    if not patch:
        return {"ok": False, "error": "No writable file patch found"}

    path = Path(patch["path"])
    if not path.is_absolute():
        path = PROJECT_ROOT / path

    path = path.resolve()

    if not str(path).startswith(str(PROJECT_ROOT.resolve())):
        return {"ok": False, "error": f"Refusing to write outside project root: {path}"}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(patch["content"], encoding="utf-8")

    return {"ok": True, "path": str(path)}

def validate_coder_output(content: str) -> Dict[str, Any]:
    text = content or ""
    lower = text.lower()

    problems = []

    dangerous_patterns = [
        "rm -rf",
        "sudo rm",
        "mkfs",
        "dd if=",
        ":(){",
        "chmod -r 777 /",
        "chown -r",
        "curl ",
        "wget ",
        "powershell -enc",
        "invoke-expression",
        "eval(",
        "exec(",
    ]

    for pattern in dangerous_patterns:
        if pattern in lower:
            problems.append(f"dangerous pattern detected: {pattern}")

    # Detect full-file rewrite tendency
    code_fence_count = text.count("```")
    line_count = len(text.splitlines())

    if line_count > 500:
        problems.append("output too large; likely full-file rewrite")

    if code_fence_count >= 6:
        problems.append("too many code blocks; likely not a minimal patch")

    # Prefer scoped patch/diff output
    has_patch_marker = (
        "--- FILE:" in text
        or "diff --git" in text
        or "@@" in text
        or "replace this" in lower
        or "modified parts" in lower
    )

    if not has_patch_marker:
        problems.append("no clear patch marker or scoped replacement block found")

    return {
        "ok": len(problems) == 0,
        "problems": problems,
        "line_count": line_count,
        "code_fence_count": code_fence_count,
    }


def wrap_invalid_coder_output(content: str, validation: Dict[str, Any]) -> str:
    problems = "\n".join(f"- {p}" for p in validation.get("problems", []))

    return f"""Coder output was rejected by validation.

Problems:
{problems}

The model must return a smaller, safer patch.

Required format:

--- FILE: path/to/file.py
@@
<only changed function/helper blocks>

Rules:
- Do not rewrite full files
- Do not include dangerous shell commands
- Do not include unrelated changes
- Keep the patch minimal

Original rejected output preview:

{content[:3000]}
"""

def debug(msg: str) -> None:
    if DEBUG:
        print(f"[REACT] {msg}")


def now_iso() -> str:
    return  datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    VAULT_DIR.mkdir(parents=True, exist_ok=True)


def append_log(line: str) -> None:
    try:
        ensure_dirs()
        with open(VAULT_DIR / "jarvis.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
def character_stage_message(event_type: str, message: str, data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    data = data or {}

    plan_id = data.get("plan_id")
    step = data.get("step") or {}
    step_id = step.get("id") if isinstance(step, dict) else data.get("task_id")
    route = data.get("route") or data.get("resolved_route")
    model = data.get("model") or data.get("resolved_model") or data.get("planner_model")
    
    if event_type == "code_edit_output":
        preview = str(data.get("result_preview", ""))[:1500]

        return (
            "💻 Coder produced output.\n\n"
            f"Path: {data.get('path')}\n"
            f"Mode: {data.get('mode')}\n\n"
            f"{preview}"
        )
    if event_type == "agent_start":
        return (
            "🧠 Agent mode started.\n"
            f"Route: {route or 'unknown'}\n"
            f"Model: {model or 'unknown'}\n\n"
            "I am breaking the task into reasoning steps."
        )

    if event_type == "agent_step":
        step_no = data.get("step") or data.get("step_no") or data.get("iteration")
        return (
            "⚙️ Agent is working.\n"
            f"Step: {step_no or 'unknown'}\n"
            f"Route: {route or 'unknown'}\n"
            f"Model: {model or 'unknown'}\n\n"
            f"{message}"
        )

    if event_type == "agent_final":
        return (
            "🏁 Agent completed the task.\n"
            f"Route: {route or 'unknown'}\n"
            f"Model: {model or 'unknown'}"
        )
    if event_type == "code_phase":
        phase = data.get("phase")

        if phase == "plan_created":
            return (
                "🧠 Planning complete.\n"
                f"Plan: {plan_id}\n"
                f"Steps: {len(data.get('steps', []))}\n\n"
                "I have a structured route now. Waiting for approval."
            )

        if phase == "running_step":
            return (
                "💻 Executing coding step.\n"
                f"Plan: {plan_id}\n"
                f"Step: {step_id}\n\n"
                f"{step.get('goal', message) if isinstance(step, dict) else message}"
            )

        if phase == "validating_patch":
            return (
                "🔎 Patch returned.\n"
                f"Plan: {plan_id}\n\n"
                "I am validating the output before applying it."
            )

        if phase == "repairing_patch":
            return (
                "🛠️ Patch failed validation.\n"
                f"Plan: {plan_id}\n\n"
                "I am asking the coder to repair the patch."
            )

        if phase == "patch_applied":
            return (
                "✅ Patch applied successfully.\n"
                f"Plan: {plan_id}\n\n"
                "Step is complete."
            )

        if phase == "patch_apply_failed":
            return (
                "❌ Patch could not be applied.\n"
                f"Plan: {plan_id}\n\n"
                "I saved the failure details for inspection."
            )

    if event_type == "code_step_ready":
        remaining = data.get("remaining")
        next_step = data.get("next_step")

        text = (
            "✅ Coding step complete.\n"
            f"Plan: {plan_id}\n"
            f"Remaining steps: {remaining}\n"
        )

        if isinstance(next_step, dict):
            text += f"\nNext: {next_step.get('goal')}"

        return text

    if event_type == "plan":
        return (
            "🧭 Selecting tools and route.\n"
            f"Model: {model or 'unknown'}\n"
            f"{message}"
        )

    if event_type == "tool_start":
        return (
            "🔧 Running tool.\n"
            f"Tool: {data.get('tool')}\n"
            f"{message}"
        )

    if event_type == "tool_result":
        return (
            "📦 Tool completed.\n"
            f"Tool: {data.get('tool')}\n"
            f"Elapsed: {data.get('elapsed_sec')}s"
        )

    if event_type == "warning":
        return (
            "⚠️ JARVIS warning.\n"
            f"{message}\n\n"
            f"{str(data.get('error', ''))[:800]}"
        )

    if event_type == "final":
        return (
            "🏁 Final response ready.\n"
            f"Route: {route or 'unknown'}\n"
            f"Model: {model or 'unknown'}"
        )

    return None
def contains_patch(text: str) -> bool:
    text = text or ""
    return (
        "--- FILE:" in text
        or "diff --git" in text
        or "@@" in text
        or "### PATCH" in text
    )


def looks_like_markdown_report(text: str) -> bool:
    text = (text or "").strip()

    if not text:
        return False

    if contains_patch(text):
        return False

    return (
        text.startswith("#")
        or "\n## " in text
        or "- " in text
        or len(text) > 800
    )

# Replace classify_agent_output_kind to also handle analyze_code
def classify_agent_output_kind(skill_name, user_text, result=None):
    result = result or {}
    name = (skill_name or "").lower().strip()
    text = (user_text or "").lower().strip()

    result_kind = result.get("kind")
    if result_kind in {"report", "patch", "message"}:
        return result_kind

    result_text = (
        result.get("markdown")
        or result.get("report")
        or result.get("text")
        or result.get("content")
        or result.get("answer")
        or ""
    )

    if contains_patch(result_text):
        return "patch"

    if looks_like_markdown_report(result_text):
        return "report"

    if name.startswith("analyze") or text.startswith("analyze ") or "analyze" in text:
        return "report"

    patch_words = [
        "fix ", "change ", "edit ", "modify ", "implement ",
        "refactor ", "apply patch", "write code", "create file",
    ]

    if name in {"code_edit", "apply_patch", "coder", "fix_file", "refactor_file"}:
        return "patch"

    if any(w in text for w in patch_words):
        return "patch"

    return "message"

def write_analysis_report(skill_name, plan_id, result):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_skill = skill_name.replace("/", "_").replace(" ", "_")

    path = VAULT_DIR / "Reports" / f"{ts}_{plan_id}.md"

    markdown = (
        result.get("markdown")
        or result.get("report")
        or result.get("text")
        or result.get("content")
        or ""
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")

    return path

def classify_skill_task(skill_name: str, user_text: str, result: dict | None = None) -> str:
    name = skill_name.lower()
    text = user_text.lower()

    # Analysis is always report mode, including code analysis
    if name.startswith("analyze") or text.startswith("analyze"):
        return "report"

    # Only explicit modification/coding actions are patch mode
    if name in {"code_edit", "apply_patch", "coder", "fix_file", "refactor_file"}:
        return "patch"

    if any(w in text for w in ["fix ", "change ", "edit ", "modify ", "implement ", "add "]):
        return "patch"

    return "message"

def emit_event(
    event_type: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    event_type = (event_type or "").lower()
    try:
        ensure_dirs()

        payload = {
            "ts": time.time(),
            "time": now_iso(),
            "type": event_type,
            "message": message,
            "data": data or {},
        }
        stage_text = character_stage_message(event_type, message, data)

        if TELEGRAM_ENABLED and stage_text:
            notify_telegram(clean_tool_result_for_telegram(stage_text))


        with open(EVENTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

        typing_events = {
        "plan",
        "router",
        "code_phase",
        "tool_start",
        "status",
        "agent_start",
        "agent_step",
        }

        if TELEGRAM_ENABLED and event_type in typing_events:
            telegram_chat_action("typing")

        # ------------------------------------------------------------------
        # Telegram notifications
        # ------------------------------------------------------------------
        if event_type in {"planner.start", "coder.start", "tool_start", "agent_start", "agent_step"}:
            stage_id = str((data or {}).get("stage_id") or event_type)
            TELEGRAM_GATEWAY.start_typing_stage(TELEGRAM_NOTIFY_CHAT_ID, stage_id)



        if event_type in {"planner.done", "coder.done", "tool_result", "agent_final", "final", "warning"}:
            stage_id = str((data or {}).get("stage_id") or event_type.replace(".done", ".start"))
            TELEGRAM_GATEWAY.stop_typing_stage(stage_id)
        important_events = {
            "critical",
            "warning",
            "plan",
            "final",
            "code_phase",
            "code_step_ready",
            "Coding planner full response",
            "Live router decision",
            "agent_start",
            "agent_step",
            "agent_final",
            "code_edit_output",
        }
        if "coder" in model:
            emoji = "💻"
        elif "planner" in model:
            emoji = "🧠"
        else:
            emoji = "🤖"
        if event_type == "warning":
            emoji = "⚠️"
        if TELEGRAM_ENABLED and event_type in important_events:
            route = str(payload["data"].get("route", ""))
            model = str(
                payload["data"].get("model")
                or payload["data"].get("resolved_model")
                or ""
            )

            telegram_text = (
                f"{emoji} JARVIS EVENT\n\n"
                f"Type: {event_type}\n"
                f"Message: {message}\n"
            )

            if route:
                telegram_text += f"Route: {route}\n"

            if model:
                telegram_text += f"Model: {model}\n"

            # Do not send raw payload JSON to Telegram
            notify_telegram(telegram_text)

    except Exception:
        pass
def save_report(
    skill_name: str,
    plan_id: str,
    result: Any,
    route: str = "code",
) -> Dict[str, Any]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_skill = (skill_name or "unknown").replace("/", "_").replace(" ", "_")

    # --- Aggregate full agent trace into one markdown document ---
    sections: List[str] = []

    # Pull each observation (one per agent step)
    observations = result.get("observations") or []
    for obs in observations:
        raw = obs.get("observation") or obs.get("content") or ""

        # observations may be JSON-wrapped tool results
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
                text = (
                    data.get("markdown")
                    or data.get("report")
                    or data.get("text")
                    or data.get("content")
                    or data.get("answer")
                    or ""
                )
                if text:
                    raw = text
            except Exception:
                pass

        if raw and raw.strip():
            sections.append(raw.strip())

    # Final answer is the synthesis — always append last
    final_answer = (
        result.get("answer")
        or result.get("markdown")
        or result.get("report")
        or result.get("text")
        or result.get("content")
        or ""
    ).strip()

    # If final_answer is already a superset of all sections (agent summarized),
    # use it alone. Otherwise prepend the observations for full context.
    if final_answer and all(
        section[:120] in final_answer for section in sections if section
    ):
        markdown = final_answer
    else:
        parts = sections + ([final_answer] if final_answer else [])
        markdown = "\n\n---\n\n".join(parts)

    if not markdown:
        markdown = json.dumps(result, indent=2, ensure_ascii=False)

    # Prepend a header
    header = f"# Report: {safe_skill}\n\n_Plan: {plan_id} — {ts}_\n\n"
    markdown = header + markdown

    report_dir = VAULT_DIR / "Reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{ts}_{safe_skill}_{plan_id[:12]}.md"
    path = report_dir / filename
    path.write_text(markdown, encoding="utf-8")

    emit_event("artifact", "Report saved", {
        "plan_id": plan_id,
        "skill": skill_name,
        "path": str(path),
        "chars": len(markdown),
        "sections": len(sections),
        "route": route,
    })

    append_event(
        "report.saved",
        f"Report saved for {skill_name}",
        plan_id=plan_id,
        route=route,
        model="",
        payload={
            "path": str(path),
            "chars": len(markdown),
            "sections": len(sections),
        },
    )

    return {
        "ok": True,
        "kind": "report",
        "path": str(path),
        "markdown": markdown,
        "message": f"Report written to {path}",
    }

def recent_events(limit: int = 100) -> List[Dict[str, Any]]:
    if not EVENTS_FILE.exists():
        return []
    try:
        lines = EVENTS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        return [json.loads(line) for line in lines if line.strip()]
    except Exception:
        return []


def recent_coding_events(limit: int = 120) -> List[Dict[str, Any]]:
    events = recent_events(500)
    coding: List[Dict[str, Any]] = []

    for e in events:
        data = e.get("data", {}) or {}
        model = str(
            data.get("model")
            or data.get("resolved_model")
            or data.get("planner_model")
            or ""
        ).lower()
        route = str(data.get("route") or data.get("resolved_route") or "").lower()
        event_type = str(e.get("type") or "").lower()

        if (
            route == "code"
            or "coder" in model
            or event_type == "code_phase"
            or "planner" in str(e.get("message", "")).lower()
        ):
            coding.append(e)

    return coding[-limit:]


def safe_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return json.dumps(str(obj), ensure_ascii=False)


def truncate_text(value: Any, limit: int = TOOL_RESULT_CHAR_LIMIT) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = safe_json_dumps(value)
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n\n[truncated to {limit} chars]"


def http_get_ok_simple(url: str, timeout: int = 2) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False




def sanitize_for_tts(text: str) -> str:
    return text.replace("'", "''").replace("JARVIS", "Jarvis").replace("FRIDAY", "Friday").replace("EDITH", "Edith").replace("HAL", "Hal")


def speak_ack(text: str) -> None:
    if not ENABLE_TTS_ACK:
        return

    def _speak() -> None:
        if speak_kokoro(text):
            return

        # fallback Windows voice
        try:
            safe = sanitize_for_tts(text)
            subprocess.run(
                [
                    POWERSHELL,
                    "-Command",
                    (
                        "Add-Type -AssemblyName System.Speech; "
                        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                        "$s.Rate = 2; "
                        f"$s.Speak('{safe}')"
                    ),
                ],
                timeout=10,
                capture_output=True,
            )
        except Exception as e:
            debug(f"Fallback ACK TTS error: {e}")

    threading.Thread(target=_speak, daemon=True).start()

def write_bridge_status(state: str, text: Optional[str] = None) -> None:
    try:
        ensure_dirs()
        (BRIDGE_DIR / "state.txt").write_text(state, encoding="utf-8")
        if text is not None:
            (BRIDGE_DIR / "output.txt").write_text(text, encoding="utf-8")
    except Exception:
        pass


def request_ollama_chat(payload: Dict[str, Any], timeout: int):
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=timeout)


def request_ollama_tags() -> Dict[str, Any]:
    req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def strip_thinking_tags(text: str) -> str:
    if not text:
        return text
    start_tag = "<think>"
    end_tag = "</think>"
    result: List[str] = []
    i = 0
    in_think = False
    while i < len(text):
        if text.startswith(start_tag, i):
            in_think = True
            i += len(start_tag)
            continue
        if text.startswith(end_tag, i):
            in_think = False
            i += len(end_tag)
            continue
        if not in_think:
            result.append(text[i])
        i += 1
    return "".join(result).replace(end_tag, "").strip()


def parse_json_object_from_text(text: str) -> Optional[Dict[str, Any]]:
    text = strip_thinking_tags(text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict):
                return data
        except Exception:
            return None
    return None


def run_live_router(user_text: str) -> Dict[str, Any]:
    prompt = load_named_prompt(
       LIVE_ROUTER_PROMPT_PATH,
       fallback=(
           "You are JARVIS Live Router. Return ONLY valid JSON with fields: "
            "speak, transcript, intent, action, route, tool, confidence, args. "
            "Default action is chat_only and route live."
        ),
    )
 

    prompt = prompt.replace(
        "{{TOOL_CATALOG}}",
        build_live_tool_catalog()
    )
    self_hint = build_self_context_prompt(
        persona=None,
        max_tools=8,
    )

    prompt = (
        prompt
        + "\n\nJARVIS SELF-CONTEXT HINT:\n"
        + self_hint[:2500]
    )
    model = resolve_model(requested_model=None, route="live")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_text},
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "top_p": 0.7,
            "num_ctx": 4096,
        },
    }
    #emit_event("warning", "Live router running", {"error": "Running live router", "payload": payload})
    try:
        with request_chat_backend(payload, timeout=CHAT_TIMEOUT_SEC, route="live") as resp:
            data = normalize_chat_response(json.loads(resp.read().decode("utf-8")))

        raw = data.get("message", {}).get("content", "")
        parsed = parse_json_object_from_text(raw)
        if isinstance(parsed, dict):
            parsed.setdefault("action", "chat_only")
            parsed.setdefault("route", "live")
            parsed.setdefault("tool", None)
            parsed.setdefault("args", {})
            parsed.setdefault("speak", "")
            parsed.setdefault("transcript", user_text)

            # Backward compatibility with old router schema
            old_conf = parsed.get("confidence")

            if "chat_confidence" not in parsed:
                if parsed.get("action") == "chat_only":
                    parsed["chat_confidence"] = float(old_conf or 0.85)
                else:
                    parsed["chat_confidence"] = 0.0

            if "escalation_confidence" not in parsed:
                if parsed.get("action") in {"direct_tool", "planner", "code", "deep_agent"}:
                    parsed["escalation_confidence"] = float(old_conf or 0.85)
                else:
                    parsed["escalation_confidence"] = 0.0

            if "execute_confidence" not in parsed:
                if parsed.get("action") in {"direct_tool", "planner", "code", "deep_agent"}:
                    parsed["execute_confidence"] = float(old_conf or 0.85)
                else:
                    parsed["execute_confidence"] = 0.0

            return parsed

        return {
            "speak": raw.strip() or "I can discuss that.",
            "transcript": user_text,
            "intent": "chat",
            "action": "chat_only",
            "route": "live",
            "tool": None,
            "chat_confidence": 0.5,
            "escalation_confidence": 0.0,
            "execute_confidence": 0.0,
            "args": {},
        }

    except Exception as e:
        emit_event("warning", "Live router failed", {"error": str(e)})
        return {
            "speak": "",
            "transcript": user_text,
            "intent": "fallback",
            "action": "chat_only",
            "route": "live",
            "tool": None,
            "chat_confidence": 0.0,
            "escalation_confidence": 0.0,
            "execute_confidence": 0.0,
            "args": {},
        }
def load_mode_profiles() -> Dict[str, Any]:
    try:
        if MODE_PROFILE_PATH.exists():
            data = json.loads(MODE_PROFILE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as e:
        debug(f"Failed to load mode_profiles.json: {e}")
    return DEFAULT_MODE_PROFILES


def load_profile_by_id(profile_id: str) -> Dict[str, Any]:
    if not profile_id:
        return {}
    try:
        profile_file = PROFILES_DIR / f"{profile_id}.json"
        if profile_file.exists():
            return json.loads(profile_file.read_text(encoding="utf-8"))
    except Exception as e:
        debug(f"Failed to load profile {profile_id}: {e}")
    return {}


def load_active_profile(profile_override: Optional[str] = None) -> Dict[str, Any]:
    if profile_override:
        profile = load_profile_by_id(profile_override)
        if profile:
            return profile
    try:
        if ACTIVE_PROFILE_PATH.exists():
            data = json.loads(ACTIVE_PROFILE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("active"):
                profile = load_profile_by_id(str(data.get("active")))
                if profile:
                    return profile
            if isinstance(data, dict) and data.get("systemPrompt"):
                return data
    except Exception as e:
        debug(f"Failed to load active profile: {e}")
    return {}


def get_profile_options(profile_override: Optional[str] = None) -> Dict[str, Any]:
    profile = load_active_profile(profile_override=profile_override)
    options: Dict[str, Any] = {}
    temperature = profile.get("temperature")
    if isinstance(temperature, (int, float)):
        options["temperature"] = temperature
    top_p = profile.get("topP")
    if isinstance(top_p, (int, float)):
        options["top_p"] = top_p
    return options
def return_chat_response(self, payload: dict, user_text: str, reply_text: str, route: str, model: str):
    write_chat_log("user", user_text, route=route, model=model)
    write_chat_log("assistant", reply_text, route=route, model=model)
    self._json_response(payload)

def resolve_runtime_mode(route: str, selected_tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = load_mode_profiles()
    defaults = cfg.get("defaults", {})
    overrides = cfg.get("tool_overrides", [])

    tool_names = set()
    for t in selected_tools:
        try:
            tool_names.add(t["function"]["name"])
        except Exception:
            continue

    for override in overrides:
        if override.get("route") != route:
            continue
        tools_any = set(override.get("tools_any", []))
        if tools_any and (tool_names & tools_any):
            return {
                "mode": override.get("mode", "conversation"),
                "persona": override.get("persona", "jarvis"),
                "tts_engine": override.get("tts_engine", "kokoro"),
                "tts_enabled": bool(override.get("tts_enabled", True)),
            }

    base = defaults.get(route, defaults.get("fast", {}))
    return {
        "mode": base.get("mode", "conversation"),
        "persona": base.get("persona", "jarvis"),
        "tts_engine": base.get("tts_engine", "kokoro"),
        "tts_enabled": bool(base.get("tts_enabled", True)),
    }


def write_runtime_mode(route: str, model: str, selected_tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    runtime = resolve_runtime_mode(route, selected_tools)
    payload = {
        **runtime,
        "route": route,
        "brain": model,
        "updated_at": now_iso(),
        "tools": [
            t["function"]["name"]
            for t in selected_tools
            if isinstance(t, dict) and isinstance(t.get("function"), dict)
        ],
    }
    try:
        ensure_dirs()
        RUNTIME_MODE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        debug(f"Failed writing runtime mode: {e}")
    return payload


def build_self_context(persona: Optional[str] = None) -> Dict[str, Any]:
    profile = load_active_profile(profile_override=persona)
    cfg = load_model_config()

    return {
        "identity": {"id": profile.get("id"), "label": profile.get("label"), "systemPrompt": profile.get("systemPrompt")},
        "models": {"routes": cfg.get("models", {}), "planner_model": cfg.get("planner_model")},
        "tool_count": len(TOOL_MAP),
        "available_routes": list(MODE_PROMPTS.keys()),
    }
def build_last_exchange_context() -> str:
    try:
        from scripts.chat_context import read_last_messages
    except Exception:
        try:
            from chat_context import read_last_messages
        except Exception:
            return ""

    try:
        last_user, last_assistant = read_last_messages()
    except Exception:
        return ""

    blocks = []

    if last_user:
        blocks.append(
            "[LAST USER MESSAGE]\n"
            f"{last_user}\n"
            "[/LAST USER MESSAGE]"
        )

    if last_assistant:
        blocks.append(
            "[LAST ASSISTANT MESSAGE]\n"
            f"{last_assistant}\n"
            "[/LAST ASSISTANT MESSAGE]"
        )

    return "\n\n".join(blocks)

def build_self_context_prompt(persona: Optional[str] = None, max_tools: int = 20) -> str:
    ctx = build_self_context(persona=persona)
    identity = ctx.get("identity", {})
    models = ctx.get("models", {})
    capabilities = ctx.get("capabilities", [])
    parts = ["Runtime self-context:"]
    parts.append(f"- Persona: {identity.get('label') or identity.get('id') or 'JARVIS'}")
    if models.get("routes"):
        parts.append(f"- Model routes: {models['routes']}")
    if models.get("planner_model"):
        parts.append(f"- Planner model: {models['planner_model']}")
    parts.append("- Available tools:")
    for item in capabilities[:max_tools]:
        parts.append(f"  - {item.get('tool', '')}: {item.get('description', '')}")
    if len(capabilities) > max_tools:
        parts.append(f"  - ...and {len(capabilities) - max_tools} more tools available")
    return "\n".join(parts)

def build_system_prompt_for_route(route: str, persona: Optional[str] = None) -> str:
    profile = load_active_profile(profile_override=persona)

    profile_prompt = (
        profile.get("systemPrompt") or ""
    ).strip() or "You are JARVIS, a capable local assistant."

    external_prompt_by_route = {
        "live": LIVE_CHAT_PROMPT_PATH,
        "fast": LIVE_CHAT_PROMPT_PATH,
        "reason": PLANNER_PROMPT_PATH,
        "code": CODER_PROMPT_PATH,
    }

    external_route_prompt = ""
    if route in external_prompt_by_route:
        external_route_prompt = load_prompt_file(external_prompt_by_route[route], "")

    if route == "code":
        coder_prompt = external_route_prompt or MODE_PROMPTS.get("code", "").strip()

        parts = [
            profile_prompt,
            coder_prompt,
            CODER_WORKSPACE_HINT.strip(),
            build_last_exchange_context(),
            build_short_term_context(),
            load_coder_memory(),
            build_self_context_prompt(persona=persona),
        ]
    else:
        mode_prompts = profile.get("modePrompts")
        profile_mode_prompt = ""

        if isinstance(mode_prompts, dict):
            profile_mode_prompt = (mode_prompts.get(route) or "").strip()

        route_prompt = (
            profile_mode_prompt
            or external_route_prompt
            or MODE_PROMPTS.get(route or "reason", "").strip()
        )
        parts = [
            profile_prompt,
            route_prompt,
            SYSTEM_ORCHESTRATOR_PROMPT.strip(),
            build_self_context_prompt(persona=persona),
        ]

    return "\n\n".join(part for part in parts if part and part.strip())
def save_coder_memory(summary: str, max_chars: int = 12000) -> None:
    CODER_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    old = ""
    if CODER_MEMORY_PATH.exists():
        old = CODER_MEMORY_PATH.read_text(encoding="utf-8", errors="ignore")

    new_text = (old.rstrip() + "\n\n" + summary.strip()).strip()

    if len(new_text) > max_chars:
        new_text = new_text[-max_chars:]

    CODER_MEMORY_PATH.write_text(new_text + "\n", encoding="utf-8")

def normalize_messages(messages: List[Dict[str, Any]], system_prompt: Optional[str] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    has_system = any(m.get("role") == "system" for m in messages)
    if not has_system:
        out.append({"role": "system", "content": system_prompt or SYSTEM_ORCHESTRATOR_PROMPT})
    for m in messages:
        role = m.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            continue
        item: Dict[str, Any] = {"role": role}
        if "content" in m:
            item["content"] = m.get("content", "")
        if "tool_calls" in m and isinstance(m["tool_calls"], list):
            item["tool_calls"] = m["tool_calls"]
        if "name" in m:
            item["name"] = m["name"]
        out.append(item)
    return out


def compact_context(messages: List[Dict[str, Any]], max_messages: int = MAX_CONTEXT_MESSAGES) -> List[Dict[str, Any]]:
    systems = [m for m in messages if m.get("role") == "system"]
    others = [m for m in messages if m.get("role") != "system"]
    if len(others) <= max_messages:
        trimmed = others
    else:
        first_user = next((m for m in others if m.get("role") == "user"), None)
        extra = 1 if first_user else 0
        tail_count = max(0, max_messages - extra)
        tail = others[-tail_count:] if tail_count > 0 else []
        trimmed = ([first_user] if first_user and first_user not in tail else []) + tail
    return systems[:1] + trimmed


def get_last_user_text(messages: List[Dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str):
                return content
            return safe_json_dumps(content)
    return ""

def should_use_kokoro(route: str, model: str) -> bool:
    route = (route or "").strip().lower()
    model = (model or "").strip().lower()

    if not KOKORO_ENABLED:
        return False

    if route in {"code", "deep"}:
        return False

    if "30b" in model or "31b" in model:
        return False

    return route in {"live", "fast", "tools", "reason"}


def sync_kokoro_for_route(route: str, model: str) -> None:
    if not KOKORO_ENABLED:
        return

    use_kokoro = should_use_kokoro(route, model)

    emit_event(
        "status",
        "Syncing Kokoro policy",
        {
            "route": route,
            "model": model,
            "use_kokoro": use_kokoro,
            "kokoro_running": is_kokoro_running(),
            "kokoro_host": KOKORO_HOST,
        },
    )

    if use_kokoro and not is_kokoro_running():
        emit_event(
            "warning",
            "Kokoro selected but not reachable",
            {"kokoro_host": KOKORO_HOST},
        )

def is_coder_model(model: str) -> bool:
    return "coder" in (model or "").lower()


def get_coder_tool() -> Optional[Dict[str, Any]]:
    return (
         TOOLS_BY_NAME.get("code_edit")
    )


def guess_coding_paths(user_text: str) -> List[str]:
    text = user_text or ""
    lower = text.lower()

    # 1. Explicit filename always wins
    explicit_file_patterns = [
        r"(?:save it to|save as|write to|create|make|to)\s+([A-Za-z0-9_.\-/]+\.(?:html|py|js|ts|tsx|jsx|css|json|md|txt))",
        r"\b([A-Za-z0-9_.\-/]+\.(?:html|py|js|ts|tsx|jsx|css|json|md|txt))\b",
    ]

    for pattern in explicit_file_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return [match.group(1).strip()]

    # 2. Known project files
    known_files = [
        "skills/news.py",
        "skills/radio.py",
        "skills/coding.py",
        "skills/loader.py",
        "scripts/react_server.py",
        "scripts/watcher.py",
        "config/models-config.json",
        "config/model_config.json",
        "config/models.json",
        "app/page.tsx",
    ]

    paths: List[str] = []

    for p in known_files:
        name = p.split("/")[-1].lower()
        stem = name.rsplit(".", 1)[0]
        if name in lower or stem in lower:
            paths.append(p)

    if "news" in lower and "skills/news.py" not in paths:
        paths.append("skills/news.py")

    if "radio" in lower and "skills/radio.py" not in paths:
        paths.append("skills/radio.py")

    # 3. Only fallback to skills for actual skill work
    if "skill" in lower and not paths:
        paths.append("skills")

    # 4. Default project root, not skills
    return paths or ["."]

def extract_tool_content(result: Any) -> str:
    # Already string
    if isinstance(result, str):
        try:
            data = json.loads(result)

            if isinstance(data, dict):
                ui = data.get("ui")

                if isinstance(ui, dict):
                    content = ui.get("content")
                    if isinstance(content, str):
                        return content

                speech = data.get("speech")
                if isinstance(speech, str):
                    return speech

                return json.dumps(
                    data,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )

            return result

        except Exception:
            return result

    # Dict/list/object fallback
    return json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        default=str,
    )

def normalized_route(requested_route: Optional[str], selected_tools: List[Dict[str, Any]]) -> str:
    if requested_route in VALID_ROUTES:
        return requested_route
    return infer_route_from_tools(selected_tools)


def call_ollama_once(model: str, messages: List[Dict[str, Any]], route: str, persona: Optional[str] = None, tools: Optional[List[Dict[str, Any]]] = None, stream: bool = False) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model,
        "messages": compact_context(normalize_messages(messages, system_prompt=build_system_prompt_for_route(route, persona=persona))),
        "stream": stream,
    }
    profile_options = get_profile_options(profile_override=persona)
    if profile_options:
        payload["options"] = profile_options
    if tools and model not in NO_TOOLS_MODELS and not is_coder_model(model):
        payload["tools"] = tools
    with request_ollama_chat(payload, timeout=CHAT_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))

# -----------------------------------------------------------------------------
# Tool selection
# -----------------------------------------------------------------------------
LAST_TELEGRAM_ACTION_AT = 0.0
def maybe_send_telegram_media(result: Any) -> bool:
    try:
        data = result
        if isinstance(result, str):
            data = json.loads(result)

        paths = []

        if isinstance(data, dict):
            for key in ["image_path", "path", "file", "filename"]:
                value = data.get(key)
                if isinstance(value, str) and value.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    paths.append(value)

            ui = data.get("ui")
            if isinstance(ui, dict):
                value = ui.get("path") or ui.get("image_path") or ui.get("file")
                if isinstance(value, str) and value.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    paths.append(value)

            images = data.get("images")
            if isinstance(images, list):
                for value in images:
                    if isinstance(value, str) and value.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                        paths.append(value)

        for image_path in paths:
            p = Path(image_path).expanduser()
            if p.exists():
                TELEGRAM_GATEWAY.send_photo(
                    TELEGRAM_NOTIFY_CHAT_ID,
                    str(p),
                    caption="Generated image"
                )
                return True

    except Exception as e:
        emit_event("warning", "Telegram media send failed", {"error": str(e)})

    return False

def telegram_chat_action(action: str = "typing") -> None:
    global LAST_TELEGRAM_ACTION_AT

    if not TELEGRAM_NOTIFY_CHAT_ID:
        return

    now = time.time()

    # Telegram typing indicator lasts a few seconds.
    # Do not send more often than every 4 seconds.
    if now - LAST_TELEGRAM_ACTION_AT < 4.0:
        return

    LAST_TELEGRAM_ACTION_AT = now

    try:
        TELEGRAM_GATEWAY.send_chat_action(TELEGRAM_NOTIFY_CHAT_ID, action)
    except Exception as e:
        debug(f"Telegram chat action failed: {e}")

def parse_plan_command(text: str) -> tuple[str, Optional[str]]:
    parts = (text or "").strip().split()
    if not parts:
        return "", None

    command = parts[0].lower()
    plan_id = parts[1] if len(parts) > 1 else None

    return command, plan_id

def build_planner_catalog() -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    for tool in TOOLS:
        try:
            name = tool["function"]["name"]
            description = tool["function"].get("description", "")
        except Exception:
            continue
        meta = TOOL_SKILL_META.get(name, {})
        catalog.append(
            {
                "name": name,
                "description": description,
                "intent_aliases": meta.get("intent_aliases", []),
                "keywords": meta.get("keywords", []),
                "direct_match": meta.get("direct_match", []),
                "route": meta.get("route", "reason"),
            }
        )
    return catalog


def build_planner_prompt(user_text: str) -> str:
    compact_catalog = []
    for item in build_planner_catalog():
        compact_catalog.append(
            {
                "name": item["name"],
                "description": item.get("description", ""),
                "aliases": item.get("intent_aliases", []),
                "route": item.get("route", "reason"),
                "keywords": item.get("keywords", [])[:12],
            }
        )
    return (
        "/no_think\n"
        "You select the minimum useful tools for a user request.\n"
        "Return ONLY valid JSON with this exact shape:\n"
        '{"tools":["tool_name_1","tool_name_2"]}\n'
        "If no tools are needed, return:\n"
        '{"tools":[]}\n\n'
        "Rules:\n"
        "- Choose the minimum useful tools.\n"
        "- Prefer exact tool names from the catalog.\n"
        "- Do not invent tool names.\n"
        "- Do not return aliases, only tool names.\n"
        "- If the request is simple conversation, return no tools.\n"
        "- If a direct answer is sufficient, return no tools.\n\n"
        f"Tool catalog:\n{json.dumps(compact_catalog, ensure_ascii=False)}\n\n"
        f"User request:\n{user_text}\n"
    )

def summarize_step_result(content: str, limit: int = 600) -> str:
    text = strip_thinking_tags(content or "").strip()
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL).strip()

    if "APPLY FAILED" in text:
        return "Patch generation completed, but applying the patch failed."

    if "--- FILE:" in text:
        files = re.findall(r"--- FILE:\s*(.+)", text)
        if files:
            return "Updated: " + ", ".join(f.strip() for f in files[:5])

    if len(text) > limit:
        text = text[:limit].rstrip() + "..."

    return text or "Step completed."

def parse_planner_response(answer: str) -> List[str]:
    data = parse_json_object_from_text(answer)
    if data:
        tools = data.get("tools", [])
        if isinstance(tools, list):
            return [item.strip() for item in tools if isinstance(item, str) and item.strip()]
    text = strip_thinking_tags(answer or "").strip()
    if not text:
        return []
    return [p.strip() for p in text.split(",") if p.strip()]


def dedupe_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for tool in tools:
        try:
            name = tool["function"]["name"]
        except Exception:
            continue
        if name not in seen:
            seen.add(name)
            out.append(tool)
    return out


def resolve_intent_or_tool_names(names: List[str]) -> List[Dict[str, Any]]:
    resolved: List[Dict[str, Any]] = []
    for raw_name in names:
        name = (raw_name or "").strip().lower()
        if not name:
            continue
        if name in TOOLS_BY_NAME:
            resolved.append(TOOLS_BY_NAME[name])
            continue
        for candidate in INTENT_TOOL_CANDIDATES.get(name, []):
            if candidate in TOOLS_BY_NAME:
                resolved.append(TOOLS_BY_NAME[candidate])
    return dedupe_tools(resolved)


def direct_tools_for_text(user_text: str) -> List[Dict[str, Any]]:
    text = (user_text or "").lower()
    matched_tool_names: List[str] = []
    for tool_name, phrases in TOOL_DIRECT_MATCH.items():
        if any(phrase in text for phrase in phrases):
            matched_tool_names.append(tool_name)
    for intent_alias, tool_names in INTENT_TOOL_CANDIDATES.items():
        if intent_alias in text:
            matched_tool_names.extend(tool_names)
    return dedupe_tools([TOOLS_BY_NAME[name] for name in matched_tool_names if name in TOOLS_BY_NAME])
def build_live_tool_catalog(max_tools: int = 40) -> str:
    catalog = []

    for tool_name, tool in sorted(TOOLS_BY_NAME.items()):
        fn = tool.get("function", {})
        meta = TOOL_SKILL_META.get(tool_name, {})

        catalog.append({
            "name": tool_name,
            "description": fn.get("description", "")[:300],
            "parameters": fn.get("parameters", {}),
            "intent_aliases": meta.get("intent_aliases", []),
            "keywords": meta.get("keywords", []),
            "direct_match": meta.get("direct_match", []),
        })

    return json.dumps(catalog[:max_tools], ensure_ascii=False)

def select_tools_by_hints(user_text: str) -> List[Dict[str, Any]]:
    text = (user_text or "").lower()
    matched_tool_names: List[str] = []
    for tool_name, hints in TOOL_HINTS.items():
        if any(hint in text for hint in hints):
            matched_tool_names.append(tool_name)
    for tool_name, keywords in TOOL_KEYWORDS.items():
        if any((kw or "").lower() in text for kw in keywords):
            matched_tool_names.append(tool_name)
    return dedupe_tools([TOOLS_BY_NAME[name] for name in matched_tool_names if name in TOOLS_BY_NAME])


def likely_needs_tools(user_text: str) -> bool:
    text = (user_text or "").lower()
    return bool(direct_tools_for_text(text) or select_tools_by_hints(text))


def select_tools_keyword(user_text: str, max_tools: int = MAX_TOOL_SELECTION) -> List[Dict[str, Any]]:
    scores: Dict[str, int] = {}
    text = (user_text or "").lower()
    for tool_name, keywords in TOOL_KEYWORDS.items():
        score = sum(1 for kw in keywords if (kw or "").lower() in text)
        if score > 0:
            scores[tool_name] = score
    top = sorted(scores, key=scores.get, reverse=True)[:max_tools]
    return [TOOLS_BY_NAME[name] for name in top if name in TOOLS_BY_NAME]


def get_effective_planner_model(user_text: str, requested_route: Optional[str], requested_model: Optional[str]) -> str:
    text = (user_text or "").strip().lower()
    words = len(text.split())
    simple_patterns = ["weather", "forecast", "news", "volume", "timer", "radio", "open", "play", "pause", "stop", "mute", "unmute"]
    if requested_route == "fast" or words <= 12:
        if any(p in text for p in simple_patterns):
            cfg = load_model_config()
            return str((cfg.get("models") or {}).get("fast", "qwen3:8b"))
    return get_planner_model()

def get_active_task(task_graph_path: Path) -> Optional[dict]:
    graph = load_task_graph(task_graph_path)

    active_id = graph.get("active_task_id")
    if not active_id:
        return None

    return graph.get("tasks", {}).get(active_id)


def get_task_by_id(task_graph_path: Path, task_id: str) -> Optional[dict]:
    graph = load_task_graph(task_graph_path)
    return graph.get("tasks", {}).get(task_id)

def select_tools_via_llm(user_text: str, requested_route: Optional[str] = None, requested_model: Optional[str] = None) -> List[Dict[str, Any]]:
    planner_model = get_effective_planner_model(user_text=user_text, requested_route=requested_route, requested_model=requested_model)
    prompt = build_planner_prompt(user_text)
    payload = {
        "model": planner_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"num_predict": 192, "temperature": 0},
    }
    try:
        emit_event("plan", "Selecting tools", {"planner_model": planner_model})
        with request_ollama_chat(payload, timeout=PLANNER_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            emit_event(
                "code_phase",
                "Coding planner full response",
                {"route": "code",
                    "model": planner_model,
                    "planner_model": planner_model,
                    "data": data,
                },
            )
        answer = strip_thinking_tags(data.get("message", {}).get("content", "")).strip()

        selected_names = parse_planner_response(answer)
        if not selected_names:
            emit_event("plan", "Planner selected no tools",  {"route": "code",
                    "model": planner_model,
                    "planner_model": planner_model,
                    "data": data,
                })
            return []
        selected: List[Dict[str, Any]] = []
        selected_names_seen = set()
        for name in selected_names:
            lowered = name.strip().lower()
            if not lowered or lowered in selected_names_seen:
                continue
            selected_names_seen.add(lowered)
            if lowered in TOOLS_BY_NAME:
                selected.append(TOOLS_BY_NAME[lowered])
                continue
            for tool in resolve_intent_or_tool_names([lowered]):
                try:
                    tool_name = tool["function"]["name"]
                except Exception:
                    continue
                if tool_name not in {t["function"]["name"] for t in selected}:
                    selected.append(tool)
        if not selected:
            emit_event("warning", "Planner returned no resolvable tools, using keyword fallback", {"raw_answer": answer})
            return select_tools_keyword(user_text)
        selected = dedupe_tools(selected)[:MAX_TOOL_SELECTION]
        emit_event("plan", "Planner selected tools", {"tools": [t["function"]["name"] for t in selected], "raw_answer": answer, "planner_model": planner_model})
        return selected
    except urllib.error.HTTPError as e:
        try:
            error_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = "<no error body>"
        emit_event("warning", "Planner failed, using keyword fallback", {"error": f"HTTP {e.code} {e.reason}", "body": error_body, "planner_model": planner_model})
        return select_tools_keyword(user_text)
    except Exception as e:
        emit_event("warning", "Planner failed, using keyword fallback", {"error": str(e), "planner_model": planner_model})
        return select_tools_keyword(user_text)


def choose_tools(user_text: str, requested_route: Optional[str] = None, requested_model: Optional[str] = None) -> List[Dict[str, Any]]:
    # Code route must be deterministic.
    # Do not use planner/hints/keywords for coding tasks.
    if requested_route == "code":
        coder_tool = get_coder_tool()
        return [coder_tool] if coder_tool else []

    text = user_text or ""
    direct = direct_tools_for_text(text)
    if direct:
        direct = dedupe_tools(direct)[:MAX_TOOL_SELECTION]
        emit_event("plan", "Direct tool selection from metadata", {"tools": [t["function"]["name"] for t in direct]})
        return direct
    selected = select_tools_via_llm(text, requested_route=requested_route, requested_model=requested_model)
    if selected:
        selected = dedupe_tools(selected)[:MAX_TOOL_SELECTION]
        emit_event("plan", "Planner tool selection used", {"tools": [t["function"]["name"] for t in selected]})
        return selected
    hinted = select_tools_by_hints(text)
    if hinted:
        hinted = dedupe_tools(hinted)[:MAX_TOOL_SELECTION]
        emit_event("plan", "Hint-based tool selection used", {"tools": [t["function"]["name"] for t in hinted]})
        return hinted
    keyword_tools = select_tools_keyword(text)
    if keyword_tools:
        keyword_tools = dedupe_tools(keyword_tools)[:MAX_TOOL_SELECTION]
        emit_event("plan", "Keyword tool selection used", {"tools": [t["function"]["name"] for t in keyword_tools]})
        return keyword_tools
    emit_event("plan", "No tools selected", {"user_text": text[:120]})
    return []


def should_select_tools(user_text: str, requested_route: Optional[str], requested_model: Optional[str]) -> bool:
    text = (user_text or "").strip()
    lower = text.lower()
    if not text:
        return False
    # For code route, direct coder-skill switching handles tool choice later.
    if requested_route == "code" and "coder" in (requested_model or "").lower():
        return False
    if len(text.split()) <= 12 and not likely_needs_tools(lower):
        return False
    if requested_route == "fast" and not likely_needs_tools(lower):
        return False
    return likely_needs_tools(lower)

def extract_last_patch_from_anything(value: Any) -> str:
    text = extract_tool_content(value)

    # If full agent JSON contains observations, parse and take last code_edit ui.content
    try:
        data = json.loads(text)
        observations = data.get("observations", [])
        if isinstance(observations, list):
            for obs in reversed(observations):
                raw = obs.get("observation")
                if not raw:
                    continue
                raw_data = json.loads(raw) if isinstance(raw, str) else raw
                ui = raw_data.get("ui") if isinstance(raw_data, dict) else None
                patch = ui.get("content") if isinstance(ui, dict) else None
                if isinstance(patch, str) and "--- FILE:" in patch:
                    return normalize_patch_text(patch)
    except Exception:
        pass

    return normalize_patch_text(text)

def is_simple_direct_chat(user_text: str, selected_tools: List[Dict[str, Any]], route: str) -> bool:
    return not selected_tools and route == "fast" and len((user_text or "").split()) <= 12

# -----------------------------------------------------------------------------
# Route inference and tool execution
# -----------------------------------------------------------------------------


def detect_route(message: str, source: str = "") -> str:
    text = (message or "").lower()
    source = (source or "").lower()
    if source in {"codex", "codex_ui", "code_ui"}:
        return "code"
    code_keywords = [
        "code", "python", "javascript", "typescript", "next.js", "react", "bug", "error",
        "stack trace", "traceback", "function", "class", "api", "endpoint", "compile", "fix this",
        "refactor", "implement", "write script", "patch", "diff", "git", "repo", "file", "server", "skill",
    ]
    if any(k in text for k in code_keywords):
        return "code"
    return "reason"


def infer_route_from_tools(selected_tools: List[Dict[str, Any]]) -> str:
    if not selected_tools:
        return "reason"
    routes: List[str] = []
    for tool in selected_tools:
        try:
            name = tool["function"]["name"]
        except Exception:
            continue
        route = TOOL_ROUTE_HINTS.get(name)
        if route:
            routes.append(route)
    if "code" in routes:
        return "code"
    if "deep" in routes:
        return "deep"
    if "reason" in routes:
        return "reason"
    if "tools" in routes:
        return "tools"
    if "fast" in routes:
        return "fast"
    return "tools"


def make_tool_message(name: str, result: Any) -> Dict[str, Any]:
    return {"role": "tool", "name": name, "content": truncate_text(result)}


def normalize_tool_calls(assistant_msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_calls = assistant_msg.get("tool_calls") or []
    normalized = []
    for idx, call in enumerate(raw_calls):
        fn = call.get("function", {}) if isinstance(call, dict) else {}
        fn_name = fn.get("name", "")
        fn_args = fn.get("arguments", {})
        if isinstance(fn_args, str):
            try:
                fn_args = json.loads(fn_args)
            except Exception:
                fn_args = {}
        if not isinstance(fn_args, dict):
            fn_args = {}
        normalized.append({"id": call.get("id", f"tool_{idx}"), "type": "function", "function": {"name": fn_name, "arguments": fn_args}})
    return normalized

def execute_tool(fn_name: str, fn_args: Dict[str, Any]) -> str:
    executor = TOOL_MAP.get(fn_name)
    if not executor:
        emit_event("warning", f"Unknown tool {fn_name}")
        return f"Unknown tool: {fn_name}"

    started = time.time()
    tool_payload = {
        "tool": fn_name,
        "args": fn_args,
    }

    if fn_name == "code_edit":
        tool_payload["coder_task"] = fn_args.get("task")
        tool_payload["coder_path"] = fn_args.get("path")
        tool_payload["coder_mode"] = fn_args.get("mode")

    emit_event("tool_start", f"Running tool {fn_name}", tool_payload)

    try:
        result = executor(**fn_args)
        
        increment_tool_usage(fn_name)
        if fn_name == "code_edit":
            emit_event(
                "code_edit_output",
                "Coder tool returned output",
                {
                    "tool": fn_name,
                    "result_preview": truncate_text(result, 4000),
                    "path": fn_args.get("path"),
                    "mode": fn_args.get("mode"),
                },
            )

        elapsed = time.time() - started
        preview = truncate_text(extract_tool_content(result), 3000)

        debug(f"Tool ok: {fn_name} in {elapsed:.2f}s")

        emit_event(
            "tool_result",
            f"Tool {fn_name} completed",
            {
                "tool": fn_name,
                "elapsed_sec": round(elapsed, 3),
                "result_preview": preview,
            },
        )

        if isinstance(result, dict):
            emit_event(
                "skill_result",
                f"Skill {fn_name} returned structured result",
                {"tool": fn_name, "result": result},
            )
            return json.dumps(result, ensure_ascii=False)

        return truncate_text(result)

    except Exception as e:
        elapsed = time.time() - started
        debug(f"Tool failed: {fn_name} in {elapsed:.2f}s :: {e}")
        emit_event(
            "warning",
            f"Tool {fn_name} failed",
            {
                "tool": fn_name,
                "elapsed_sec": round(elapsed, 3),
                "error": str(e),
            },
        )
        return truncate_text({
            "error": str(e),
            "tool": fn_name,
            "traceback": traceback.format_exc(limit=3),
        })
    
def send_flux_result_to_telegram(result: Any) -> bool:
    try:
        data = result

        if isinstance(result, str):
            data = json.loads(result)

        if not isinstance(data, dict):
            return False

        image_path = (
            data.get("image_path")
            or data.get("path")
            or data.get("file")
            or data.get("output")
        )

        if not image_path:
            ui = data.get("ui")
            if isinstance(ui, dict):
                image_path = (
                    ui.get("image_path")
                    or ui.get("path")
                    or ui.get("file")
                    or ui.get("output")
                )

        if not image_path:
            emit_event("warning", "Flux result had no image path", {"result": data})
            return False

        path = Path(str(image_path)).expanduser()

        if not path.is_absolute():
            path = PROJECT_ROOT / path

        path = path.resolve()

        if not path.exists():
            emit_event("warning", "Flux image path does not exist", {"path": str(path)})
            return False

        TELEGRAM_GATEWAY.send_photo(
            TELEGRAM_NOTIFY_CHAT_ID,
            str(path),
            caption="🎨 Flux image generated",
        )

        emit_event("status", "Flux image sent to Telegram", {"path": str(path)})
        return True

    except Exception as e:
        emit_event("warning", "Flux Telegram image send failed", {"error": str(e)})
        return False
    
def wait_for_ollama(max_wait_sec: int = 30) -> bool:
    emit_event("status", "Waiting for Ollama", {"host": OLLAMA_HOST})
    for _ in range(max_wait_sec):
        try:
            tags = request_ollama_tags()
            emit_event("status", "Ollama ready", {"model_count": len(tags.get("models", []))})
            return True
        except Exception:
            time.sleep(1)
    emit_event("warning", "Ollama not ready in time", {"host": OLLAMA_HOST})
    return False


@dataclass
class ChatRun:
    request_id: str
    model: str
    started_at: float = field(default_factory=time.time)
    selected_tools: List[str] = field(default_factory=list)
    iterations: int = 0
    used_tools: bool = False

    def duration_ms(self) -> int:
        return int((time.time() - self.started_at) * 1000)

# -----------------------------------------------------------------------------
# Core chat loop
# -----------------------------------------------------------------------------


def react_chat(model: str, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None, route: str = "reason", persona: Optional[str] = None) -> Dict[str, Any]:
    tools = tools or []
    system_prompt = build_system_prompt_for_route(route, persona=persona)
    normalized_messages = compact_context(normalize_messages(messages, system_prompt=system_prompt))

    # Critical: qwen coder models do not receive native Ollama tools.
    use_tools = (not is_coder_model(model)) and model not in NO_TOOLS_MODELS and len(tools) > 0

    run = ChatRun(request_id=str(uuid.uuid4())[:8], model=model, selected_tools=[t["function"]["name"] for t in tools])
    debug(f"run={run.request_id} model={model} route={route} persona={persona} selected_tools={run.selected_tools} use_tools={use_tools}")
    emit_event("status", "Chat run started", {"request_id": run.request_id, "model": model, "route": route, "persona": persona, "tools": run.selected_tools, "use_tools": use_tools})

    last_data: Dict[str, Any] = {"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": "No response generated."}, "done": True}

    for iteration in range(1, MAX_ITERATIONS + 1):
        run.iterations = iteration
        body: Dict[str, Any] = {"model": model, "messages": normalized_messages, "stream": False}
        profile_options = get_profile_options(profile_override=persona)
        if profile_options:
            body["options"] = profile_options
        if use_tools:
            body["tools"] = tools

        try:
            emit_event("status", "Calling Ollama", {"request_id": run.request_id, "iteration": iteration, "model": model, "route": route, "persona": persona, "use_tools": use_tools})
            with request_ollama_chat(body, timeout=CHAT_TIMEOUT_SEC) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                error_body = "<no error body>"
            if e.code == 400 and use_tools:
                debug(f"{model} rejected tools. Marking as no-tools model. body={error_body}")
                emit_event("warning", f"{model} rejected tools, retrying without tools", {"request_id": run.request_id, "iteration": iteration, "body": error_body})
                NO_TOOLS_MODELS.add(model)
                use_tools = False
                continue
            emit_event("warning", "Ollama HTTP error", {"request_id": run.request_id, "code": e.code, "reason": e.reason, "body": error_body})
            return {"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": f"Error calling Ollama: HTTP {e.code} {e.reason}"}, "done": True}
        except Exception as e:
            emit_event("warning", "Ollama request failed", {"request_id": run.request_id, "error": str(e)})
            return {"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": f"Error calling Ollama: {e}"}, "done": True}

        last_data = data
        assistant_msg = data.get("message", {}) or {}
        tool_calls = normalize_tool_calls(assistant_msg) if use_tools else []
        content_preview = (assistant_msg.get("content") or "")[:120].replace("\n", " ")
        debug(f"run={run.request_id} iter={iteration} tool_calls={len(tool_calls)} preview={content_preview!r}")
        emit_event("status", "Model replied", {"request_id": run.request_id, "iteration": iteration, "tool_call_count": len(tool_calls), "content_preview": content_preview})

        if not tool_calls:
            content = data.get("message", {}).get("content", "")
            if isinstance(content, str):
                data["message"]["content"] = content.replace("**", "")
            append_log(f"[{datetime.now().strftime('%H:%M:%S')}] run={run.request_id} done model={model} route={route} persona={persona} iterations={run.iterations} duration_ms={run.duration_ms()}")
            emit_event("final", "Final response ready", {"request_id": run.request_id, "duration_ms": run.duration_ms(), "route": route, "model": model})
            return data

        normalized_messages.append({"role": "assistant", "content": assistant_msg.get("content", ""), "tool_calls": tool_calls})
        run.used_tools = True
        for call in tool_calls:
            fn_name = call["function"]["name"]
            fn_args = call["function"]["arguments"]
            debug(f"run={run.request_id} tool={fn_name} args={safe_json_dumps(fn_args)[:180]}")
            result = execute_tool(fn_name, fn_args)
            debug(f"run={run.request_id} tool={fn_name} result={result[:180]!r}")
            normalized_messages.append(make_tool_message(fn_name, result))

    append_log(f"[{datetime.now().strftime('%H:%M:%S')}] run={run.request_id} max_iterations model={model} route={route} persona={persona} iterations={run.iterations} duration_ms={run.duration_ms()}")
    emit_event("warning", "Max iterations reached", {"request_id": run.request_id, "duration_ms": run.duration_ms(), "route": route, "model": model})
    return last_data

# -----------------------------------------------------------------------------
# Streaming support
# -----------------------------------------------------------------------------


def stream_direct_chat(handler: "ReactHandler", model: str, messages: List[Dict[str, Any]], selected_tools: Optional[List[Dict[str, Any]]] = None, route: str = "reason", persona: Optional[str] = None) -> None:
    user_text = get_last_user_text(messages)
    user_text = clean_telegram_prefix(user_text)
    if selected_tools is None:
        selected_tools = choose_tools(user_text, requested_route=route, requested_model=model) if should_select_tools(user_text, route, model) else []

    tool_names = [t["function"]["name"] for t in selected_tools]
    debug(f"Streaming selected tools: {tool_names}")
    emit_event("status", "Streaming chat started", {"model": model, "route": route, "persona": persona, "tools": tool_names})

    if selected_tools and not is_coder_model(model):
        ack = random.choice(ACKS)
        write_bridge_status("thinking", ack)
        speak_ack(ack)
        if ENABLE_STREAM_STATUS:
            handler._write_sse_json({"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": ""}, "done": False, "status": f"Using tools: {', '.join(tool_names)}"})
        result = react_chat(model, messages, selected_tools, route=route, persona=persona)
        handler._write_sse_json(result)
        return

    body = {
        "model": model,
        "messages": compact_context(normalize_messages(messages, system_prompt=build_system_prompt_for_route(route, persona=persona))),
        "stream": True,
    }
    profile_options = get_profile_options(profile_override=persona)
    if profile_options:
        body["options"] = profile_options
    try:
        with request_ollama_chat(body, timeout=CHAT_TIMEOUT_SEC) as resp:
            for raw_line in resp:
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                handler.wfile.write((line + "\n").encode("utf-8"))
                handler.wfile.flush()
    except Exception as e:
        emit_event("warning", "Streaming error", {"error": str(e), "model": model, "route": route, "persona": persona})
        handler._write_sse_json({"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": f"Streaming error: {e}"}, "done": True})

# -----------------------------------------------------------------------------
# HTTP handler
# -----------------------------------------------------------------------------


class ReactHandler(BaseHTTPRequestHandler):
    server_version = "JarvisReact/3.0"

    def do_POST(self) -> None:
        try:
            self._do_POST_impl()
        except Exception as e:
            error_text = traceback.format_exc(limit=20)
            print("[REACT] UNHANDLED do_POST ERROR:", error_text)
            emit_event("warning", "Unhandled do_POST error", {"error": str(e), "traceback": error_text})
            try:
                self._json_response({"error": "Internal server error", "detail": str(e), "traceback": error_text}, code=500)
            except Exception:
                pass

    def _do_POST_impl(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/chat":
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
            body = json.loads(raw_body)
        except Exception:
            self._json_response({"error": "Invalid JSON body"}, code=400)
            return

        requested_model = body.get("model")
        requested_route = body.get("route")
        source = body.get("source", "")
        messages = body.get("messages", [])
        stream = bool(body.get("stream", False))

        if not isinstance(messages, list):
            self._json_response({"error": "messages must be a list"}, code=400)
            return

        user_text = get_last_user_text(messages)
        user_text = clean_telegram_prefix(user_text)
        #### REMove if needed after testing
    

        live_result = run_live_router(user_text)
        live_result = force_correct_common_tool(user_text, live_result)
        live_action = live_result.get("action")
        #live_confidence = float(live_result.get("confidence") or 0)
        chat_confidence = float(
            live_result.get("chat_confidence", 0)
        )

        escalation_confidence = float(
            live_result.get("escalation_confidence", 0)
)
        execute_confidence = float(
            live_result.get("execute_confidence", 0)
)

        live_speak = str(live_result.get("speak") or "").strip()
        write_chat_log("assistant", live_speak, route=live_action, model="live")
        live_transcript = str(live_result.get("transcript") or "").strip()
        live_tool = str(live_result.get("tool") or "").strip()
        live_intent = str(live_result.get("intent") or "").strip()
        live_args = live_result.get("args") or {}
        emit_event(
            "Live router",
            "Reply and confidence",
            {
                "speak": live_speak,
                "tool": live_tool,
                "escalation_confidence": escalation_confidence,
                "execute_confidence": execute_confidence,
                "chat_confidence": chat_confidence,
                "user_text": user_text[:200],
            },
        )
        if not isinstance(live_args, dict):
            live_args = {}

        if live_tool == "radio" and live_args.get("action") == "play" and not live_args.get("station"):
            live_action = "chat_only"
            live_speak = "Which radio station should I play?"
        notify_telegram(f"{live_speak}")
        if live_transcript:
            user_text = live_transcript
        #else:
        ##    user_text_for_routing = user_text
        if live_action == "chat_only" and (chat_confidence >= 0.70 or escalation_confidence == 0.0) and live_speak:
            #if source == "telegram":
            #    notify_telegram(live_speak)
            
            self._json_response({
                "model": "live_router",
                "created_at": now_iso(),
                "message": {
                    "role": "assistant",
                    "content": live_speak,
                },
                "done": True,
                "route": "live",
                "live": live_result,
            })
            return
        ##elif source == "telegram":
        ##    notify_telegram(f"{live_speak}")
        #if live_action == "direct_tool":
        live_direct_skill_match = resolve_skill_command(user_text)
        live_tool_fixed = live_tool
        
        if live_direct_skill_match and live_direct_skill_match.get("score", 0) >= 0.88:
            live_tool_fixed = live_direct_skill_match.get("tool_name")
        if (
            live_action == "direct_tool"
            and execute_confidence >= 0.75
            and live_tool_fixed
            and live_tool_fixed in TOOL_MAP
        ):
            live_result = complete_tool_args_with_meta(
            tool_name=live_tool_fixed,
            user_text=user_text,
            parsed=live_result,
            )
            live_args = live_result.get("args") or {}
            result = execute_tool(live_tool_fixed, live_args)
            sent_media = False
            if source == "telegram" and live_tool_fixed == "flux":
                sent_media = send_flux_result_to_telegram(result)
                if source == "telegram":
                    if sent_media:
                        notify_telegram("Image sent to Telegram!")
                    else:
                        notify_telegram("Failed to send image to Telegram.")
            content = extract_tool_content(result)
            reply = content or live_speak or f"Done: {live_tool_fixed}"
            if log_chat_event and reply.strip():
                try:
                    write_chat_log("user", user_text, route=route, model=model)
                    write_chat_log("assistant", reply_text, route=route, model=model)
                except Exception as e:
                    print(f"[CHAT_LOG] assistant and user log failed: {e}")
            ##if source == "telegram":
            ##    notify_telegram(reply)
            
            emit_event(
                "router",
                "Live router decision",
                {
                    "action": live_result.get("action"),
                    "route": live_result.get("route"),
                    "tool": live_tool_fixed,
                    "chat_confidence": live_result.get("chat_confidence"),
                    "escalation_confidence": live_result.get("escalation_confidence"),
                    "execute_confidence": live_result.get("execute_confidence"),
                    "intent": live_result.get("intent"),
                    "speak": live_result.get("speak", "")[:300],
                },
            )
            self._json_response({
                "model": "live_router",
                "created_at": now_iso(),
                "message": {
                    "role": "assistant",
                    "content": reply,
                },
                "done": True,
                "route": "tools",
                "format": "direct_tool",
                "tool": live_tool,
                "tool_result": result,
                "live": live_result,
            })
            return
    
        normalized_user = user_text.strip().lower()

        is_code_request = any(x in normalized_user for x in [
            "code",
            "fix",
            "edit",
            "patch",
            "implement",
            "create script",
            "save it",
            "write it",
            ".py",
            ".js",
            ".ts",
            "tester",
            "test_",
            "react_server.py",
        ])

        if live_action == "code" or live_result.get("route") == "code":
            requested_route = "code"

        if is_code_request:
            requested_route = "code"

        # Disable fuzzy skill matching for coder requests
        if requested_route == "code":
            direct_skill_match = None
        else:
            direct_skill_match = resolve_skill_command(user_text)
            if direct_skill_match and direct_skill_match.get("score", 0) >= 0.88:
                live_result.update({
                    "action": "direct_tool",
                    "route": "tools",
                    "tool": direct_skill_match["tool_name"],
                    "chat_confidence": 0.0,
                    "escalation_confidence": 1.0,
                    "execute_confidence": 1.0,
                    "args": live_result.get("args") or {},
                })
                requested_route = "tools"

        live_action = live_result.get("action")
        if live_action == "chat_only":
            requested_route = "live"
        elif live_action == "direct_tool":
            requested_route = "tools"
        elif live_action == "planner":
            requested_route = "reason"
        elif live_action == "code":
            requested_route = "code"
        elif live_action == "deep_agent":
            requested_route = "deep"
        if direct_skill_match:
            requested_route = "tools"
        workflow_state = load_workflow_state()

        if workflow_state:
            reply = continue_markdown_workflow(user_text, workflow_state)

            self._json_response({
                "model": "workflow",
                "created_at": now_iso(),
                "message": {"role": "assistant", "content": reply},
                "done": True,
            })
            return

        md_skill = match_markdown_skill(user_text)

        if md_skill:
            body["markdown_skill"] = md_skill
            requested_route = md_skill.get("route", requested_route or "reason")

            if md_skill.get("type") == "interview_workflow":
                state = {
                    "skill": md_skill.get("name"),
                    "skill_path": md_skill.get("path"),
                    "phase": "interview",
                    "answers": {},
                }

                save_workflow_state(state)

                question = get_next_workflow_question(state)

                self._json_response({
                    "model": "workflow",
                    "created_at": now_iso(),
                    "message": {
                        "role": "assistant",
                        "content": question or "Workflow started.",
                    },
                    "done": True,
                })
                return
            if live_action == "chat_only" and requested_route == "live" and live_intent == "chat_history_query":
                model = resolve_model(requested_model=requested_model, route="live")

                try:
                    from scripts.chat_context import read_last_chat_log_chars
                except Exception:
                    from chat_context import read_last_chat_log_chars

                recent_chat = read_last_chat_log_chars(max_chars=4000)

                history_context = (
                    "Recent chat log. Use this to answer the user's question about recent discussion. "
                    "Do not dump the log unless the user asks. Answer concisely.\n\n"
                    + recent_chat
                )

                messages.insert(1, {
                    "role": "system",
                    "content": history_context,
                })

                data = call_ollama_once(
                    model=model,
                    messages=messages,
                    route="live",
                    persona=None,
                    tools=None,
                    stream=False,
                )

                reply_text = (
                    data.get("message", {}).get("content", "")
                    if isinstance(data, dict)
                    else ""
                )
                write_chat_log("assistant", reply_text, route=route, model=model)
                if log_chat_event and reply_text.strip():
                    try:
                        write_chat_log("user", user_text, route=route, model=model)
                        write_chat_log("assistant", reply_text, route=route, model=model)
                    except Exception as e:
                        print(f"[CHAT_LOG] assistant log failed: {e}")
                if source == "telegram" and reply_text.strip():
                    notify_telegram("test"+reply_text.strip())

                self._json_response({
                    **data,
                    "route": "live",
                    "live": live_result,
                    "chat_history_used": True,
                })
                return
            if live_result.get("action") == "chat_only" and requested_route == "live":
                model = resolve_model(requested_model=requested_model, route="live")
                self_context = build_self_context_prompt(persona=persona, max_tools=20)

                messages.insert(1, {
                    "role": "system",
                    "content": (
                        "JARVIS self-context. Use this to understand who you are and what you can do. "
                        "Do not over-explain it unless asked.\n\n"
                        + self_context
                    )
                })
                data = call_ollama_once(
                    model=model,
                    messages=messages,
                    route="live",
                    persona=None,
                    tools=None,
                    stream=False,
                )

                reply_text = (
                    data.get("message", {}).get("content", "")
                    if isinstance(data, dict)
                    else ""
                )
                write_chat_log("assistant", reply_text, route=route, model=model)
                if source == "telegram" and reply_text.strip():
                    notify_telegram(reply_text.strip())
                write_chat_log("assistant", reply_text, route=route, model=model)
                self._json_response({
                    **data,
                    "route": "live",
                    "live": live_result,
                })
                return
        # ------------------------------------------------------------
        # Memory context
        # ------------------------------------------------------------
        # IMPORTANT:
        # - user_text stays clean/raw for route detection, command parsing, and tool selection.
        # - planner_user_text may include memory hints for planning/reasoning only.
        # - memory must never override the current user command.
        # ------------------------------------------------------------

        plan_command, plan_command_id = parse_plan_command(user_text)
        lower_user = user_text.strip().lower()

        active_task_followups = {
            "proceed",
            "continue",
            "save it",
            "write it",
            "create it",
            "do it",
            "yes",
            "yes proceed",
            "show directory",
            "save it and show directory",
        }
        direct_command_prefixes = (
            "list skills",
            "show skills",
            "what skills",
            "reload skills",
            "play ",
            "stop radio",
            "timer ",
            "set timer",
            "health",
        )
        normalized_user = user_text.strip().lower()

        is_active_followup = normalized_user in active_task_followups
        skip_memory = (
            requested_route == "live"
            or bool(direct_skill_match)
            or  is_active_followup
            or bool(md_skill)
            or plan_command in {"proceed", "continue", "next", "run", "yes", "cancel"}
            or lower_user.startswith(direct_command_prefixes)
        )

        context_pack = ""
        planner_user_text = user_text

        if not skip_memory:
            context_pack = build_context_pack(user_text)

            if context_pack:
                context_system_message = {
                    "role": "system",
                    "content": (
                        "Memory context is optional background only. "
                        "The current user message is the command. "
                        "Do not change the user's intent based on memory. "
                        "If memory conflicts with the current command, ignore memory.\n\n"
                        + context_pack
                    ),
                }

                insert_at = 1 if messages and messages[0].get("role") == "system" else 0
                messages.insert(insert_at, context_system_message)

                planner_user_text = (
                    "USER COMMAND:\n"
                    f"{user_text}\n\n"
                    "OPTIONAL MEMORY HINTS:\n"
                    f"{context_pack[:2500]}\n\n"
                    "Instruction: obey USER COMMAND. Use memory only as supporting context."
                )
                emit_event(
                    "debug",
                    "Planner text",
                    {
                        "chars": len(planner_user_text),
                        "preview": planner_user_text[:4000],
                    },
                )
        #plan_command, plan_command_id = parse_plan_command(user_text)
##### planner

        if source == "telegram" and plan_command in {"proceed", "continue", "next", "run", "modify", "cancel","accept"}:
            requested_route = "code"
            requested_model = None

        if requested_route not in VALID_ROUTES:
            requested_route = detect_route(user_text, source)

        selected_tools: List[Dict[str, Any]] = []

        plan_command, plan_command_id = parse_plan_command(user_text)
        plan_decision = None

        if plan_command in {"proceed", "continue", "next", "run", "yes", "accept"}:
            plan_decision = {
                "action": "code",
                "route": "code",
                "chat_confidence": 0.0,
                "execution_confidence": 1.0,
                "continue_plan": True,
                "plan_action": "continue",
            }
            requested_route = "code"
            requested_model = None

        elif plan_command == "modify":
            plan_decision = {
                "action": "planner",
                "route": "reason",
                "chat_confidence": 1.0,
                "execution_confidence": 0.0,
                "continue_plan": True,
                "plan_action": "modify",
            }
            requested_route = "code"
            requested_model = None

        elif plan_command == "cancel":
            plan_decision = {
                "action": "code",
                "route": "code",
                "chat_confidence": 0.0,
                "execution_confidence": 1.0,
                "continue_plan": True,
                "plan_action": "cancel",
            }
            requested_route = "code"
            requested_model = None

        if direct_skill_match:
            selected_tools = [direct_skill_match["tool"]]
        elif plan_command in {"proceed", "continue", "next", "run", "modify", "cancel"}:
            selected_tools = []
        elif should_select_tools(user_text, requested_route, requested_model):
            selected_tools = choose_tools(
                user_text,
                requested_route=requested_route,
                requested_model=requested_model,
            )
        emit_event(
            "router",
            "Fuzzy skill command match",
            {
                "matched": bool(direct_skill_match),
                "tool": direct_skill_match.get("tool_name") if direct_skill_match else None,
                "phrase": direct_skill_match.get("phrase") if direct_skill_match else None,
                "score": direct_skill_match.get("score") if direct_skill_match else None,
                "user_text": user_text[:200],
            },
        )

        resolved_route = normalized_route(requested_route, selected_tools)

        is_code_request = any(x in user_text.lower() for x in [
            "code", "fix", "edit", "implement", "create script",
            "save it", ".py", "tester"
        ])

        if is_code_request or (plan_decision and plan_decision.get("execution_confidence", 0) >= 0.85):
            resolved_route = "code"

        if resolved_route == "code":
            requested_model = None
            model = resolve_model(requested_model=None, route="code")
            selected_tools = [TOOLS_BY_NAME["code_edit"]] if "code_edit" in TOOLS_BY_NAME else []
        else:
            model = resolve_model(requested_model=requested_model, route=resolved_route)

        route = resolved_route
        if log_chat_event:
            try:
                log_chat_event(
                    role="user",
                    content=user_text,
                    route=route,
                    model=model,
                )
            except Exception as e:
                print(f"[CHAT_LOG] user log failed: {e}")
        if user_text.lower().startswith("agent: continue"):
            task = get_active_task(TASK_GRAPH_PATH)

            if task:
                user_text = (
                    f"Continue this task.\n\n"
                    f"Original request:\n{task.get('user_request')}\n\n"
                    f"Steps:\n{json.dumps(task.get('steps', []), indent=2)}\n\n"
                    f"Recent events:\n{json.dumps(task.get('events', [])[-10:], indent=2)}"
                )

                body["task_id"] = task.get("id")
        # Optional agent executor.
        # Do NOT hijack code route, because direct coder route below has its own planner/apply flow.
        agent_requested = (
            route == "deep" 
            or user_text.lower().startswith(("agent:", "do task:"))
        )
    

        if agent_requested:
            result = run_agent_loop(
                user_message=planner_user_text,
                route=route,
                model=model,
                tools_by_name=TOOLS_BY_NAME,
                tool_map=TOOL_MAP,
                call_ollama_once=call_ollama_once,
                execute_tool=execute_tool,
                emit_event=emit_event,
                truncate_text=truncate_text,
                strip_thinking_tags=strip_thinking_tags,
                now_iso=now_iso,
                task_graph_path=TASK_GRAPH_PATH,
                task_id=body.get("task_id"),
                max_steps=8,
            )
            write_chat_log("assistant", reply_text, route=route, model=model)
            if isinstance(result, dict) and result.get("kind") == "report":
                report_path = write_analysis_report(
                    skill_name=tool_name,
                    plan_id=result.get("plan_id") or plan_id,
                    result=result,
                )

                emit_event("artifact", "Analysis report written", {
                    "plan_id": plan_id,
                    "skill": tool_name,
                    "path": str(report_path),
                })

                return {
                    "ok": True,
                    "kind": "report",
                    "path": str(report_path),
                    "message": f"Report written to {report_path}",
                }
            self._json_response({
                "model": model,
                "created_at": now_iso(),
                "message": {
                    "role": "assistant",
                    "content": result.get("answer", ""),
                },
                "done": True,
                "route": route,
                "format": "agent",
                "task_id": result.get("task_id"),
                "agent": {
                    "trace": result.get("trace", []),
                    "observations": result.get("observations", []),
                },
            })
            return
        # ------------------------------------------------------------------
        # Direct coder route
        # ------------------------------------------------------------------
        if resolved_route == "code" and is_coder_model(model):
            coder_tool = get_coder_tool()

            if coder_tool:
                selected_tools = [coder_tool]

            tool_names = [
                t["function"]["name"]
                for t in selected_tools
                if isinstance(t, dict) and isinstance(t.get("function"), dict)
            ]

            runtime_mode = write_runtime_mode(resolved_route, model, selected_tools)
            persona = runtime_mode.get("persona")

            try:
                sync_kokoro_for_route(resolved_route, model)
            except Exception as e:
                emit_event(
                    "warning",
                    "Orpheus sync failed",
                    {"route": resolved_route, "model": model, "error": str(e)},
                )

            emit_event(
                "status",
                "Incoming coder skill request",
                {
                    "requested_model": requested_model,
                    "requested_route": requested_route,
                    "source": source,
                    "resolved_route": resolved_route,
                    "resolved_model": model,
                    "tools": tool_names,
                    "user_preview": user_text[:140],
                    "runtime_mode": runtime_mode,
                },
            )

            if not selected_tools:
                self._json_response(
                    {
                        "model": model,
                        "created_at": now_iso(),
                        "message": {
                            "role": "assistant",
                            "content": f"Code route selected, but no coder skill was loaded. Expected tool: code_edit. Found: {tool_names}",
                        },
                        "done": True,
                    }
                )
                return

            ack = random.choice(ACKS)
            write_bridge_status("thinking", ack)
            append_log(f"[{datetime.now().strftime('%H:%M:%S')}] ACK: {ack}")
            speak_ack(ack)

            tool_name = selected_tools[0]["function"]["name"]

            paths = body.get("paths")
            if not isinstance(paths, list) or not paths:
                paths = guess_coding_paths(user_text)

            command, requested_plan_id = parse_plan_command(user_text)

            if requested_plan_id:
                active_plan = load_plan_by_id(requested_plan_id)
            else:
                active_plan = load_active_plan()
            if requested_plan_id and active_plan:
                save_active_plan(active_plan)
           
            emit_event(
                "code_phase",
                "Guessed coding paths",
                {
                    "paths": paths,
                },
            )

           
            if command == "cancel":

                if not requested_plan_id:
                    self._json_response({
                        "model": model,
                        "created_at": now_iso(),
                        "message": {"role": "assistant", "content": "Cancel failed: missing plan id."},
                        "done": True,
                    })
                    return

                plan = load_plan_by_id(requested_plan_id)
                if not plan:
                    self._json_response({
                        "model": model,
                        "created_at": now_iso(),
                        "message": {"role": "assistant", "content": f"Plan not found: {requested_plan_id}"},
                        "done": True,
                    })
                    return

                plan["status"] = "cancelled"
                plan["cancelled_at"] = now_iso()
                save_json(requested_plan_id, "status.json", plan)

                self._json_response({
                    "model": model,
                    "created_at": now_iso(),
                    "message": {"role": "assistant", "content": f"Cancelled plan {requested_plan_id}."},
                    "done": True,
                })
                return
            # Modify current plan / create new modified plan
            if command == "modify" or user_text.strip().lower().startswith("modify this plan:"):
                active_plan = build_simple_code_plan(planner_user_text, paths)
                
                emit_event(
                    "code_phase",
                    "Plan modified",
                    {
                        "phase": "plan_modified",
                        "plan_id": active_plan.get("plan_id"),
                        "steps": active_plan.get("steps", []),
                    },
                )
                save_json(active_plan["plan_id"], "plan.json", active_plan)

                append_event(
                    "plan.modified",
                    "Coding plan modified",
                    plan_id=active_plan.get("plan_id"),
                    route="code",
                    model=active_plan.get("planner_model"),
                    payload={"steps": active_plan.get("steps", [])},
                )
                save_active_plan(active_plan)
                
                self._json_response(
                    {
                        "model": model,
                        "created_at": now_iso(),
                        "message": {"role": "assistant", "content": render_plan(active_plan)},
                        "done": True,
                    }
                )
                return

            # New request creates plan first
            if command not in {"proceed", "continue", "next", "run", "yes","accept"}:
                active_plan = build_simple_code_plan(planner_user_text, paths)
    # ADD HERE
                plan_files = active_plan.get("files") or []
                has_plan_file = any("." in str(p).split("/")[-1] for p in plan_files)

                if needs_output_path(user_text, paths) and not has_plan_file:
                    plan_id = active_plan["plan_id"]

                    active_plan["state"] = "waiting_input"
                    active_plan["waiting_for"] = "output_path"
                    save_active_plan(active_plan)

                    self._json_response({
                        "model": model,
                        "created_at": now_iso(),
                        "message": {
                            "role": "assistant",
                            "content": (
                                f"PLAN_ID: {plan_id}\n\n"
                                "Where should I save the generated file?\n\n"
                                "Examples:\n"
                                "- love.html\n"
                                "- app/page.tsx\n"
                                "- scripts/test.py"
                            ),
                        },
                        "done": True,
                        "route": "code",
                    })
                    return

                # continue normal planner/coder flow
                emit_event(
                    "code_phase",
                    "Plan created",
                    {
                        "phase": "plan_created",
                        "plan_id": active_plan.get("plan_id"),
                        "steps": active_plan.get("steps", []),
                    },
                )
                append_event(
                    "planner.done",
                    "Planner returned coding plan",
                    plan_id=active_plan.get("plan_id"),
                    route="code",
                    model=active_plan.get("planner_model"),
                    payload={
                        "steps": active_plan.get("steps", []),
                        "paths": active_plan.get("paths", []),
                    },
                )
                save_active_plan(active_plan)
                self._json_response(
                    {
                        "model": model,
                        "created_at": now_iso(),
                        "message": {"role": "assistant", "content": render_plan(active_plan)},
                        "done": True,
                    }
                )
                return

            # Proceed / continue requires active plan
            if not active_plan:
                self._json_response(
                    {
                        "model": model,
                        "created_at": now_iso(),
                        "message": {
                            "role": "assistant",
                            "content": "No active coding plan found. Send the coding request first.",
                        },
                        "done": True,
                    }
                )
                return

            current_step = int(active_plan.get("current_step", 0))
            steps = active_plan.get("steps", [])

            if current_step >= len(steps):
                self._json_response(
                    {
                        "model": model,
                        "created_at": now_iso(),
                        "message": {"role": "assistant", "content": "Coding plan is already complete."},
                        "done": True,
                    }
                )
                return

            step = steps[current_step]

            emit_event(
                "code_phase",
                f"Running step {step.get('id')}: {step.get('goal')}",
                {
                    "phase": "running_step",
                    "plan_id": active_plan.get("plan_id"),
                    "step": step,
                    "paths": paths,
                },
            )

            fn_args = {
                "task": (
                    active_plan.get("user_request", user_text)
                    + "\n\nCurrent approved planner step:\n"
                    + str(step.get("goal", "Make a minimal patch."))
                    + "\n\nOUTPUT FORMAT STRICT:\n"
                    + "--- FILE: path/to/file.py\n"
                    + "@@\n"
                    + "<only changed function/helper blocks>\n\n"
                    + "Rules:\n"
                    + "- Must include --- FILE\n"
                    + "- Must include @@\n"
                    + "- No full files unless creating a new file\n"
                    + "- Minimal patch only\n"
                    + "- No shell commands\n"
                ),
                "path": paths[0] if paths else str(PROJECT_ROOT),
                "model": model,
                "mode": "patch",
            }

            emit_event(
                "status",
                "Executing coder skill directly",
                {
                    "route": resolved_route,
                    "model": model,
                    "tool": tool_name,
                    "args": fn_args,
                },
            )
            append_event(
                "coder.start",
                f"Coder started step {step.get('id')}",
                plan_id=active_plan.get("plan_id"),
                task_id=str(step.get("id")),
                route=resolved_route,
                model=model,
                payload={
                    "tool": tool_name,
                    "step": step,
                    "paths": paths,
                },
            )
            result = run_agent_loop(
                user_message=(
                    "Execute this approved plan only.\n\n"
                    f"Plan:\n{json.dumps(active_plan, indent=2)}\n\n"
                    "Rules:\n"
                    "- Follow the plan step by step.\n"
                    "- Do not add new goals.\n"
                    "- Use code_edit only for file changes.\n"
                    "- Do not use flux for HTML/CSS animation.\n"
                    "- Stop when the plan is complete.\n"
                ),
                route="code",
                model=model,
                tools_by_name={"code_edit": TOOLS_BY_NAME["code_edit"]},
                tool_map={"code_edit": TOOL_MAP["code_edit"]},
                call_ollama_once=call_ollama_once,
                execute_tool=execute_tool,
                emit_event=emit_event,
                truncate_text=truncate_text,
                strip_thinking_tags=strip_thinking_tags,
                now_iso=now_iso,
                task_graph_path=TASK_GRAPH_PATH,
                task_id=active_plan.get("plan_id"),
                max_steps=len(active_plan.get("steps", [])) + 2,
            )

            result_dict = result if isinstance(result, dict) else {}
            result_kind = classify_agent_output_kind(
                skill_name=tool_name,
                user_text=user_text,
                result=result_dict,
            )

            content = extract_last_patch_from_anything(result)
            content = normalize_patch_text(content)

            if result_kind == "report":
                _plan_id = active_plan.get("plan_id") or "report_" + str(uuid.uuid4())[:8]

                markdown = (
                    result_dict.get("markdown")
                    or result_dict.get("report")
                    or result_dict.get("answer")
                    or result_dict.get("text")
                    or result_dict.get("content")
                    or content
                )

                report_path = write_analysis_report(
                    skill_name=tool_name,
                    plan_id=_plan_id,
                    result={"markdown": markdown},
                )

                emit_event(
                    "artifact",
                    "Analysis report written",
                    {
                        "plan_id": _plan_id,
                        "skill": tool_name,
                        "path": str(report_path),
                    },
                )

                self._json_response(
                    {
                        "model": model,
                        "created_at": now_iso(),
                        "message": {
                            "role": "assistant",
                            "content": markdown,
                        },
                        "done": True,
                        "route": resolved_route,
                        "format": "report",
                        "report_path": str(report_path),
                    }
                )
                return

            if "--- FILE:" not in content or "@@" not in content:
                emit_event(
                    "warning",
                    "Coder returned non-patch output",
                    {
                        "plan_id": active_plan.get("plan_id"),
                        "step": step,
                        "preview": content[:1000],
                    },
                )

                content = (
                    "Coder returned analysis instead of a patch.\n\n"
                    "This output was rejected.\n\n"
                    f"Preview:\n{content[:1500]}"
                )

            patch_file = f"patches/step_{step.get('id')}.patch"
            (plan_dir(active_plan["plan_id"]) / patch_file).write_text(
                content,
                encoding="utf-8",
            )

            append_event(
                "coder.done",
                f"Coder finished step {step.get('id')}",
                plan_id=active_plan.get("plan_id"),
                task_id=str(step.get("id")),
                route=resolved_route,
                model=model,
                payload={
                    "patch_file": patch_file,
                    "chars": len(content),
                },
            )

            if "### PATCH" in content:
                patch_part = content.split("### PATCH", 1)[1].strip()
            else:
                patch_part = content

            validation = validate_coder_output(patch_part)

            emit_event(
                "code_phase",
                "Patch returned, validating",
                {
                    "phase": "validating_patch",
                    "plan_id": active_plan.get("plan_id"),
                    "preview": patch_part[:500],
                },
            )

            emit_event(
                "status",
                "Coder output validation completed",
                {
                    "route": resolved_route,
                    "model": model,
                    "tool": tool_name,
                    "validation": validation,
                },
            )

            append_event(
                "patch.validated",
                "Coder output validation completed",
                plan_id=active_plan.get("plan_id"),
                task_id=str(step.get("id")),
                route=resolved_route,
                model=model,
                payload={"validation": validation},
            )

            if not validation["ok"]:
                retry_instruction = (
                    active_plan.get("user_request", user_text)
                    + "\n\nYour previous answer was rejected by validation.\n"
                    + "Problems:\n"
                    + "\n".join(f"- {p}" for p in validation.get("problems", []))
                    + "\n\nReturn ONLY this format, no explanation, no markdown fences:\n"
                    + "--- FILE: path/to/file.py\n"
                    + "@@\n"
                    + "<minimal changed function/helper blocks only>\n"
                )

                retry_args = {
                    "task": retry_instruction,
                    "path": paths[0] if paths else str(PROJECT_ROOT),
                    "model": model,
                    "mode": "patch",
                }

                emit_event(
                    "code_phase",
                    "Patch failed validation, repairing",
                    {
                        "phase": "repairing_patch",
                        "plan_id": active_plan.get("plan_id"),
                        "problems": validation.get("problems", []),
                    },
                )

                retry_result = execute_tool(tool_name, retry_args)
                retry_content = extract_tool_content(retry_result)
                retry_content = normalize_patch_text(retry_content)
                retry_validation = validate_coder_output(retry_content)

                if retry_validation["ok"]:
                    content = retry_content
                    validation = retry_validation
                else:
                    content = wrap_invalid_coder_output(retry_content, retry_validation)
                    validation = retry_validation

            emit_event(
                "final",
                "Coder skill response ready",
                {
                    "route": resolved_route,
                    "model": model,
                    "tool": tool_name,
                    "validated": validation["ok"],
                },
            )

            if validation["ok"]:
                apply_result = apply_file_patch(content)

                emit_event(
                    "code_phase",
                    "Patch applied" if apply_result.get("ok") else "Patch apply failed",
                    {
                        "phase": "patch_applied" if apply_result.get("ok") else "patch_apply_failed",
                        "plan_id": active_plan.get("plan_id"),
                        "result": apply_result,
                    },
                )

                append_event(
                    "patch.applied" if apply_result.get("ok") else "patch.apply_failed",
                    "Patch applied" if apply_result.get("ok") else "Patch apply failed",
                    plan_id=active_plan.get("plan_id"),
                    task_id=str(step.get("id")),
                    route=resolved_route,
                    model=model,
                    payload={"result": apply_result},
                )

                if apply_result.get("ok"):
                    step["status"] = "done"
                    step["summary"] = summarize_step_result(content)
                    active_plan["current_step"] = current_step + 1
                    save_active_plan(active_plan)
                    save_json(active_plan["plan_id"], "status.json", active_plan)

                    append_event(
                        "step.done",
                        f"Step {step.get('id')} completed",
                        plan_id=active_plan.get("plan_id"),
                        task_id=str(step.get("id")),
                        route=resolved_route,
                        model=model,
                        payload={
                            "step": step,
                            "current_step": active_plan["current_step"],
                            "remaining": len(steps) - active_plan["current_step"],
                        },
                    )

                    emit_event(
                        "code_step_ready",
                        f"Step {step.get('id')} complete. Ready for next step.",
                        {
                            "plan_id": active_plan.get("plan_id"),
                            "step": step,
                            "current_step": active_plan["current_step"],
                            "remaining": len(steps) - active_plan["current_step"],
                            "next_step": steps[active_plan["current_step"]]
                            if active_plan["current_step"] < len(steps)
                            else None,
                        },
                    )
                else:
                    content = content + "\n\nAPPLY FAILED:\n" + json.dumps(apply_result, indent=2)

            self._json_response(
                {
                    "model": model,
                    "created_at": now_iso(),
                    "message": {"role": "assistant", "content": content},
                    "done": True,
                    "validation": validation,
                }
            )
            return
        # ------------------------------------------------------------------
        # Normal non-direct route
        # ------------------------------------------------------------------
        tool_names = [t["function"]["name"] for t in selected_tools]

        runtime_mode = write_runtime_mode(resolved_route, model, selected_tools)
        persona = runtime_mode.get("persona")

        try:
            sync_kokoro_for_route(resolved_route, model)
        except Exception as e:
            emit_event(
                "warning",
                "Orpheus sync failed",
                {"route": resolved_route, "model": model, "error": str(e)},
            )

        debug(f"Runtime mode: {runtime_mode}")
        debug(
            f"POST /api/chat requested_model={requested_model!r} requested_route={requested_route!r} source={source!r} "
            f"resolved_route={resolved_route!r} resolved_model={model!r} persona={persona!r} stream={stream} "
            f"tool_count={len(selected_tools)} user={user_text[:140]!r}"
        )
        debug(f"Selected {len(selected_tools)} tools: {tool_names}")

        emit_event(
            "status",
            "Incoming chat request",
            {
                "requested_model": requested_model,
                "requested_route": requested_route,
                "source": source,
                "resolved_route": resolved_route,
                "resolved_model": model,
                "stream": stream,
                "tool_count": len(selected_tools),
                "tools": tool_names,
                "user_preview": user_text[:140],
                "runtime_mode": runtime_mode,
            },
        )

        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            stream_direct_chat(
                self,
                model,
                messages,
                selected_tools=selected_tools,
                route=resolved_route,
                persona=persona,
            )
            return

        if is_simple_direct_chat(user_text, selected_tools, resolved_route):
            try:
                data = call_ollama_once(
                    model=model,
                    messages=messages,
                    route=resolved_route,
                    persona=persona,
                    tools=None,
                    stream=False,
                )
                self._json_response(data)
                return
            except Exception as e:
                self._json_response(
                    {
                        "model": model,
                        "created_at": now_iso(),
                        "message": {"role": "assistant", "content": f"Error calling Ollama: {e}"},
                        "done": True,
                    }
                )
                return
        if selected_tools:
            ack = random.choice(ACKS)
            write_bridge_status("thinking", ack)
            append_log(f"[{datetime.now().strftime('%H:%M:%S')}] ACK: {ack}")
            speak_ack(ack)

            result = react_chat(
                model,
                messages,
                selected_tools,
                route=resolved_route,
                persona=persona,
            )

            self._json_response(result)
            return
        

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/history/plans":
            plans_root = VAULT_DIR / ".jarvis" / "history" / "plans"
            plans = []
            if plans_root.exists():
                for p in sorted(plans_root.iterdir(), reverse=True):
                    if p.is_dir():
                        plan_file = p / "plan.json"
                        status_file = p / "status.json"
                        item = {"plan_id": p.name}
                        try:
                            if status_file.exists():
                                item.update(json.loads(status_file.read_text(encoding="utf-8")))
                            elif plan_file.exists():
                                item.update(json.loads(plan_file.read_text(encoding="utf-8")))
                        except Exception as e:
                            item["error"] = str(e)
                        plans.append(item)
            self._json_response({"plans": plans[:50]})
            return

        if path.startswith("/api/history/plan/"):
            plan_id = path.rsplit("/", 1)[-1]
            d = VAULT_DIR / ".jarvis" / "history" / "plans" / plan_id

            if not d.exists():
                self._json_response({"error": "Plan not found", "plan_id": plan_id}, code=404)
                return

            def read_json(name: str):
                f = d / name
                if not f.exists():
                    return None
                return json.loads(f.read_text(encoding="utf-8"))

            events = []
            events_file = d / "events.jsonl"
            if events_file.exists():
                for line in events_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.strip():
                        try:
                            events.append(json.loads(line))
                        except Exception:
                            pass

            self._json_response(
                {
                    "plan_id": plan_id,
                    "plan": read_json("plan.json"),
                    "status": read_json("status.json"),
                    "events": events,
                }
            )
            return
        if path == "/api/coding-log":
            self._json_response({"events": recent_coding_events(120)})
            return

        if path == "/api/health":
            try:
                tags = request_ollama_tags()
                ollama_ready = True
                ollama_models = len(tags.get("models", []))
            except Exception:
                ollama_ready = False
                ollama_models = 0
            profile = load_active_profile()
            self._json_response(
                {
                    "status": "ok",
                    "service": "jarvis-react-v3",
                    "time": now_iso(),
                    "ollama_host": OLLAMA_HOST,
                    "ollama_ready": ollama_ready,
                    "ollama_model_count": ollama_models,
                    "loaded_skills": len(get_loaded_skills()),
                    "tool_count": len(TOOL_MAP),
                    "active_profile": {"id": profile.get("id"), "label": profile.get("label")},
                    "models": load_model_config().get("models", {}),
                    "planner_model": get_planner_model(),
                }
            )
            return

        if path == "/api/skills":
            self._json_response(
                {
                    "skills": get_loaded_skills(),
                    "tools": list(TOOL_MAP.keys()),
                    "tool_keywords": TOOL_KEYWORDS,
                    "tool_skill_meta": TOOL_SKILL_META,
                    "intent_tool_candidates": INTENT_TOOL_CANDIDATES,
                    "tool_route_hints": TOOL_ROUTE_HINTS,
                    "no_tools_models": sorted(NO_TOOLS_MODELS),
                }
            )
            return

        if path == "/api/models":
            cfg = load_model_config()
            self._json_response({"models": cfg.get("models", {}), "planner_model": get_planner_model()})
            return

        if path == "/api/events":
            self._json_response({"events": recent_events(100)})
            return

        if path == "/api/timers":
            try:
                from skills.timer import get_active_timers  # type: ignore
                self._json_response({"timers": get_active_timers()})
            except ImportError:
                self._json_response({"timers": []})
            return

        if path == "/api/radio":
            try:
                from skills.radio import get_now_playing, get_radio_state, get_stations  # type: ignore
                self._json_response({**get_radio_state(), "stations": get_stations(), "now_playing": get_now_playing()})
            except ImportError:
                self._json_response({"playing": False, "stations": {}})
            return

        if path == "/api/reload":
            try:
                result = reload_all_skills()
                self._json_response(result)
            except Exception as e:
                self._json_response({"error": str(e)}, code=500)
            return

        if path == "/api/network":
            try:
                from skills.network import get_topology  # type: ignore
                self._json_response(get_topology())
            except ImportError:
                self._json_response({"devices": [], "gateway": "192.168.0.1"})
            return

        if path == "/api/self":
            try:
                runtime_persona = None
                if RUNTIME_MODE_PATH.exists():
                    runtime_persona = json.loads(RUNTIME_MODE_PATH.read_text(encoding="utf-8")).get("persona")
            except Exception:
                runtime_persona = None
            self._json_response(build_self_context(persona=runtime_persona))
            return

        if path == "/api/runtime-mode":
            try:
                if RUNTIME_MODE_PATH.exists():
                    self._json_response(json.loads(RUNTIME_MODE_PATH.read_text(encoding="utf-8")))
                else:
                    self._json_response({"mode": "conversation", "persona": "jarvis"})
            except Exception as e:
                self._json_response({"error": str(e)}, code=500)
            return

        self.send_error(404)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json_response(self, payload: Dict[str, Any], code: int = 200) -> None:
        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except BrokenPipeError:
            emit_event(
                "warning",
                "Client disconnected before response could be sent",
                {"code": code},
            )
        except Exception as e:
            emit_event(
                "warning",
                "Failed sending JSON response",
                {"error": str(e), "code": code},
            )

    def _write_sse_json(self, data: Dict[str, Any]) -> None:
        line = json.dumps(data, ensure_ascii=False) + "\n"
        self.wfile.write(line.encode("utf-8"))
        self.wfile.flush()

    def log_message(self, fmt: str, *args: Any) -> None:
        return

# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    sys.stdout = os.fdopen(sys.stdout.fileno(), "w", buffering=1)
    sys.stderr = os.fdopen(sys.stderr.fileno(), "w", buffering=1)

    ensure_dirs()
    emit_event("status", "React server starting", {"port": PORT, "ollama_host": OLLAMA_HOST})
    wait_for_ollama()
    if KOKORO_ENABLED:
        try:
            sync_kokoro_for_route("fast", resolve_model(requested_model=None, route="fast"))
        except Exception as e:
            emit_event("warning", "Initial Kokoro warm start failed", {"error": str(e)})

    server = ThreadingHTTPServer(("127.0.0.1", PORT), ReactHandler)
    print(f"[REACT] ReAct server v3 on http://127.0.0.1:{PORT}")
    print(f"[REACT] Ollama backend: {OLLAMA_HOST}")
    print(f"[REACT] Vault: {VAULT_DIR}")
    print(f"[REACT] Bridge: {BRIDGE_DIR}")
    print(f"[REACT] Active profile path: {ACTIVE_PROFILE_PATH}")
    print(f"[REACT] Profiles dir: {PROFILES_DIR}")
    print(f"[REACT] Runtime mode path: {RUNTIME_MODE_PATH}")
    print(f"[REACT] Tools ({len(TOOL_MAP)}): {', '.join(TOOL_MAP.keys())}")
    print("[REACT] READY")
    emit_event("status", "React server ready", {"port": PORT, "tool_count": len(TOOL_MAP)})

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[REACT] Server stopped")
        emit_event("status", "React server stopped")
        server.server_close()
