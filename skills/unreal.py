"""
JARVIS Skill — Unreal Engine 5.8 MCP integration.

Connects to the built-in UE 5.8 MCP server (HTTP/JSON-RPC) or the
unrealmcp TCP bridge (port 55557) for custom tools not yet in the
official plugin (MetaHuman morph targets, emotion states).

UE side setup:
  1. Edit → Plugins → search "Unreal MCP" → enable → restart editor
  2. Console: ModelContextProtocol.GenerateClientConfig → check Output Log for port
  3. Add to Claude Code: claude mcp add unreal --transport http http://localhost:3000/mcp

Custom MetaHuman tools (Blueprint):
  Create BP_JarvisMCPBridge actor in the level that exposes:
    - SetMorphTarget(Name, Value)
    - SetEmotionState(StateName)
    - SetAmplitude(Value)
  Register these with the MCP plugin via C++ or Python UE scripting.
"""

import json
import os
import socket
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

SKILL_NAME        = "unreal"
SKILL_DESCRIPTION = "Control Unreal Engine 5.8 via MCP — spawn actors, control MetaHuman, lighting, Blueprints"
SKILL_VERSION     = "1.0.0"
SKILL_CATEGORY    = "creative"
SKILL_TAGS        = ["unreal", "ue5", "mcp", "metahuman", "3d", "game", "animation"]

SKILL_META = {
    "name":          SKILL_NAME,
    "description":   SKILL_DESCRIPTION,
    "entrypoint":    "exec_unreal",
    "route":         "tools",
    "intent_aliases": [
        "unreal engine", "spawn actor", "metahuman", "ue5", "set emotion in unreal",
        "place object", "lighting unreal", "blueprint", "unreal scene",
    ],
    "keywords": [
        "unreal", "ue5", "actor", "spawn", "metahuman", "morph", "blueprint",
        "lighting", "scene", "level", "material", "transform",
    ],
    "direct_match":  ["unreal", "spawn actor", "set metahuman emotion"],
    "network_access": True,
    "writes_files":  False,
    "response_style": {
        "default": "structured_status_ui",
        "avoid_raw_dump": True,
    },
}

# ── Config ────────────────────────────────────────────────────────────────────

# Official UE 5.8 built-in MCP server (HTTP/JSON-RPC Streamable transport)
# Port is printed to Output Log after: ModelContextProtocol.GenerateClientConfig
UE_MCP_HTTP_URL  = os.environ.get("UE_MCP_URL",        "http://localhost:3000/mcp")

# unrealmcp / custom C++ bridge (TCP, simpler for custom tools)
UE_TCP_HOST      = os.environ.get("UE_TCP_HOST",        "127.0.0.1")
UE_TCP_PORT      = int(os.environ.get("UE_TCP_PORT",    "55557"))

# File bridge (legacy — replaced by MCP, kept as fallback)
BRIDGE_DIR       = os.environ.get("UE_BRIDGE_DIR",      "E:/coding/jarvis-os/bridge")

_rpc_id = 0


# ── HTTP MCP client (UE 5.8 built-in) ────────────────────────────────────────

def _next_id() -> int:
    global _rpc_id
    _rpc_id += 1
    return _rpc_id


def _mcp_call(tool_name: str, arguments: dict, timeout: int = 15) -> Dict[str, Any]:
    """Call a tool on the UE 5.8 built-in MCP HTTP server (JSON-RPC 2.0)."""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id":      _next_id(),
        "method":  "tools/call",
        "params":  {"name": tool_name, "arguments": arguments},
    }).encode("utf-8")

    req = urllib.request.Request(
        UE_MCP_HTTP_URL,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept":       "application/json, text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            # Strip SSE envelope if present ("data: {...}\n\n")
            if raw.startswith("data:"):
                raw = "\n".join(
                    line[5:].strip()
                    for line in raw.splitlines()
                    if line.startswith("data:")
                )
            body = json.loads(raw) if raw.strip() else {}
            return {"ok": True, "result": body.get("result", body)}
    except urllib.error.URLError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _mcp_list_tools() -> Dict[str, Any]:
    """Fetch the tool manifest from the UE MCP server."""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id":      _next_id(),
        "method":  "tools/list",
        "params":  {},
    }).encode("utf-8")
    req = urllib.request.Request(
        UE_MCP_HTTP_URL,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            tools = body.get("result", {}).get("tools", [])
            return {"ok": True, "tools": [t.get("name") for t in tools]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── TCP bridge client (custom / unrealmcp tools) ──────────────────────────────

def _tcp_call(command: str, params: dict = None, timeout: int = 10) -> Dict[str, Any]:
    """Send a JSON command to the unrealmcp C++ TCP bridge on port 55557."""
    msg = json.dumps({"command": command, **(params or {})}) + "\n"
    try:
        with socket.create_connection((UE_TCP_HOST, UE_TCP_PORT), timeout=timeout) as sock:
            sock.sendall(msg.encode("utf-8"))
            raw = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                raw += chunk
                if b"\n" in raw:
                    break
        body = json.loads(raw.decode("utf-8", errors="replace").strip())
        ok = body.get("success", body.get("ok", True))
        return {"ok": bool(ok), "result": body}
    except ConnectionRefusedError:
        return {"ok": False, "error": f"TCP bridge not reachable at {UE_TCP_HOST}:{UE_TCP_PORT}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── File bridge (legacy fallback for emotion/state) ───────────────────────────

def _write_bridge(filename: str, content: str) -> bool:
    try:
        import pathlib
        p = pathlib.Path(BRIDGE_DIR) / filename
        p.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


# ── Convenience wrappers ──────────────────────────────────────────────────────

def _spawn_actor(actor_type: str, name: str = "", location: list = None,
                 rotation: list = None, scale: list = None) -> Dict[str, Any]:
    return _mcp_call("spawn_actor", {
        "actor_type": actor_type,
        "name":       name or actor_type,
        "location":   location or [0, 0, 0],
        "rotation":   rotation or [0, 0, 0],
        "scale":      scale    or [1, 1, 1],
    })


def _set_transform(actor_name: str, location: list = None,
                   rotation: list = None, scale: list = None) -> Dict[str, Any]:
    args = {"name": actor_name}
    if location: args["location"] = location
    if rotation: args["rotation"] = rotation
    if scale:    args["scale"]    = scale
    return _mcp_call("set_actor_transform", args)


def _get_actors(actor_type: str = "") -> Dict[str, Any]:
    return _mcp_call("get_actors_in_level", {"actor_type": actor_type} if actor_type else {})


def _set_material(actor_name: str, material_path: str,
                  slot: int = 0) -> Dict[str, Any]:
    return _mcp_call("set_material", {
        "name":          actor_name,
        "material_path": material_path,
        "slot_index":    slot,
    })


def _run_automation_test(test_name: str) -> Dict[str, Any]:
    return _mcp_call("run_automation_test", {"test_name": test_name}, timeout=60)


def _get_editor_state() -> Dict[str, Any]:
    return _mcp_call("get_editor_state", {})


# ── MetaHuman / Jarvis-specific (TCP custom tools) ────────────────────────────

# Emotion → morph target mapping (matches BP_JarvisMCPBridge in UE)
_EMOTION_MORPHS: Dict[str, Dict[str, float]] = {
    "neutral":   {"CTRL_expressions_mouthClose": 0.0, "CTRL_expressions_browInnerUp_L": 0.0},
    "happy":     {"CTRL_expressions_mouthSmile_L": 0.8, "CTRL_expressions_mouthSmile_R": 0.8,
                  "CTRL_expressions_cheekSquint_L": 0.4, "CTRL_expressions_cheekSquint_R": 0.4},
    "thinking":  {"CTRL_expressions_browInnerUp_L": 0.6, "CTRL_expressions_browInnerUp_R": 0.3,
                  "CTRL_expressions_eyeLookUp_L": 0.3},
    "focused":   {"CTRL_expressions_browDown_L": 0.4, "CTRL_expressions_browDown_R": 0.4,
                  "CTRL_expressions_eyeSquint_L": 0.3, "CTRL_expressions_eyeSquint_R": 0.3},
    "concerned": {"CTRL_expressions_browInnerUp_L": 0.7, "CTRL_expressions_browInnerUp_R": 0.7,
                  "CTRL_expressions_mouthFrown_L": 0.5, "CTRL_expressions_mouthFrown_R": 0.5},
    "surprised": {"CTRL_expressions_browOuterUp_L": 0.9, "CTRL_expressions_browOuterUp_R": 0.9,
                  "CTRL_expressions_eyeWide_L": 0.7, "CTRL_expressions_eyeWide_R": 0.7},
}


def _set_morph_target(morph_name: str, value: float) -> Dict[str, Any]:
    # Try TCP custom tool first, fall back to MCP call
    result = _tcp_call("set_morph_target", {"name": morph_name, "value": float(value)})
    if not result["ok"]:
        result = _mcp_call("set_morph_target", {"name": morph_name, "value": float(value)})
    return result


def _set_emotion(emotion: str) -> Dict[str, Any]:
    emotion = emotion.lower().strip()
    morphs  = _EMOTION_MORPHS.get(emotion, _EMOTION_MORPHS["neutral"])
    results = []
    for morph, val in morphs.items():
        r = _set_morph_target(morph, val)
        results.append({"morph": morph, "ok": r["ok"]})
    # Also write file bridge as backup
    _write_bridge("emotion.txt", emotion)
    all_ok = all(r["ok"] for r in results)
    return {"ok": all_ok, "emotion": emotion, "morphs": results}


def _set_amplitude(value: float) -> Dict[str, Any]:
    """Drive mouth open/close from TTS audio amplitude (0.0–1.0)."""
    mouth_val = min(1.0, max(0.0, float(value))) * 0.6
    result = _tcp_call("set_morph_target", {
        "name":  "CTRL_expressions_mouthOpen",
        "value": mouth_val,
    })
    if not result["ok"]:
        result = _mcp_call("set_morph_target", {
            "name":  "CTRL_expressions_mouthOpen",
            "value": mouth_val,
        })
    return result


def _trigger_animation(sequence_name: str, actor_name: str = "BP_JarvisMetaHuman") -> Dict[str, Any]:
    return _tcp_call("play_animation", {
        "actor": actor_name,
        "sequence": sequence_name,
    })


# ── Status result helper ──────────────────────────────────────────────────────

def _status(title: str, msg: str, ok: bool, data: dict = None) -> dict:
    return {
        "ok": ok,
        "speech": {"text": msg, "priority": "normal"},
        "ui": {
            "placement": "right-side-hud",
            "format":    "status",
            "title":     title,
            "summary":   msg,
            "ttl_seconds": 60,
        },
        "data": data or {"plain": msg},
    }


# ── Main executor ─────────────────────────────────────────────────────────────

def exec_unreal(
    action:        str,
    actor_type:    str  = "",
    actor_name:    str  = "",
    location:      list = None,
    rotation:      list = None,
    scale:         list = None,
    material_path: str  = "",
    slot:          int  = 0,
    morph_name:    str  = "",
    morph_value:   float = 0.0,
    emotion:       str  = "",
    amplitude:     float = 0.0,
    sequence:      str  = "",
    test_name:     str  = "",
    command:       str  = "",
    params:        dict = None,
) -> Dict[str, Any]:

    action = (action or "").strip().lower()

    # ── Editor info ───────────────────────────────────────────────────────────
    if action == "status":
        r = _get_editor_state()
        tools = _mcp_list_tools()
        msg = "UE MCP connected." if r["ok"] else f"UE MCP not reachable: {r.get('error','')}"
        return _status("Unreal MCP", msg, r["ok"], {
            "editor":    r.get("result"),
            "tools":     tools.get("tools", []),
            "http_url":  UE_MCP_HTTP_URL,
            "tcp_port":  UE_TCP_PORT,
        })

    if action == "list_tools":
        r = _mcp_list_tools()
        names = r.get("tools", [])
        return _status("UE Tools", f"{len(names)} tools available", r["ok"], {"tools": names})

    # ── Actor control ─────────────────────────────────────────────────────────
    if action == "spawn_actor":
        if not actor_type:
            return _status("Spawn Actor", "actor_type required", False)
        r = _spawn_actor(actor_type, actor_name, location, rotation, scale)
        return _status("Spawn Actor",
                       f"Spawned {actor_type}" if r["ok"] else r.get("error", "Failed"),
                       r["ok"], r)

    if action == "set_transform":
        if not actor_name:
            return _status("Set Transform", "actor_name required", False)
        r = _set_transform(actor_name, location, rotation, scale)
        return _status("Set Transform",
                       f"Moved {actor_name}" if r["ok"] else r.get("error", "Failed"),
                       r["ok"], r)

    if action == "get_actors":
        r = _get_actors(actor_type)
        actors = r.get("result", {})
        return _status("Get Actors", "Actors fetched" if r["ok"] else r.get("error", "Failed"),
                       r["ok"], {"actors": actors})

    if action == "delete_actor":
        if not actor_name:
            return _status("Delete Actor", "actor_name required", False)
        r = _mcp_call("delete_actor", {"name": actor_name})
        return _status("Delete Actor",
                       f"Deleted {actor_name}" if r["ok"] else r.get("error", "Failed"),
                       r["ok"], r)

    # ── Lighting ──────────────────────────────────────────────────────────────
    if action == "set_lighting":
        args = {}
        if actor_name:    args["name"]       = actor_name
        if location:      args["location"]   = location
        if morph_value:   args["intensity"]  = morph_value
        if material_path: args["color"]      = material_path  # hex color via material_path param
        r = _mcp_call("set_light_properties", args)
        return _status("Set Lighting",
                       "Lighting updated" if r["ok"] else r.get("error", "Failed"),
                       r["ok"], r)

    # ── Materials ─────────────────────────────────────────────────────────────
    if action == "set_material":
        if not actor_name or not material_path:
            return _status("Set Material", "actor_name and material_path required", False)
        r = _set_material(actor_name, material_path, slot)
        return _status("Set Material",
                       f"Material set on {actor_name}" if r["ok"] else r.get("error", "Failed"),
                       r["ok"], r)

    # ── MetaHuman / Jarvis face ───────────────────────────────────────────────
    if action == "set_emotion":
        if not emotion:
            return _status("Set Emotion", "emotion required (neutral/happy/thinking/focused/concerned/surprised)", False)
        r = _set_emotion(emotion)
        return _status("MetaHuman Emotion",
                       f"Emotion: {emotion}" if r["ok"] else "Partial — some morphs failed",
                       r["ok"], r)

    if action == "set_morph":
        if not morph_name:
            return _status("Set Morph", "morph_name required", False)
        r = _set_morph_target(morph_name, morph_value)
        return _status("Morph Target",
                       f"{morph_name} = {morph_value}" if r["ok"] else r.get("error", "Failed"),
                       r["ok"], r)

    if action == "set_amplitude":
        r = _set_amplitude(amplitude)
        return _status("Amplitude",
                       f"Mouth = {amplitude:.2f}" if r["ok"] else r.get("error", "Failed"),
                       r["ok"], r)

    if action == "play_animation":
        if not sequence:
            return _status("Play Animation", "sequence required", False)
        r = _trigger_animation(sequence, actor_name or "BP_JarvisMetaHuman")
        return _status("Play Animation",
                       f"Playing {sequence}" if r["ok"] else r.get("error", "Failed"),
                       r["ok"], r)

    # ── Automation tests ──────────────────────────────────────────────────────
    if action == "run_test":
        if not test_name:
            return _status("Run Test", "test_name required", False)
        r = _run_automation_test(test_name)
        return _status("Automation Test",
                       f"Test {test_name}: {'PASS' if r['ok'] else 'FAIL'}",
                       r["ok"], r)

    # ── Raw passthrough ───────────────────────────────────────────────────────
    if action == "mcp_call":
        if not command:
            return _status("MCP Call", "command (tool name) required", False)
        r = _mcp_call(command, params or {})
        return _status("MCP Raw", f"{command}: {'OK' if r['ok'] else r.get('error','')}",
                       r["ok"], r)

    if action == "tcp_call":
        if not command:
            return _status("TCP Call", "command required", False)
        r = _tcp_call(command, params or {})
        return _status("TCP Raw", f"{command}: {'OK' if r['ok'] else r.get('error','')}",
                       r["ok"], r)

    return _status(
        "Unreal",
        "Unknown action. Use: status, list_tools, spawn_actor, set_transform, get_actors, "
        "delete_actor, set_lighting, set_material, set_emotion, set_morph, set_amplitude, "
        "play_animation, run_test, mcp_call, tcp_call",
        False,
    )


# ── Tool definition ───────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "unreal",
            "description": (
                "Control Unreal Engine 5.8 via MCP. "
                "Actor control: spawn_actor, set_transform, get_actors, delete_actor. "
                "Scene: set_lighting, set_material. "
                "MetaHuman face: set_emotion (neutral/happy/thinking/focused/concerned/surprised), "
                "set_morph (individual morph target), set_amplitude (TTS mouth sync), play_animation. "
                "Editor: status, list_tools, run_test. "
                "Raw: mcp_call, tcp_call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "status", "list_tools",
                            "spawn_actor", "set_transform", "get_actors", "delete_actor",
                            "set_lighting", "set_material",
                            "set_emotion", "set_morph", "set_amplitude", "play_animation",
                            "run_test",
                            "mcp_call", "tcp_call",
                        ],
                    },
                    "actor_type":    {"type": "string", "description": "UE actor class, e.g. PointLight, StaticMeshActor, DirectionalLight"},
                    "actor_name":    {"type": "string", "description": "Actor name or label in the level"},
                    "location":      {"type": "array",  "items": {"type": "number"}, "description": "[X, Y, Z] in cm"},
                    "rotation":      {"type": "array",  "items": {"type": "number"}, "description": "[Pitch, Yaw, Roll] in degrees"},
                    "scale":         {"type": "array",  "items": {"type": "number"}, "description": "[X, Y, Z] scale"},
                    "material_path": {"type": "string", "description": "UE material asset path, e.g. /Game/Materials/M_Glow"},
                    "slot":          {"type": "integer","description": "Material slot index (default 0)"},
                    "morph_name":    {"type": "string", "description": "MetaHuman CTRL morph target name"},
                    "morph_value":   {"type": "number", "description": "Morph target value 0.0–1.0"},
                    "emotion":       {"type": "string", "enum": ["neutral","happy","thinking","focused","concerned","surprised"],
                                     "description": "Jarvis MetaHuman emotion preset"},
                    "amplitude":     {"type": "number", "description": "TTS audio amplitude 0.0–1.0 for mouth sync"},
                    "sequence":      {"type": "string", "description": "Animation sequence asset name"},
                    "test_name":     {"type": "string", "description": "Unreal automation test name"},
                    "command":       {"type": "string", "description": "Raw MCP tool name or TCP command"},
                    "params":        {"type": "object", "description": "Raw params for mcp_call or tcp_call"},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {"unreal": exec_unreal}

KEYWORDS = {
    "unreal": [
        "unreal", "ue5", "actor", "spawn", "metahuman", "morph target",
        "blueprint", "lighting", "scene", "level", "animation", "emotion face",
    ],
}

SKILL_EXAMPLES = [
    {"command": "check unreal connection",       "tool": "unreal", "args": {"action": "status"}},
    {"command": "set jarvis emotion to happy",   "tool": "unreal", "args": {"action": "set_emotion", "emotion": "happy"}},
    {"command": "spawn a point light at 0 0 300","tool": "unreal", "args": {"action": "spawn_actor", "actor_type": "PointLight", "location": [0,0,300]}},
    {"command": "list actors in level",          "tool": "unreal", "args": {"action": "get_actors"}},
    {"command": "play idle animation",           "tool": "unreal", "args": {"action": "play_animation", "sequence": "AS_Jarvis_Idle"}},
]
