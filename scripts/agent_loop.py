"""
JARVIS Agent Loop — Intent Router
==================================
Thin intelligent router. Never executes code or touches files directly.
Responsibilities:
  1. Auto-discover skills from SKILLS_DIR
  2. Classify intent → match skill via keywords + LLM scoring
  3. Clarify once if ambiguous, then dispatch
  4. Reject gracefully if out of scope

Skills own all execution. Loop owns routing logic only.

Modes:
  ROUTE   — clear intent, dispatch immediately
  CLARIFY — one question to the user, then re-route
  REJECT  — out of scope or unsafe

Usage:
  python agent_loop.py                        # interactive CLI
  python agent_loop.py "check for better models"  # single task
  uvicorn agent_loop:app --port 8100          # HTTP mode
"""

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────

SKILLS_DIR   = Path(os.getenv("JARVIS_SKILLS_DIR",  "/mnt/e/coding/jarvis-os/skills"))
OLLAMA_HOST  = os.getenv("OLLAMA_HOST",              "http://localhost:11434")
ROUTER_MODEL = os.getenv("JARVIS_ROUTER_MODEL",      "qwen3:14b")
MAX_CLARIFY  = 1      # only one clarifying question per task, ever
KEYWORD_THRESHOLD = 2  # min keyword hits to consider a skill a candidate

# ── Skill registry ────────────────────────────────────────────────────────────

_skills: dict[str, dict] = {}   # name → {module, TOOLS, TOOL_MAP, KEYWORDS, SKILL_DESCRIPTION}


def load_skills() -> dict[str, dict]:
    """
    Auto-discover and load all skill files from SKILLS_DIR.
    A valid skill file must export: SKILL_NAME, SKILL_DESCRIPTION, TOOL_MAP, KEYWORDS.
    """
    registry = {}

    if not SKILLS_DIR.exists():
        print(f"[router] skills dir not found: {SKILLS_DIR}")
        return registry

    for skill_file in sorted(SKILLS_DIR.glob("*_skill.py")):
        try:
            spec   = importlib.util.spec_from_file_location(skill_file.stem, skill_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            name = getattr(module, "SKILL_NAME", skill_file.stem)
            registry[name] = {
                "module":      module,
                "file":        str(skill_file),
                "description": getattr(module, "SKILL_DESCRIPTION", ""),
                "tool_map":    getattr(module, "TOOL_MAP",  {}),
                "keywords":    getattr(module, "KEYWORDS",  {}),
                "tools":       getattr(module, "TOOLS",     []),
            }
            print(f"[router] loaded skill: {name}  ({len(registry[name]['tool_map'])} tools)")
        except Exception as e:
            print(f"[router] failed to load {skill_file.name}: {e}")

    return registry


def get_skills() -> dict:
    global _skills
    if not _skills:
        _skills = load_skills()
    return _skills


# ── Keyword scorer ────────────────────────────────────────────────────────────

def score_skills(task: str) -> list[tuple[str, str, int]]:
    """
    Score each skill's tools against the task text by keyword overlap.
    Returns sorted list of (skill_name, tool_name, score) descending.
    """
    task_lower = task.lower()
    hits = []

    for skill_name, skill in get_skills().items():
        for tool_name, kw_list in skill["keywords"].items():
            score = sum(1 for kw in kw_list if kw.lower() in task_lower)
            if score >= 1:
                hits.append((skill_name, tool_name, score))

    hits.sort(key=lambda x: x[2], reverse=True)
    return hits


def top_candidates(task: str, top_n: int = 3) -> list[dict]:
    """Return top N skill+tool candidates as dicts for the LLM prompt."""
    scores = score_skills(task)
    seen = set()
    candidates = []
    for skill_name, tool_name, score in scores:
        key = f"{skill_name}.{tool_name}"
        if key not in seen:
            seen.add(key)
            skill = get_skills()[skill_name]
            # Find tool description
            tool_desc = ""
            for t in skill["tools"]:
                if t.get("function", {}).get("name") == tool_name:
                    tool_desc = t["function"].get("description", "")
                    break
            candidates.append({
                "skill":       skill_name,
                "tool":        tool_name,
                "score":       score,
                "description": tool_desc or skill["description"],
            })
        if len(candidates) >= top_n:
            break
    return candidates


# ── LLM call (Ollama) ─────────────────────────────────────────────────────────

def _ollama_chat(messages: list[dict], model: str = ROUTER_MODEL, timeout: int = 30) -> str:
    """Call Ollama chat endpoint, return assistant text."""
    import urllib.request

    payload = json.dumps({
        "model":    model,
        "messages": messages,
        "stream":   False,
        "options":  {"temperature": 0.1, "num_predict": 512},
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data["message"]["content"].strip()
    except Exception as e:
        return f"[llm_error] {e}"


# ── Router logic ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are JARVIS, an AI operating system router.
Your only job is to decide how to handle a user task — you do NOT execute anything yourself.

Available skills and their tools will be provided to you.

Respond ONLY with valid JSON in one of these three formats:

ROUTE — you know exactly what to do:
{"mode": "route", "skill": "<skill_name>", "tool": "<tool_name>", "args": {<tool_args>}, "reason": "<one line>"}

CLARIFY — task is ambiguous, need one piece of info:
{"mode": "clarify", "question": "<single specific question>", "reason": "<why you need this>"}

REJECT — task is out of scope or unsafe:
{"mode": "reject", "reason": "<brief explanation>"}

Rules:
- Prefer ROUTE over CLARIFY. Only clarify if you truly cannot pick a tool without more info.
- Never route to code_edit unless the task explicitly mentions editing a specific file.
- Never execute shell commands yourself — route to the shell skill.
- Never answer questions directly — if no skill handles it, REJECT with a helpful reason.
- Args must match the tool's parameter schema exactly.
- Respond with JSON only. No preamble, no explanation outside the JSON.
"""


def build_routing_prompt(task: str, candidates: list[dict], clarify_answer: str = "") -> str:
    """Build the user message for the LLM router."""
    skill_summary = "\n".join(
        f"  skill={c['skill']}  tool={c['tool']}  — {c['description']}"
        for c in candidates
    )

    # Also include all skills briefly so LLM knows full scope
    all_skills = "\n".join(
        f"  {name}: {s['description'][:120]}"
        for name, s in get_skills().items()
    )

    msg = f"""Task: {task}

Top keyword matches:
{skill_summary or '  (none — use all_skills below)'}

All available skills:
{all_skills}
"""
    if clarify_answer:
        msg += f"\nUser clarified: {clarify_answer}"

    return msg


def route(task: str, clarify_answer: str = "") -> dict:
    """
    Core routing function.
    Returns a dict with mode: route | clarify | reject
    plus relevant fields for each mode.
    """
    candidates = top_candidates(task, top_n=5)

    messages = [
        {"role": "system",  "content": SYSTEM_PROMPT},
        {"role": "user",    "content": build_routing_prompt(task, candidates, clarify_answer)},
    ]

    raw = _ollama_chat(messages)

    # Strip any thinking tags local models sometimes emit
    if "<think>" in raw:
        raw = raw[raw.rfind("</think>") + 8:].strip()

    # Parse JSON
    try:
        # Find first { ... } block in case model adds extra text
        start = raw.index("{")
        end   = raw.rindex("}") + 1
        decision = json.loads(raw[start:end])
    except Exception:
        # Fallback: if LLM fails, use top keyword hit
        if candidates:
            top = candidates[0]
            decision = {
                "mode":   "route",
                "skill":  top["skill"],
                "tool":   top["tool"],
                "args":   {},
                "reason": "keyword fallback (LLM parse failed)",
            }
        else:
            decision = {
                "mode":   "reject",
                "reason": "Could not understand task and no matching skill found.",
            }

    decision["_raw_llm"] = raw
    return decision


# ── Dispatcher ────────────────────────────────────────────────────────────────

def dispatch(decision: dict) -> str:
    """Execute a ROUTE decision by calling the skill's TOOL_MAP."""
    skill_name = decision.get("skill")
    tool_name  = decision.get("tool")
    args       = decision.get("args", {})

    skills = get_skills()
    if skill_name not in skills:
        return f"[error] Unknown skill: {skill_name}"

    tool_map = skills[skill_name]["tool_map"]
    if tool_name not in tool_map:
        return f"[error] Unknown tool '{tool_name}' in skill '{skill_name}'"

    try:
        result = tool_map[tool_name](args)
        return str(result)
    except Exception as e:
        return f"[error] {skill_name}.{tool_name} raised: {e}"


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_task(task: str, verbose: bool = True) -> dict:
    """
    Process a single task through the full routing pipeline.
    Returns full result dict with mode, decision, output.
    """
    if verbose:
        print(f"\n[router] task: {task}")

    start = time.monotonic()
    decision = route(task)
    elapsed = round(time.monotonic() - start, 2)

    if verbose:
        print(f"[router] mode={decision['mode']}  ({elapsed}s)")

    result = {"task": task, "decision": decision, "output": None, "elapsed_s": elapsed}

    if decision["mode"] == "route":
        if verbose:
            print(f"[router] → {decision['skill']}.{decision['tool']}  args={decision.get('args',{})}")
            print(f"[router]   reason: {decision.get('reason','')}")
        output = dispatch(decision)
        result["output"] = output
        if verbose:
            print(f"\n{output}")

    elif decision["mode"] == "clarify":
        result["output"] = decision["question"]
        if verbose:
            print(f"[router] clarify: {decision['question']}")

    elif decision["mode"] == "reject":
        result["output"] = f"Out of scope: {decision['reason']}"
        if verbose:
            print(f"[router] reject: {decision['reason']}")

    return result


def interactive_loop():
    """CLI interactive mode with clarify support."""
    print("JARVIS Agent Loop — interactive mode")
    print(f"Router model: {ROUTER_MODEL}  |  Skills: {SKILLS_DIR}")
    print(f"Loaded {len(get_skills())} skills: {', '.join(get_skills().keys())}")
    print("Type 'exit' to quit.\n")

    clarify_pending: Optional[str] = None
    original_task:   Optional[str] = None

    while True:
        try:
            prompt = "clarify> " if clarify_pending else "jarvis> "
            user_input = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not user_input or user_input.lower() in ("exit", "quit"):
            break

        if clarify_pending:
            # Re-route original task with clarification answer
            result = run_task(original_task, verbose=False)
            # Actually route with clarify answer
            decision = route(original_task, clarify_answer=user_input)
            if decision["mode"] == "route":
                output = dispatch(decision)
                print(f"\n→ {decision['skill']}.{decision['tool']}\n{output}\n")
            else:
                print(f"\n{decision.get('reason', decision.get('question', '?'))}\n")
            clarify_pending  = None
            original_task    = None
        else:
            result = run_task(user_input)
            if result["decision"]["mode"] == "clarify":
                clarify_pending = result["decision"]["question"]
                original_task   = user_input
                print(f"\n? {clarify_pending}\n")


# ── FastAPI app (optional) ────────────────────────────────────────────────────

try:
    from fastapi import FastAPI
    from pydantic import BaseModel

    app = FastAPI(title="JARVIS Agent Loop")

    class TaskRequest(BaseModel):
        task: str
        clarify_answer: str = ""

    @app.post("/route")
    def http_route(req: TaskRequest):
        """Route a task, returns decision + output if routed."""
        decision = route(req.task, req.clarify_answer)
        output = None
        if decision["mode"] == "route":
            output = dispatch(decision)
        return {"decision": decision, "output": output}

    @app.get("/skills")
    def http_skills():
        """List all loaded skills and their tools."""
        return {
            name: {
                "description": s["description"],
                "tools": list(s["tool_map"].keys()),
            }
            for name, s in get_skills().items()
        }

    @app.post("/reload")
    def http_reload():
        """Reload all skills from disk."""
        global _skills
        _skills = {}
        _skills = load_skills()
        return {"loaded": list(_skills.keys())}

except ImportError:
    app = None


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "--serve":
        # Single task mode
        run_task(" ".join(sys.argv[1:]))
    elif "--serve" in sys.argv:
        import uvicorn
        uvicorn.run("agent_loop:app", host="127.0.0.1", port=8100, reload=False)
    else:
        interactive_loop()
