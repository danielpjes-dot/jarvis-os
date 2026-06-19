"""
JARVIS Skill — App Scaffolder
=====================================
Interactive project scaffolding wizard. Interviews the user about tech stack
via structured questions, then either:
  a) generates the scaffold directly (standalone project), or
  b) feeds tech_decisions into planner.exec_plan() so the planner
     creates correctly-targeted tasks for the chosen stack.

Based on app-scaffolder SKILL.md — uses previous JARVIS project patterns
(BullishBeat/StockWatch railway microservices, Caskra Nile multi-tenant,
Alchemians brewery) as reference architecture.
"""

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Optional

SKILL_NAME = "scaffolder"
SKILL_DESCRIPTION = (
    "Interactive app scaffolding wizard. Asks structured tech stack questions "
    "(framework, database, auth, payments, AI, deployment) based on previous JARVIS "
    "projects, then generates a complete scaffold or feeds decisions into the planner. "
    "Use for: 'new app', 'new project', 'scaffold', 'start a project', 'build me an app', "
    "'set up a new service', 'create a new project', 'pick a tech stack', "
    "'bootstrap', 'new microservice', 'architecture planning'."
)

OLLAMA_HOST    = os.getenv("OLLAMA_HOST",           "http://localhost:11434")
DRAFTER_MODEL  = os.getenv("JARVIS_DRAFTER_MODEL",  "qwen3:14b")
STAGING_ROOT   = Path(os.getenv("JARVIS_STAGING",   "/mnt/e/coding/staging"))
REDIS_HOST     = os.getenv("JARVIS_REDIS_HOST",     "localhost")
REDIS_PORT     = int(os.getenv("JARVIS_REDIS_PORT",  6379))

# ── Reference project patterns (from JARVIS memory) ───────────────────────────

REFERENCE_PROJECTS = {
    "bullishbeat": {
        "stack":   "FastAPI + Railway microservices (9 services) + Vertex AI + Polygon.io + Redis",
        "pattern": "railway_microservices",
        "notes":   "regime-aware ML, WebSocket live trading, XGBoost models",
    },
    "caskra": {
        "stack":   "Next.js + FastAPI + Nile.tech PostgreSQL (multi-tenant RLS) + PostHog + Drizzle",
        "pattern": "nile_multitenant",
        "notes":   "brewery SaaS, multi-tenant row isolation, 11-language i18n",
    },
    "dravn": {
        "stack":   "FastAPI + Helm/K8s + Semgrep SAST + hardened Dockerfile",
        "pattern": "enterprise_api",
        "notes":   "enterprise API integration platform, security-hardened",
    },
    "jarvis_os": {
        "stack":   "FastAPI + Next.js dashboard + Ollama + Qdrant + Redis + Obsidian vault",
        "pattern": "local_ai",
        "notes":   "fully local AI OS, WSL2 Ubuntu, no cloud dependencies",
    },
}

# ── Interview questions ────────────────────────────────────────────────────────

INTERVIEW_QUESTIONS = [
    {
        "id":      "project_name",
        "prompt":  "What's your project name?",
        "type":    "text",
    },
    {
        "id":      "description",
        "prompt":  "One-sentence description?",
        "type":    "text",
    },
    {
        "id":      "reference_pattern",
        "prompt":  "Closest existing JARVIS project pattern?",
        "type":    "choice",
        "options": [
            ("railway_microservices", "BullishBeat — Railway microservices, ML/AI backend"),
            ("nile_multitenant",      "Caskra — Multi-tenant SaaS, Nile Postgres, Next.js"),
            ("enterprise_api",        "DRAVN — Enterprise API, K8s, security-hardened"),
            ("local_ai",              "JARVIS OS — Local AI, Ollama, no cloud"),
            ("greenfield",            "Greenfield — No reference pattern"),
        ],
    },
    {
        "id":      "frontend",
        "prompt":  "Frontend framework?",
        "type":    "choice",
        "options": [
            ("nextjs",     "Next.js 15 + React 19 (recommended) — SSR, Vercel-ready"),
            ("vite_react", "Vite + React 19 — SPA, fast dev"),
            ("nuxt",       "Nuxt 4 + Vue 3"),
            ("sveltekit",  "SvelteKit — Lightweight"),
            ("none",       "None — API only"),
        ],
        "default": "nextjs",
    },
    {
        "id":      "css",
        "prompt":  "CSS framework?",
        "type":    "choice",
        "options": [
            ("tailwind",  "Tailwind CSS (recommended)"),
            ("shadcn",    "shadcn/ui + Tailwind — Pre-built components"),
            ("chakra",    "Chakra UI"),
            ("plain",     "Plain CSS"),
        ],
        "default": "shadcn",
        "skip_if": {"frontend": "none"},
    },
    {
        "id":      "backend",
        "prompt":  "Backend framework?",
        "type":    "choice",
        "options": [
            ("fastapi",  "FastAPI (recommended) — Async, auto-docs, great for AI"),
            ("django",   "Django — Batteries-included, admin panel"),
            ("express",  "Node.js Express — Lightweight"),
            ("fastify",  "Node.js Fastify — Fast Express alternative"),
            ("none",     "None — Next.js API routes only"),
        ],
        "default": "fastapi",
    },
    {
        "id":      "database",
        "prompt":  "Database?",
        "type":    "choice",
        "options": [
            ("postgres",  "PostgreSQL (recommended)"),
            ("nile",      "Nile — Multi-tenant Postgres (like Caskra)"),
            ("sqlite",    "SQLite — Serverless, good for small apps"),
            ("mongo",     "MongoDB — Document store"),
        ],
        "default": "postgres",
    },
    {
        "id":      "db_hosting",
        "prompt":  "Database hosting?",
        "type":    "choice",
        "options": [
            ("railway",   "Railway PostgreSQL (recommended) — Managed, $5/mo"),
            ("nile",      "Nile — Multi-tenant Postgres (eu-central-1 or us-west-2)"),
            ("supabase",  "Supabase — Managed Postgres + auth + storage"),
            ("neon",      "Neon — Serverless Postgres, scales to zero"),
            ("docker",    "Self-hosted in Docker — Full control"),
        ],
        "default": "railway",
    },
    {
        "id":      "auth",
        "prompt":  "Authentication?",
        "type":    "choice",
        "options": [
            ("jwt_roles",  "JWT + bcrypt + RBAC (recommended) — Full control, API keys, rate limiting"),
            ("authjs",     "Auth.js + JWT hardened — Social login + StockWatch security"),
            ("supabase",   "Supabase Auth — Managed, social logins"),
            ("clerk",      "Clerk — Drop-in UI, managed"),
            ("none",       "None — No auth yet"),
        ],
        "default": "jwt_roles",
    },
    {
        "id":      "payments",
        "prompt":  "Payments?",
        "type":    "choice",
        "options": [
            ("stripe",         "Stripe — Cards, subscriptions, invoices"),
            ("revolut",        "Revolut Business — European, competitive FX"),
            ("stripe_revolut", "Stripe + Revolut — Best of both"),
            ("none",           "None — No payments yet"),
        ],
        "default": "none",
    },
    {
        "id":      "ai",
        "prompt":  "AI/ML integration?",
        "type":    "choice",
        "options": [
            ("claude",   "Claude (Anthropic) — Best reasoning, tool use"),
            ("ollama",   "Local Ollama — Privacy-first, no API costs (like JARVIS)"),
            ("openai",   "OpenAI GPT-4"),
            ("vertex",   "Google Vertex AI (like BullishBeat)"),
            ("multi",    "Multiple providers with fallback chain"),
            ("none",     "None — No AI"),
        ],
        "default": "none",
    },
    {
        "id":      "cache",
        "prompt":  "Caching / job queue?",
        "type":    "choice",
        "options": [
            ("redis",  "Redis — Cache + queue + pub/sub (recommended)"),
            ("celery", "Celery + Redis — Distributed tasks"),
            ("none",   "None"),
        ],
        "default": "redis",
    },
    {
        "id":      "deployment",
        "prompt":  "Deployment target?",
        "type":    "choice",
        "options": [
            ("railway",      "Railway (recommended) — Easy, managed, $5/mo"),
            ("fly",          "Fly.io — Edge, Docker-based"),
            ("vercel",       "Vercel — Frontend + serverless functions"),
            ("docker_vps",   "Self-hosted VPS + Docker — Full control"),
            ("k8s",          "Kubernetes (like DRAVN)"),
        ],
        "default": "railway",
    },
    {
        "id":      "architecture",
        "prompt":  "Architecture?",
        "type":    "choice",
        "options": [
            ("monolith",      "Monolith (recommended for starting)"),
            ("microservices", "Microservices (like BullishBeat — 9 services)"),
            ("modular",       "Modular monolith — Single deploy, internal modules"),
        ],
        "default": "monolith",
    },
    {
        "id":      "extras",
        "prompt":  "Extra features? (comma-separated numbers or 'none')",
        "type":    "multi",
        "options": [
            ("i18n",        "i18n multi-language (like Caskra — 11 languages)"),
            ("rate_limit",  "Rate limiting"),
            ("feature_flags", "Feature flags / plan gating"),
            ("api_keys",    "API key management"),
            ("webhooks",    "Webhook system"),
            ("realtime",    "Real-time WebSockets"),
            ("seo",         "SEO optimization"),
            ("pwa",         "PWA"),
            ("analytics",   "Analytics dashboard (Recharts)"),
            ("monitoring",  "Sentry + PostHog monitoring"),
        ],
    },
]


# ── LLM helper ─────────────────────────────────────────────────────────────────

def _ollama(messages: list[dict], max_tokens: int = 2000) -> str:
    payload = json.dumps({
        "model":    DRAFTER_MODEL,
        "messages": messages,
        "stream":   False,
        "options":  {"temperature": 0.2, "num_predict": max_tokens},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            text = json.loads(resp.read())["message"]["content"].strip()
            if "<think>" in text:
                text = text[text.rfind("</think>") + 8:].strip()
            return text
    except Exception as e:
        return f"[llm_error] {e}"


# ── Scaffold generator ─────────────────────────────────────────────────────────

SCAFFOLD_SYSTEM = """You are JARVIS app scaffolder. Generate a complete project scaffold based on tech decisions.

Reference projects for patterns:
- BullishBeat: FastAPI + Railway microservices + Redis + ML models
- Caskra: Next.js + FastAPI + Nile multi-tenant Postgres + i18n
- DRAVN: FastAPI + K8s/Helm + security-hardened
- JARVIS OS: FastAPI + Next.js + Ollama + Qdrant + Redis

Output a complete project as JSON with this structure:
{
  "project_name": "<name>",
  "files": [
    {"path": "relative/path/file.ext", "content": "<full file content>"},
    ...
  ],
  "commands": ["<setup command 1>", ...],
  "env_vars": {"VAR_NAME": "description"},
  "next_steps": ["<step 1>", ...]
}

Generate REAL working code — no placeholders, no TODOs.
Always include: docker-compose.yml, backend/main.py, README.md, .env.example, start.sh.
Apply security checklist: CORS, JWT short expiry, bcrypt cost 12, rate limiting, no secrets in code.
JSON only. No preamble."""


def generate_scaffold(decisions: dict) -> dict:
    """Call LLM to generate the full scaffold based on tech decisions."""
    messages = [
        {"role": "system", "content": SCAFFOLD_SYSTEM},
        {"role": "user",   "content": f"Tech decisions:\n{json.dumps(decisions, indent=2)}\n\nGenerate the project scaffold now."},
    ]
    raw = _ollama(messages, max_tokens=4000)

    # Extract JSON
    try:
        start = raw.index("{")
        end   = raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except Exception:
        return {"error": "Could not parse scaffold", "raw": raw[:500]}


def write_scaffold_to_staging(scaffold: dict, plan_id: str) -> list[str]:
    """Write all scaffold files to staging/dev/{plan_id}/."""
    written = []
    base    = STAGING_ROOT / "dev" / plan_id

    for file_entry in scaffold.get("files", []):
        path    = base / file_entry["path"]
        content = file_entry.get("content", "")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(str(path.relative_to(STAGING_ROOT)))

    return written


def decisions_to_planner_goal(decisions: dict) -> str:
    """Convert tech decisions into a planner-ready goal string."""
    name   = decisions.get("project_name", "new project")
    desc   = decisions.get("description",  "")
    stack  = []

    if decisions.get("frontend") not in ("none", None):
        stack.append(decisions["frontend"])
    if decisions.get("backend") not in ("none", None):
        stack.append(decisions["backend"])
    if decisions.get("database"):
        stack.append(decisions["database"])
    if decisions.get("auth") not in ("none", None):
        stack.append(f"{decisions['auth']} auth")
    if decisions.get("ai") not in ("none", None):
        stack.append(f"{decisions['ai']} AI")

    stack_str = " + ".join(stack)
    return f"Build {name}: {desc}. Stack: {stack_str}. Deployment: {decisions.get('deployment','railway')}. Architecture: {decisions.get('architecture','monolith')}."


# ── Tool executors ─────────────────────────────────────────────────────────────

def exec_interview(project_name: str = "", description: str = "") -> str:
    """
    Run the interactive scaffolding interview.
    Returns a formatted summary of all tech decisions as JSON string.
    In JARVIS interactive mode this drives a multi-turn conversation —
    here it returns the full question set for the agent loop to present.
    """
    questions_out = []
    for q in INTERVIEW_QUESTIONS:
        entry = {
            "id":     q["id"],
            "prompt": q["prompt"],
            "type":   q["type"],
        }
        if "options" in q:
            entry["options"] = [f"{i+1}. {o[1]}" for i, o in enumerate(q["options"])]
        if "default" in q:
            entry["default"] = q["default"]
        if "skip_if" in q:
            entry["skip_if"] = q["skip_if"]
        questions_out.append(entry)

    # Pre-fill known values
    prefill = {}
    if project_name:
        prefill["project_name"] = project_name
    if description:
        prefill["description"] = description

    return json.dumps({
        "action":   "interview",
        "questions": questions_out,
        "prefill":  prefill,
        "instruction": (
            "Present these questions to the user one category at a time. "
            "After all answers collected, call scaffold_from_decisions with the results dict."
        ),
    }, indent=2)


def exec_scaffold_from_decisions(decisions_json: str, send_to_planner: bool = False) -> str:
    """
    Given a JSON string of tech decisions, either:
    - Generate scaffold directly and write to staging/dev/{plan_id}/
    - Or feed decisions into planner.exec_plan() for task-based execution
    """
    try:
        decisions = json.loads(decisions_json)
    except Exception as e:
        return f"Error: could not parse decisions JSON: {e}"

    plan_id   = f"scaffold_{int(time.time())}"
    lines     = [f"=== Scaffolding: {decisions.get('project_name', '?')} ===\n"]
    lines.append(f"Plan ID: {plan_id}")
    lines.append(f"Pattern: {decisions.get('reference_pattern', 'greenfield')}\n")

    if send_to_planner:
        # Feed into planner for task decomposition
        goal = decisions_to_planner_goal(decisions)
        lines.append(f"Sending to planner: {goal}\n")

        # Import planner dynamically (avoids circular if same skills dir)
        try:
            import importlib.util
            planner_path = next(
                (p for p in [
                    Path(os.getenv("JARVIS_SKILLS_DIR", "/mnt/e/coding/jarvis-os/skills")) / "planner_skill.py",
                    Path(__file__).parent / "planner_skill.py",
                ] if p.exists()),
                None
            )
            if planner_path:
                spec = importlib.util.spec_from_file_location("planner_skill", planner_path)
                mod  = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                result = mod.exec_plan(goal)
                lines.append(result)
            else:
                lines.append("Error: planner_skill.py not found")
        except Exception as e:
            lines.append(f"Error calling planner: {e}")
    else:
        # Generate scaffold directly
        lines.append("Generating scaffold via LLM...")
        scaffold = generate_scaffold(decisions)

        if "error" in scaffold:
            return f"Scaffold generation failed: {scaffold['error']}"

        written = write_scaffold_to_staging(scaffold, plan_id)
        lines.append(f"✓ {len(written)} files written to staging/dev/{plan_id}/\n")

        for f in written:
            lines.append(f"  {f}")

        if scaffold.get("commands"):
            lines.append("\nSetup commands:")
            for cmd in scaffold["commands"]:
                lines.append(f"  $ {cmd}")

        if scaffold.get("env_vars"):
            lines.append("\nRequired env vars:")
            for k, v in scaffold["env_vars"].items():
                lines.append(f"  {k}: {v}")

        if scaffold.get("next_steps"):
            lines.append("\nNext steps:")
            for step in scaffold["next_steps"]:
                lines.append(f"  → {step}")

        lines.append(f"\nFiles in staging/dev/{plan_id}/ — review then promote_plan to tested/")

    return "\n".join(lines)


def exec_list_patterns() -> str:
    """List available reference project patterns from JARVIS history."""
    lines = ["Available reference patterns:\n"]
    for name, info in REFERENCE_PROJECTS.items():
        lines.append(f"  {name}")
        lines.append(f"    Stack:   {info['stack']}")
        lines.append(f"    Notes:   {info['notes']}")
    return "\n".join(lines)


def exec_quick_scaffold(project_name: str, pattern: str = "nile_multitenant") -> str:
    """
    Quick scaffold using defaults from a reference pattern.
    No interview — uses the reference project's proven stack.
    """
    pattern_defaults = {
        "railway_microservices": {
            "frontend": "nextjs", "css": "shadcn", "backend": "fastapi",
            "database": "postgres", "db_hosting": "railway",
            "auth": "jwt_roles", "cache": "redis",
            "deployment": "railway", "architecture": "microservices",
            "ai": "vertex", "payments": "stripe",
        },
        "nile_multitenant": {
            "frontend": "nextjs", "css": "shadcn", "backend": "fastapi",
            "database": "nile", "db_hosting": "nile",
            "auth": "jwt_roles", "cache": "redis",
            "deployment": "railway", "architecture": "monolith",
            "extras": ["i18n", "rate_limit", "monitoring"],
        },
        "enterprise_api": {
            "frontend": "none", "backend": "fastapi",
            "database": "postgres", "db_hosting": "docker",
            "auth": "jwt_roles", "cache": "redis",
            "deployment": "k8s", "architecture": "microservices",
            "extras": ["rate_limit", "api_keys", "webhooks", "monitoring"],
        },
        "local_ai": {
            "frontend": "nextjs", "css": "tailwind", "backend": "fastapi",
            "database": "sqlite", "db_hosting": "docker",
            "auth": "jwt_roles", "cache": "redis",
            "deployment": "docker_vps", "architecture": "monolith",
            "ai": "ollama",
        },
    }

    defaults = pattern_defaults.get(pattern, pattern_defaults["nile_multitenant"])
    decisions = {
        "project_name": project_name,
        "description":  f"{project_name} — scaffolded from {pattern} pattern",
        "reference_pattern": pattern,
        **defaults,
    }

    return exec_scaffold_from_decisions(json.dumps(decisions))


# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "interview",
            "description": (
                "Start the interactive scaffolding interview. Returns structured questions "
                "for the user to answer about their tech stack. Call first for any new project."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "Project name if already known"},
                    "description":  {"type": "string", "description": "Project description if already known"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scaffold_from_decisions",
            "description": (
                "Generate complete project scaffold from collected tech decisions. "
                "Writes files to staging/dev/{plan_id}/. "
                "Set send_to_planner=true to decompose into tasks instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "decisions_json":   {"type": "string", "description": "JSON string of tech decisions from interview"},
                    "send_to_planner":  {"type": "boolean", "description": "If true, feed into planner instead of generating directly"},
                },
                "required": ["decisions_json"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "quick_scaffold",
            "description": (
                "Quick scaffold using defaults from a JARVIS reference pattern. "
                "No interview — uses proven stack from BullishBeat, Caskra, DRAVN, or JARVIS OS."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "Name of the new project"},
                    "pattern":      {
                        "type": "string",
                        "enum": ["railway_microservices", "nile_multitenant", "enterprise_api", "local_ai"],
                        "description": "Reference pattern to clone defaults from",
                    },
                },
                "required": ["project_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_patterns",
            "description": "List available reference project patterns from JARVIS project history.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

TOOL_MAP = {
    "interview":              lambda args: exec_interview(args.get("project_name", ""), args.get("description", "")),
    "scaffold_from_decisions": lambda args: exec_scaffold_from_decisions(args["decisions_json"], args.get("send_to_planner", False)),
    "quick_scaffold":         lambda args: exec_quick_scaffold(args["project_name"], args.get("pattern", "nile_multitenant")),
    "list_patterns":          lambda args: exec_list_patterns(),
}

KEYWORDS = {
    "interview":              ["new app", "new project", "start a project", "build me an app",
                               "set up a new service", "create a new project", "scaffold",
                               "tech stack", "architecture planning", "bootstrap"],
    "scaffold_from_decisions": ["scaffold from", "generate project", "create from decisions",
                                "build from answers", "generate scaffold"],
    "quick_scaffold":         ["quick scaffold", "clone pattern", "use caskra pattern",
                               "use bullishbeat pattern", "default stack", "same stack as"],
    "list_patterns":          ["list patterns", "available patterns", "reference projects",
                               "what patterns", "show patterns"],
}
