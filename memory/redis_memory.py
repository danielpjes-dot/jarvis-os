"""
JARVIS OS — Redis Memory Module
Handles all short-term agent memory: state, tools, working memory, task steps, loop counter.
Drop into /jarvis/memory/redis_memory.py
"""

import json
import redis
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

r = redis.Redis(host="localhost", port=6379, decode_responses=True)

# ---------------------------------------------------------------------------
# TTLs
# ---------------------------------------------------------------------------

TTL_STATE    = 4 * 3600   # 4h  — agent state block
TTL_TASK     = 4 * 3600   # 4h  — active task + steps
TTL_TOOLS    = 30         # 30s — tool health (probe frequently)
TTL_WORKING  = 2 * 3600   # 2h  — working memory rolling buffer
TTL_LOOP     = 4 * 3600   # 4h  — loop counter
TTL_FLAGS    = 1 * 3600   # 1h  — arbitrary session flags

WORKING_MEMORY_CAP = 10   # max items in rolling buffer

# ---------------------------------------------------------------------------
# Core read/write
# ---------------------------------------------------------------------------

def mem_write(key: str, value: Any, ttl: int = TTL_STATE) -> bool:
    try:
        payload = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        r.setex(key, ttl, payload)
        return True
    except redis.RedisError:
        return False

def mem_read(key: str, default: Any = None) -> Any:
    try:
        raw = r.get(key)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return raw
    except redis.RedisError:
        return default

def mem_delete(key: str) -> bool:
    try:
        r.delete(key)
        return True
    except redis.RedisError:
        return False

def mem_exists(key: str) -> bool:
    try:
        return r.exists(key) == 1
    except redis.RedisError:
        return False

# ---------------------------------------------------------------------------
# Agent state block
# ---------------------------------------------------------------------------

def write_state(identity: str, task: str, tools: dict, confidence: str = "high", notes: str = ""):
    state = {
        "identity":   identity,
        "task":       task,
        "tools":      tools,
        "confidence": confidence,
        "notes":      notes,
        "updated_at": datetime.utcnow().isoformat(),
    }
    mem_write("agent:state", state, TTL_STATE)
    return state

def read_state() -> dict:
    return mem_read("agent:state", default={})

def update_state(**kwargs):
    """Patch specific fields in the existing state block."""
    state = read_state()
    state.update(kwargs)
    state["updated_at"] = datetime.utcnow().isoformat()
    mem_write("agent:state", state, TTL_STATE)
    return state

def format_state_block() -> str:
    """Returns compact header string ready to inject into LLM system prompt."""
    s = read_state()
    if not s:
        return "AGENT STATE: unavailable"
    tools_str = ", ".join(
        f"{k}={'✓' if v else '✗'}" for k, v in s.get("tools", {}).items()
    )
    return (
        f"AGENT STATE:\n"
        f"- Identity:   {s.get('identity', 'JARVIS')}\n"
        f"- Task:       {s.get('task', 'none')}\n"
        f"- Tools:      [{tools_str}]\n"
        f"- Confidence: {s.get('confidence', 'unknown')}\n"
        f"- Notes:      {s.get('notes', '')}\n"
        f"- Updated:    {s.get('updated_at', 'unknown')}"
    )

# ---------------------------------------------------------------------------
# Tool health
# ---------------------------------------------------------------------------

def write_tools(tools: dict[str, bool]):
    mem_write("agent:tools", tools, TTL_TOOLS)

def read_tools() -> dict:
    return mem_read("agent:tools", default={})

def set_tool(name: str, status: bool):
    tools = read_tools()
    tools[name] = status
    write_tools(tools)

# ---------------------------------------------------------------------------
# Working memory — capped rolling list
# ---------------------------------------------------------------------------

def push_memory(item: str):
    """Push item to working memory. Caps at WORKING_MEMORY_CAP. Resets TTL."""
    try:
        r.rpush("agent:memory:working", item)
        r.ltrim("agent:memory:working", -WORKING_MEMORY_CAP, -1)
        r.expire("agent:memory:working", TTL_WORKING)
    except redis.RedisError:
        pass

def read_memory() -> list[str]:
    try:
        return r.lrange("agent:memory:working", 0, -1)
    except redis.RedisError:
        return []

def clear_memory():
    mem_delete("agent:memory:working")

# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

def write_task(task: str):
    mem_write("agent:task:current", task, TTL_TASK)

def read_task() -> str:
    return mem_read("agent:task:current", default="")

def push_step(step: str):
    try:
        r.rpush("agent:task:steps", step)
        r.expire("agent:task:steps", TTL_TASK)
    except redis.RedisError:
        pass

def read_steps() -> list[str]:
    try:
        return r.lrange("agent:task:steps", 0, -1)
    except redis.RedisError:
        return []

def clear_task():
    mem_delete("agent:task:current")
    mem_delete("agent:task:steps")

# ---------------------------------------------------------------------------
# Loop counter
# ---------------------------------------------------------------------------

def increment_loop() -> int:
    try:
        count = r.incr("agent:loop:count")
        r.expire("agent:loop:count", TTL_LOOP)
        return int(count)
    except redis.RedisError:
        return 0

def read_loop() -> int:
    return int(mem_read("agent:loop:count", default=0))

def reset_loop():
    mem_delete("agent:loop:count")

# ---------------------------------------------------------------------------
# Flags — arbitrary boolean/string session flags
# ---------------------------------------------------------------------------

def set_flag(name: str, value: Any = True):
    mem_write(f"agent:flags:{name}", value, TTL_FLAGS)

def get_flag(name: str, default: Any = None) -> Any:
    return mem_read(f"agent:flags:{name}", default=default)

def clear_flag(name: str):
    mem_delete(f"agent:flags:{name}")

# ---------------------------------------------------------------------------
# Session flush — call before clearing at session end
# ---------------------------------------------------------------------------

def snapshot() -> dict:
    """Collect full session state. Pass to Qdrant/Obsidian archiver before flush."""
    return {
        "state":          read_state(),
        "task":           read_task(),
        "steps":          read_steps(),
        "working_memory": read_memory(),
        "tools":          read_tools(),
        "loop_count":     read_loop(),
        "snapshot_at":    datetime.utcnow().isoformat(),
    }

def flush():
    """Wipe all agent:* keys. Always call snapshot() first."""
    try:
        keys = r.keys("agent:*")
        if keys:
            r.delete(*keys)
    except redis.RedisError:
        pass

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def ping() -> bool:
    try:
        return r.ping()
    except redis.RedisError:
        return False