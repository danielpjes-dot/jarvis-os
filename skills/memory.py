"""
JARVIS Skill — MemPalace long-term memory (search, add, status).

This is a core continuity skill for JARVIS.
It connects day-to-day notes in the Obsidian vault with searchable long-term memory.
"""

import datetime
import subprocess
import os
from pathlib import Path

# NOTE: named "mempalace" (not "memory") — memory_core.py owns SKILL_NAME
# "memory"; two skills with the same name overwrite each other in the
# plan_runner registry.
SKILL_NAME = "mempalace"
SKILL_DESCRIPTION = "MemPalace long-term memory — search, add, status (vault-search fallback)"

VAULT_DIR = Path("D:/Jarvis_vault") if os.name == "nt" else Path("/mnt/d/Jarvis_vault")


def _mempalace_available() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("mempalace") is not None
    except Exception:
        return False


def _vault_text_search(query: str, max_results: int = 8) -> str:
    """Fallback search: scan vault .md files directly for the query terms."""
    if not VAULT_DIR.exists():
        return f"Vault not found at {VAULT_DIR}"

    terms = [t for t in query.lower().split() if len(t) > 2] or [query.lower()]
    results = []

    try:
        for md in sorted(VAULT_DIR.rglob("*.md"),
                         key=lambda f: f.stat().st_mtime, reverse=True):
            if ".trash" in md.parts or ".obsidian" in md.parts:
                continue
            try:
                text = md.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            low = text.lower()
            if all(t in low for t in terms) or (len(terms) > 1 and sum(t in low for t in terms) >= 2):
                lines = text.splitlines()
                snippet_lines = []
                for i, line in enumerate(lines):
                    if any(t in line.lower() for t in terms):
                        start, end = max(0, i - 2), min(len(lines), i + 3)
                        snippet_lines.append("\n".join(lines[start:end]))
                        if len(snippet_lines) >= 2:
                            break
                rel = md.relative_to(VAULT_DIR)
                results.append(f"[{rel}]\n" + "\n…\n".join(snippet_lines))
                if len(results) >= max_results:
                    break
    except Exception as e:
        return f"Vault search error: {e}"

    if not results:
        return f"No results found in vault for '{query}'."
    return "\n\n---\n\n".join(results)[:6000]


def exec_memory_search(query: str) -> str:
    if _mempalace_available():
        try:
            result = subprocess.run(
                ["python3", "-m", "mempalace", "search", query],
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = (result.stdout + result.stderr).strip()
            if output:
                return output[:6000]
        except subprocess.TimeoutExpired:
            return "Memory search timed out."
        except Exception:
            pass
    # mempalace not installed or returned nothing — search the vault directly
    return _vault_text_search(query)


def exec_memory_add(text: str, room: str = "general") -> str:
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    try:
        daily_dir = VAULT_DIR / "Daily"
        daily_dir.mkdir(parents=True, exist_ok=True)
        daily_file = daily_dir / f"{date_str}.md"

        if not daily_file.exists():
            daily_file.write_text(
                f"---\ncreated: {date_str}\ntags: [daily, jarvis]\n---\n\n# {date_str}\n\n",
                encoding="utf-8",
            )

        with open(daily_file, "a", encoding="utf-8") as f:
            f.write(f"\n## {time_str} — JARVIS Memory ({room})\n{text}\n")

        if _mempalace_available():
            subprocess.Popen(
                ["python3", "-m", "mempalace", "mine", str(VAULT_DIR)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return f"Saved to vault: Daily/{date_str}.md and queued for MemPalace mining"

        return f"Saved to vault: Daily/{date_str}.md"
    except Exception as e:
        return f"Memory save error: {e}"


def exec_memory_status() -> str:
    if _mempalace_available():
        try:
            result = subprocess.run(
                ["python3", "-m", "mempalace", "status"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            output = (result.stdout + result.stderr).strip()
            if output:
                return output[:4000]
        except Exception as e:
            return f"Memory status error: {e}"

    # Fallback status: vault stats
    try:
        md_count = sum(1 for _ in VAULT_DIR.rglob("*.md"))
        daily_count = sum(1 for _ in (VAULT_DIR / "Daily").glob("*.md")) if (VAULT_DIR / "Daily").exists() else 0
        return (
            f"MemPalace not installed — using direct vault search.\n"
            f"Vault: {VAULT_DIR}\n"
            f"Notes: {md_count} markdown files, {daily_count} daily logs."
        )
    except Exception as e:
        return f"Memory status error: {e}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search JARVIS long-term memory (MemPalace). Recall past conversations, decisions, facts about people, project history, and vault-linked memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for in memory",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_add",
            "description": "Save a new memory to JARVIS long-term storage. Use for preferences, facts, decisions, events, and notable project updates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The fact or memory to store",
                    },
                    "room": {
                        "type": "string",
                        "description": "Room: projects, team, daily, general, research",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_status",
            "description": "Show MemPalace status — wings, rooms, and memory count.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

TOOL_MAP = {
    "memory_search": exec_memory_search,
    "memory_add": exec_memory_add,
    "memory_status": exec_memory_status,
}

KEYWORDS = {
    "memory_search": [
        "who am i",
        "remember",
        "recall",
        "know me",
        "my name",
        "past",
        "history",
        "what did",
        "last time",
        "memory",
        "obsidian",
        "vault",
    ],
    "memory_add": [
        "remember this",
        "save this",
        "note that",
        "don't forget",
        "store this",
        "add to memory",
    ],
    "memory_status": [
        "memory status",
        "how many memories",
        "what do you know",
        "memory health",
    ],
}

SKILL_META = {
    "intent_aliases": [
        "memory",
        "remember",
        "recall",
        "long term memory",
        "obsidian memory",
        "vault memory",
        "mempalace",
    ],
    "keywords": [
        "memory",
        "remember",
        "recall",
        "who am i",
        "what do you know about me",
        "what do you remember",
        "past conversation",
        "last time",
        "history",
        "obsidian",
        "vault",
        "mempalace",
        "save to memory",
        "store this",
        "don't forget this",
    ],
    "route": "reason",
    "tools": {
        "memory_search": {
            "intent_aliases": [
                "memory search",
                "search memory",
                "recall",
                "remember",
                "what do you remember",
                "what do you know about me",
            ],
            "keywords": [
                "who am i",
                "remember",
                "recall",
                "know me",
                "my name",
                "past",
                "history",
                "what did",
                "last time",
                "memory",
                "obsidian",
                "vault",
                "search memory",
                "past conversation",
            ],
            "direct_match": [
                "who am i",
                "what do you remember",
                "what do you know about me",
                "search memory",
                "recall this",
                "remember me",
                "last time we talked about",
            ],
            "route": "reason",
        },
        "memory_add": {
            "intent_aliases": [
                "remember this",
                "save memory",
                "store this",
                "add to memory",
                "note this",
            ],
            "keywords": [
                "remember this",
                "save this",
                "note that",
                "don't forget",
                "store this",
                "add to memory",
                "save to memory",
            ],
            "direct_match": [
                "remember this",
                "save this",
                "store this",
                "add to memory",
                "don't forget this",
                "note this down",
            ],
            "route": "reason",
        },
        "memory_status": {
            "intent_aliases": [
                "memory status",
                "memory health",
                "mempalace status",
            ],
            "keywords": [
                "memory status",
                "how many memories",
                "what do you know",
                "memory health",
                "mempalace status",
            ],
            "direct_match": [
                "memory status",
                "mempalace status",
                "how many memories",
            ],
            "route": "reason",
        },
    },
}