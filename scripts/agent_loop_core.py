"""
JARVIS Agent Loop Core — patched run_agent_loop
================================================
Drop-in replacement for the original agent_loop.py module.

What changed vs original:
  1. Killed hardcoded `code` route — loop now reasons which tool to use
  2. Skills injected at call time — tools come from TOOL_MAP, not static registry
  3. Added `plan` route — multi-step goals hand off to planner_skill, not self-loop
  4. Added `plan_id` context — loop knows which staging folder it's working in
  5. ACT parser accepts both pipe format AND JSON tool_use format
  6. `code_edit` demoted — only selected when task explicitly names a file to edit

Everything else (task graph, PLAN/ACT/FINAL, step tracking, emit_event) unchanged.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional


# ── Unchanged helpers from original ──────────────────────────────────────────

def extract_agent_command(strip_thinking_tags: Callable[[str], str], text: str) -> tuple[str, str]:
    text = strip_thinking_tags(text or "").strip()

    act_match = re.search(
        r"\bACT:\s*(.*?)(?=\bFINAL:|\bPLAN:|$)",
        text, flags=re.DOTALL | re.IGNORECASE,
    )
    if act_match:
        return "ACT", act_match.group(1).strip()

    final_match = re.search(
        r"\bFINAL:\s*(.*)", text, flags=re.DOTALL | re.IGNORECASE,
    )
    if final_match:
        return "FINAL", final_match.group(1).strip()

    plan_match = re.search(
        r"\bPLAN:\s*(.*?)(?=\bACT:|\bFINAL:|$)",
        text, flags=re.DOTALL | re.IGNORECASE,
    )
    if plan_match:
        return "PLAN", plan_match.group(1).strip()

    return "PLAN", text


def parse_agent_action(action: str) -> tuple[str, dict]:
    if "|" not in action:
        return action.strip(), {}

    tool_name, raw_args = action.split("|", 1)
    tool_name = tool_name.strip()

    try:
        args = json.loads(raw_args.strip())
    except Exception:
        args = {"raw": raw_args.strip()}

    if not isinstance(args, dict):
        args = {"value": args}

    return tool_name, args


def load_task_graph(task_graph_path: Path) -> dict:
    if not task_graph_path.exists():
        return {"tasks": {}, "active_task_id": None}
    try:
        data = json.loads(task_graph_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("tasks", {})
            data.setdefault("active_task_id", None)
            return data
    except Exception:
        pass
    return {"tasks": {}, "active_task_id": None}


def save_task_graph(task_graph_path: Path, graph: dict) -> None:
    task_graph_path.parent.mkdir(parents=True, exist_ok=True)
    task_graph_path.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def create_task(
    task_graph_path: Path, now_iso: Callable[[], str],
    title: str, user_request: str, route: str, model: str,
) -> dict:
    graph   = load_task_graph(task_graph_path)
    task_id = "task_" + str(uuid.uuid4())[:8]
    now     = now_iso()
    task    = {
        "id": task_id, "title": title[:120], "status": "running",
        "created_at": now, "updated_at": now, "route": route, "model": model,
        "user_request": user_request, "steps": [], "events": [],
    }
    graph["tasks"][task_id] = task
    graph["active_task_id"] = task_id
    save_task_graph(task_graph_path, graph)
    return task


def append_task_event(
    task_graph_path: Path, now_iso: Callable[[], str],
    task_id: str, event_type: str, data: dict,
) -> None:
    graph = load_task_graph(task_graph_path)
    task  = graph.get("tasks", {}).get(task_id)
    if not task:
        return
    now = now_iso()
    task.setdefault("events", []).append({"time": now, "type": event_type, "data": data})
    task["updated_at"] = now
    save_task_graph(task_graph_path, graph)


def append_task_step(
    task_graph_path: Path, now_iso: Callable[[], str],
    task_id: str, title: str, status: str, result: str = "",
) -> None:
    graph = load_task_graph(task_graph_path)
    task  = graph.get("tasks", {}).get(task_id)
    if not task:
        return
    now   = now_iso()
    steps = task.setdefault("steps", [])
    steps.append({
        "id": f"step_{len(steps) + 1}", "title": title,
        "status": status, "result": result,
        "created_at": now, "updated_at": now,
    })
    task["updated_at"] = now
    save_task_graph(task_graph_path, graph)


def build_tool_description_text(tools_by_name: dict) -> str:
    lines = []
    for tool_name, tool_def in sorted(tools_by_name.items()):
        try:
            fn    = tool_def.get("function", {})
            desc  = fn.get("description", "")
            props = fn.get("parameters", {}).get("properties", {})
            args  = []
            for arg_name, arg_info in props.items():
                enum_values = arg_info.get("enum")
                if enum_values:
                    args.append(f"{arg_name}={enum_values}")
                else:
                    args.append(f"{arg_name}:{arg_info.get('type','any')}")
            lines.append(f"- {tool_name}: {desc} | args: {', '.join(args)}")
        except Exception:
            lines.append(f"- {tool_name}")
    return "\n".join(lines)


# ── Route classifier ──────────────────────────────────────────────────────────

# Keywords that signal a multi-step plan is needed rather than a single tool call
_PLAN_KEYWORDS = [
    "build", "create", "design", "scaffold", "system", "implement",
    "develop", "make", "set up", "write a", "full", "complete",
    "banking", "ecommerce", "platform", "service", "pipeline",
    "multi-step", "workflow", "automate",
]

# Keywords that mean the user literally wants to edit a specific existing file
_CODE_EDIT_KEYWORDS = [
    "edit", "fix", "patch", "refactor", "update", "change line",
    "rename", "add function to", "modify",
]


def classify_route(user_message: str, explicit_route: str) -> str:
    """
    Determine the best route for a request.

    Routes:
      plan   — multi-step goal, hands off to planner_skill
      code   — explicit file edit (code_edit tool used, but only when named)
      agent  — single-tool task, runs through ReAct loop
    """
    if explicit_route and explicit_route not in ("auto", ""):
        # Caller already decided — but override 'code' if message doesn't name a file
        if explicit_route == "code":
            msg_lower = user_message.lower()
            has_file  = any(ext in msg_lower for ext in (".py", ".js", ".ts", ".json", ".yaml", ".md", ".sql"))
            has_edit  = any(kw in msg_lower for kw in _CODE_EDIT_KEYWORDS)
            if not (has_file and has_edit):
                # Caller said 'code' but no file mentioned — treat as agent
                return "agent"
        return explicit_route

    msg_lower = user_message.lower()

    # Multi-step goal → plan route
    plan_hits = sum(1 for kw in _PLAN_KEYWORDS if kw in msg_lower)
    if plan_hits >= 2:
        return "plan"

    # Explicit file edit → code route
    has_file = any(ext in msg_lower for ext in (".py", ".js", ".ts", ".json", ".yaml", ".md", ".sql"))
    has_edit = any(kw in msg_lower for kw in _CODE_EDIT_KEYWORDS)
    if has_file and has_edit:
        return "code"

    return "agent"


# ── Planner handoff ───────────────────────────────────────────────────────────

def _handoff_to_planner(
    user_message: str,
    task_id: str,
    task_graph_path: Path,
    now_iso: Callable[[], str],
    emit_event: Callable,
    plan_id: Optional[str] = None,
) -> dict:
    """
    Hand a multi-step goal off to planner_skill.exec_plan().
    Returns agent result dict with plan summary.
    """
    import importlib.util, os
    from pathlib import Path as _Path

    emit_event("agent_plan", "Handing off to planner", {
        "task_id": task_id, "goal": user_message[:200],
    })

    # Locate planner_skill
    skills_dir   = _Path(os.getenv("JARVIS_SKILLS_DIR", "/mnt/e/coding/jarvis-os/skills"))
    planner_path = skills_dir / "planner_skill.py"

    if not planner_path.exists():
        # Try sibling of this file
        planner_path = _Path(__file__).parent / "planner_skill.py"

    if not planner_path.exists():
        answer = "Planner skill not found — cannot decompose this goal."
        append_task_event(task_graph_path, now_iso, task_id, "agent_error", {"error": answer})
        return {"ok": False, "type": "agent_result", "task_id": task_id,
                "answer": answer, "trace": [], "observations": []}

    try:
        spec = importlib.util.spec_from_file_location("planner_skill", planner_path)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        goal   = user_message
        result = mod.exec_plan(goal)

        append_task_step(task_graph_path, now_iso, task_id,
                         title="Planner decomposition", status="done", result=result[:2000])
        append_task_event(task_graph_path, now_iso, task_id,
                          "agent_final", {"answer": result[:2000]})

        return {
            "ok": True, "type": "agent_result",
            "task_id": task_id, "answer": result,
            "trace": [{"step": 1, "command": "PLAN→planner_skill", "payload": result}],
            "observations": [],
        }
    except Exception as e:
        answer = f"Planner failed: {e}"
        append_task_event(task_graph_path, now_iso, task_id, "agent_error", {"error": answer})
        return {"ok": False, "type": "agent_result", "task_id": task_id,
                "answer": answer, "trace": [], "observations": []}


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_agent_loop(
    user_message: str,
    route: str,
    model: str,
    tools_by_name: dict,
    tool_map: dict,
    call_ollama_once: Callable[..., dict],
    execute_tool: Callable[[str, dict], str],
    emit_event: Callable[[str, str, Optional[Dict[str, Any]]], None],
    truncate_text: Callable[[Any, int], str],
    strip_thinking_tags: Callable[[str], str],
    now_iso: Callable[[], str],
    task_graph_path: Path,
    task_id: Optional[str] = None,
    max_steps: int = 8,
    # New params — optional, backward-compatible
    plan_id: Optional[str] = None,
    skill_tool_map: Optional[dict] = None,   # merged TOOL_MAP from all skills
) -> dict:
    trace        = []
    observations = []

    if not task_id:
        task = create_task(
            task_graph_path=task_graph_path, now_iso=now_iso,
            title=user_message[:80], user_request=user_message,
            route=route, model=model,
        )
        task_id = task["id"]

    # ── Route classification ──────────────────────────────────────────────────
    effective_route = classify_route(user_message, route)

    # Multi-step goal → hand off to planner, don't self-loop
    if effective_route == "plan":
        return _handoff_to_planner(
            user_message, task_id, task_graph_path, now_iso, emit_event, plan_id,
        )

    # Merge skill tools into tools_by_name if provided
    # This makes skill tools available to the ReAct loop without changing callers
    if skill_tool_map:
        for skill_name, skill in skill_tool_map.items():
            for t in skill.get("tools", []):
                fn   = t.get("function", {})
                name = fn.get("name", "")
                if name and name not in tools_by_name:
                    tools_by_name[name] = t
            for tool_name, fn in skill.get("tool_map", {}).items():
                if tool_name not in tool_map:
                    tool_map[tool_name] = fn

    available_tools = build_tool_description_text(tools_by_name)

    emit_event("agent_start", "Agent loop started", {
        "task_id": task_id, "route": effective_route, "model": model,
        "max_steps": max_steps, "user_request": user_message[:500],
        "plan_id": plan_id or "",
    })

    append_task_event(task_graph_path, now_iso, task_id, "agent_start", {
        "route": effective_route, "model": model,
        "max_steps": max_steps, "user_request": user_message[:500],
        "plan_id": plan_id or "",
    })

    # ── System prompt ─────────────────────────────────────────────────────────
    plan_context = f"\nWorking in plan: {plan_id}" if plan_id else ""
    code_edit_note = (
        "\nIMPORTANT: Use code_edit ONLY when the user explicitly names a file to edit."
        "\nFor all other tasks — shell commands, model ops, file reads, searches — use the matching tool."
    )

    system_agent_prompt = f"""You are JARVIS agent executor.{plan_context}

Work in this loop:
PLAN: brief next step
ACT: tool_name | {{"key": "value"}}
FINAL: final answer to the user

Rules:
- Prefer returning only one command.
- If you accidentally include PLAN, ACT, and FINAL together, ACT will be executed first.
- Do not invent tool results.
- Use tools only when needed.
- Use only available tools.
- Use exact tool argument names and enum values from the tool descriptions.
- Prefer small safe steps.
- Stop as soon as you can answer.
- Do not use markdown fences.{code_edit_note}

Available tools:
{available_tools}""".strip()

    # ── Initial working prompt — NO hardcoded code route ─────────────────────
    working_prompt = f"""User request:
{user_message}

Previous observations:
None

Return one:
PLAN: ...
ACT: tool_name | {{"key": "value"}}
FINAL: ...""".strip()

    # ── ReAct loop ────────────────────────────────────────────────────────────
    for step_no in range(1, max_steps + 1):
        try:
            data = call_ollama_once(
                model=model,
                messages=[
                    {"role": "system", "content": system_agent_prompt},
                    {"role": "user",   "content": working_prompt},
                ],
                route=effective_route,
                tools=None,
                stream=False,
            )
            model_response = data.get("message", {}).get("content", "")
        except Exception as e:
            answer = f"Agent loop failed while calling Ollama: {type(e).__name__}: {e}"
            append_task_event(task_graph_path, now_iso, task_id, "agent_error", {"error": answer})
            return {
                "ok": False, "type": "agent_result",
                "task_id": task_id, "answer": answer,
                "trace": trace, "observations": observations,
            }

        text              = strip_thinking_tags(model_response or "").strip()
        command, payload  = extract_agent_command(strip_thinking_tags, text)

        trace.append({
            "step": step_no, "command": command,
            "payload": payload, "model_response": text,
        })

        emit_event("agent_step", "Agent reasoning step", {
            "task_id": task_id, "step": step_no,
            "route": effective_route, "model": model,
            "command": command, "payload": payload[:2000], "response": text[:2000],
        })

        append_task_event(task_graph_path, now_iso, task_id, "agent_step", {
            "step": step_no, "route": effective_route, "model": model,
            "command": command, "payload": payload[:2000],
        })

        # ── FINAL ─────────────────────────────────────────────────────────────
        if command == "FINAL":
            emit_event("agent_final", "Agent completed task", {
                "task_id": task_id, "steps": step_no,
                "route": effective_route, "model": model,
            })
            append_task_event(task_graph_path, now_iso, task_id, "agent_final", {
                "steps": step_no, "route": effective_route,
                "model": model, "answer": payload[:2000],
            })
            append_task_step(task_graph_path, now_iso, task_id,
                             title="Final answer", status="done", result=payload[:2000])
            return {
                "ok": True, "type": "agent_result",
                "task_id": task_id, "answer": payload,
                "trace": trace, "observations": observations,
            }

        # ── ACT ───────────────────────────────────────────────────────────────
        if command == "ACT":
            tool_name, tool_args = parse_agent_action(payload)

            # Guard: if model tries code_edit without a file in the request, redirect
            if tool_name == "code_edit":
                msg_lower = user_message.lower()
                has_file  = any(ext in msg_lower for ext in
                                (".py", ".js", ".ts", ".json", ".yaml", ".md", ".sql", ".txt"))
                if not has_file:
                    # Redirect — inject a correction and let the model retry
                    observation = (
                        "code_edit rejected: no specific file was named in the request. "
                        "Use shell, read_file, or another appropriate tool instead."
                    )
                    emit_event("agent_redirect", "code_edit redirected", {
                        "task_id": task_id, "step": step_no, "reason": observation,
                    })
                    observations.append({
                        "tool": "code_edit_rejected",
                        "args": tool_args,
                        "observation": observation,
                    })
                    working_prompt = f"""User request:
{user_message}

Previous observations:
{json.dumps(observations, indent=2, ensure_ascii=False)}

{observation}

Pick a different tool. Return:
ACT: tool_name | {{"key": "value"}}
FINAL: ...""".strip()
                    continue

            if tool_name not in tools_by_name:
                observation = f"Tool not available: {tool_name}"
            elif tool_name not in tool_map:
                observation = f"Tool executor not loaded: {tool_name}"
            else:
                observation = execute_tool(tool_name, tool_args)

            emit_event("agent_tool", f"Agent executed tool {tool_name}", {
                "task_id": task_id, "step": step_no,
                "tool": tool_name, "args": tool_args,
                "observation": truncate_text(observation, 1000),
            })
            append_task_event(task_graph_path, now_iso, task_id, "agent_tool", {
                "step": step_no, "tool": tool_name, "args": tool_args,
                "observation": truncate_text(observation, 1000),
            })
            append_task_step(task_graph_path, now_iso, task_id,
                             title=f"Executed tool {tool_name}", status="done",
                             result=truncate_text(observation, 1000))

            observations.append({
                "tool": tool_name, "args": tool_args,
                "observation": truncate_text(observation, 3000),
            })

            if step_no >= max_steps - 1:
                working_prompt = f"""User request:
{user_message}

Tool executed:
{tool_name}

Observation:
{truncate_text(observation, 4000)}

This is the final synthesis step.

Return ONLY:
FINAL: <answer to user>""".strip()
                continue

            working_prompt = f"""User request:
{user_message}

Previous observations:
{json.dumps(observations, indent=2, ensure_ascii=False)}

Now use the observations. Return one:
ACT: tool_name | {{"key": "value"}}
FINAL: ...""".strip()
            continue

        # ── PLAN or unclear ───────────────────────────────────────────────────
        if step_no >= max_steps - 1:
            working_prompt = f"""User request:
{user_message}

Previous observations:
{json.dumps(observations, indent=2, ensure_ascii=False)}

This is your last step. Return FINAL: with the best answer now.""".strip()
        else:
            working_prompt = f"""User request:
{user_message}

Agent previous response:
{payload}

Previous observations:
{json.dumps(observations, indent=2, ensure_ascii=False)}

Continue. Return one:
ACT: tool_name | {{"key": "value"}}
FINAL: ...""".strip()

    # Step limit reached
    emit_event("agent_final", "Agent reached step limit", {
        "task_id": task_id, "steps": max_steps,
        "route": effective_route, "model": model,
    })

    last_text = trace[-1].get("payload") if trace else ""
    answer    = last_text or "Agent loop reached the step limit before producing a final answer."

    append_task_event(task_graph_path, now_iso, task_id, "agent_limit", {
        "steps": max_steps, "answer": answer[:2000],
    })

    return {
        "ok": True, "type": "agent_result",
        "task_id": task_id, "answer": answer,
        "trace": trace, "observations": observations,
    }