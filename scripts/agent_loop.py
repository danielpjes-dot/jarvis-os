from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional


def extract_agent_command(strip_thinking_tags: Callable[[str], str], text: str) -> tuple[str, str]:
    text = strip_thinking_tags(text or "").strip()

    act_match = re.search(
        r"\bACT:\s*(.*?)(?=\bFINAL:|\bPLAN:|$)",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if act_match:
        return "ACT", act_match.group(1).strip()

    final_match = re.search(
        r"\bFINAL:\s*(.*)",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if final_match:
        return "FINAL", final_match.group(1).strip()

    plan_match = re.search(
        r"\bPLAN:\s*(.*?)(?=\bACT:|\bFINAL:|$)",
        text,
        flags=re.DOTALL | re.IGNORECASE,
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
        json.dumps(graph, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_task(
    task_graph_path: Path,
    now_iso: Callable[[], str],
    title: str,
    user_request: str,
    route: str,
    model: str,
) -> dict:
    graph = load_task_graph(task_graph_path)
    task_id = "task_" + str(uuid.uuid4())[:8]
    now = now_iso()

    task = {
        "id": task_id,
        "title": title[:120],
        "status": "running",
        "created_at": now,
        "updated_at": now,
        "route": route,
        "model": model,
        "user_request": user_request,
        "steps": [],
        "events": [],
    }

    graph["tasks"][task_id] = task
    graph["active_task_id"] = task_id
    save_task_graph(task_graph_path, graph)
    return task


def append_task_event(
    task_graph_path: Path,
    now_iso: Callable[[], str],
    task_id: str,
    event_type: str,
    data: dict,
) -> None:
    graph = load_task_graph(task_graph_path)
    task = graph.get("tasks", {}).get(task_id)
    if not task:
        return

    now = now_iso()
    task.setdefault("events", []).append(
        {
            "time": now,
            "type": event_type,
            "data": data,
        }
    )
    task["updated_at"] = now
    save_task_graph(task_graph_path, graph)


def append_task_step(
    task_graph_path: Path,
    now_iso: Callable[[], str],
    task_id: str,
    title: str,
    status: str,
    result: str = "",
) -> None:
    graph = load_task_graph(task_graph_path)
    task = graph.get("tasks", {}).get(task_id)
    if not task:
        return

    now = now_iso()
    steps = task.setdefault("steps", [])

    steps.append(
        {
            "id": f"step_{len(steps) + 1}",
            "title": title,
            "status": status,
            "result": result,
            "created_at": now,
            "updated_at": now,
        }
    )

    task["updated_at"] = now
    save_task_graph(task_graph_path, graph)


def build_tool_description_text(tools_by_name: dict) -> str:
    tool_descriptions = []

    for tool_name, tool_def in sorted(tools_by_name.items()):
        try:
            fn = tool_def.get("function", {})
            desc = fn.get("description", "")
            parameters = fn.get("parameters", {})
            props = parameters.get("properties", {})

            args_preview = []

            for arg_name, arg_info in props.items():
                arg_type = arg_info.get("type", "any")
                enum_values = arg_info.get("enum")

                if enum_values:
                    args_preview.append(f"{arg_name}={enum_values}")
                else:
                    args_preview.append(f"{arg_name}:{arg_type}")

            args_text = ", ".join(args_preview)
            tool_descriptions.append(f"- {tool_name}: {desc} | args: {args_text}")
        except Exception:
            tool_descriptions.append(f"- {tool_name}")

    return "\n".join(tool_descriptions)


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
) -> dict:
    trace = []
    observations = []

    if not task_id:
        task = create_task(
            task_graph_path=task_graph_path,
            now_iso=now_iso,
            title=user_message[:80],
            user_request=user_message,
            route=route,
            model=model,
        )
        task_id = task["id"]

    available_tools = build_tool_description_text(tools_by_name)

    emit_event(
        "agent_start",
        "Agent loop started",
        {
            "task_id": task_id,
            "route": route,
            "model": model,
            "max_steps": max_steps,
            "user_request": user_message[:500],
        },
    )

    append_task_event(
        task_graph_path,
        now_iso,
        task_id,
        "agent_start",
        {
            "route": route,
            "model": model,
            "max_steps": max_steps,
            "user_request": user_message[:500],
        },
    )

    system_agent_prompt = f"""
You are JARVIS agent executor.

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
- Do not use markdown fences.

Available tools:
{available_tools}
""".strip()
    if route == "code":
        working_prompt = f"""
    User request:
    {user_message}

    Previous observations:
    None

    You are in CODE route.

    Do not explain.
    Do not say what you will do.
    Do not inspect directories unless absolutely required.

    Use the code_edit tool directly.

    Return ONLY one command in this exact format:

    ACT: code_edit | {{"task":"<clear coding task>","path":"<target path or project root>","mode":"patch","model":"{model}"}}
    """.strip()
    else:
        working_prompt = f"""
    User request:
    {user_message}

    Previous observations:
    None

    Return one:
    PLAN: ...
    ACT: tool_name | {{"key": "value"}}
    FINAL: ...
    """.strip()


    for step_no in range(1, max_steps + 1):
        try:
            data = call_ollama_once(
                model=model,
                messages=[
                    {"role": "system", "content": system_agent_prompt},
                    {"role": "user", "content": working_prompt},
                ],
                route=route,
                tools=None,
                stream=False,
            )
            model_response = data.get("message", {}).get("content", "")
        except Exception as e:
            answer = f"Agent loop failed while calling Ollama: {type(e).__name__}: {e}"
            append_task_event(
                task_graph_path,
                now_iso,
                task_id,
                "agent_error",
                {"error": answer},
            )
            return {
                "ok": False,
                "type": "agent_result",
                "task_id": task_id,
                "answer": answer,
                "trace": trace,
                "observations": observations,
            }

        text = strip_thinking_tags(model_response or "").strip()
        command, payload = extract_agent_command(strip_thinking_tags, text)

        trace.append(
            {
                "step": step_no,
                "command": command,
                "payload": payload,
                "model_response": text,
            }
        )

        emit_event(
            "agent_step",
            "Agent reasoning step",
            {
                "task_id": task_id,
                "step": step_no,
                "route": route,
                "model": model,
                "command": command,
                "payload": payload[:2000],
                "response": text[:2000],
            },
        )

        append_task_event(
            task_graph_path,
            now_iso,
            task_id,
            "agent_step",
            {
                "step": step_no,
                "route": route,
                "model": model,
                "command": command,
                "payload": payload[:2000],
            },
        )

        if command == "FINAL":
            emit_event(
                "agent_final",
                "Agent completed task",
                {
                    "task_id": task_id,
                    "steps": step_no,
                    "route": route,
                    "model": model,
                },
            )

            append_task_event(
                task_graph_path,
                now_iso,
                task_id,
                "agent_final",
                {
                    "steps": step_no,
                    "route": route,
                    "model": model,
                    "answer": payload[:2000],
                },
            )

            append_task_step(
                task_graph_path,
                now_iso,
                task_id,
                title="Final answer",
                status="done",
                result=payload[:2000],
            )

            return {
                "ok": True,
                "type": "agent_result",
                "task_id": task_id,
                "answer": payload,
                "trace": trace,
                "observations": observations,
            }

        if command == "ACT":
            tool_name, tool_args = parse_agent_action(payload)

            if tool_name not in tools_by_name:
                observation = f"Tool not available: {tool_name}"
            elif tool_name not in tool_map:
                observation = f"Tool executor not loaded: {tool_name}"
            else:
                observation = execute_tool(tool_name, tool_args)

            emit_event(
                "agent_tool",
                f"Agent executed tool {tool_name}",
                {
                    "task_id": task_id,
                    "step": step_no,
                    "tool": tool_name,
                    "args": tool_args,
                    "observation": truncate_text(observation, 1000),
                },
            )

            append_task_event(
                task_graph_path,
                now_iso,
                task_id,
                "agent_tool",
                {
                    "step": step_no,
                    "tool": tool_name,
                    "args": tool_args,
                    "observation": truncate_text(observation, 1000),
                },
            )

            append_task_step(
                task_graph_path,
                now_iso,
                task_id,
                title=f"Executed tool {tool_name}",
                status="done",
                result=truncate_text(observation, 1000),
            )

            observations.append(
                {
                    "tool": tool_name,
                    "args": tool_args,
                    "observation": truncate_text(observation, 3000),
                }
            )

            if step_no >= max_steps - 1:
                working_prompt = f"""
User request:
{user_message}

Tool executed:
{tool_name}

Observation:
{truncate_text(observation, 4000)}

This is the final synthesis step.

Return ONLY:
FINAL: <answer to user>
""".strip()
                continue

            working_prompt = f"""
User request:
{user_message}

Previous observations:
{json.dumps(observations, indent=2, ensure_ascii=False)}

Now use the observations. Return one:
ACT: tool_name | {{"key": "value"}}
FINAL: ...
""".strip()
            continue

        # PLAN or unclear response.
        if step_no >= max_steps - 1:
            working_prompt = f"""
User request:
{user_message}

Previous observations:
{json.dumps(observations, indent=2, ensure_ascii=False)}

This is your last step. Return FINAL: with the best answer now.
""".strip()
        else:
            working_prompt = f"""
User request:
{user_message}

Agent previous response:
{payload}

Previous observations:
{json.dumps(observations, indent=2, ensure_ascii=False)}

Continue. Return one:
ACT: tool_name | {{"key": "value"}}
FINAL: ...
""".strip()

    emit_event(
        "agent_final",
        "Agent reached step limit",
        {
            "task_id": task_id,
            "steps": max_steps,
            "route": route,
            "model": model,
        },
    )

    last_text = trace[-1].get("payload") if trace else ""
    answer = last_text or "Agent loop reached the step limit before producing a final answer."

    append_task_event(
        task_graph_path,
        now_iso,
        task_id,
        "agent_limit",
        {
            "steps": max_steps,
            "answer": answer[:2000],
        },
    )

    return {
        "ok": True,
        "type": "agent_result",
        "task_id": task_id,
        "answer": answer,
        "trace": trace,
        "observations": observations,
    }