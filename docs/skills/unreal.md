# Unreal Engine Skill

Control Unreal Engine 5.8 via the built-in MCP plugin — spawn actors, drive MetaHuman expressions, control lighting, trigger animations.

**File:** `skills/unreal.py`

---

## UE Side Setup

1. Open your UE 5.8 project
2. `Edit → Plugins` → search **Unreal MCP** → enable → restart editor
3. UE Output Log console: `ModelContextProtocol.GenerateClientConfig`
   - Check log for the actual port (default expected: 3000)
4. Add to Claude Code (optional): `claude mcp add unreal --transport http http://localhost:3000/mcp`

For custom MetaHuman tools (morph targets, emotion, amplitude) also enable the **unrealmcp TCP bridge** (port 55557) or add a `BP_JarvisMCPBridge` Blueprint actor that exposes `SetMorphTarget`, `SetEmotionState`, `SetAmplitude` to the MCP plugin.

---

## Tools

### unreal

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | See actions below |
| `actor_type` | string | no | UE actor class, e.g. `PointLight`, `StaticMeshActor` |
| `actor_name` | string | no | Actor label in the level |
| `location` | array | no | `[X, Y, Z]` in cm |
| `rotation` | array | no | `[Pitch, Yaw, Roll]` in degrees |
| `scale` | array | no | `[X, Y, Z]` |
| `material_path` | string | no | UE asset path, e.g. `/Game/Materials/M_Glow` |
| `slot` | integer | no | Material slot index (default 0) |
| `morph_name` | string | no | MetaHuman CTRL morph target name |
| `morph_value` | number | no | Morph value 0.0–1.0 |
| `emotion` | string | no | `neutral` / `happy` / `thinking` / `focused` / `concerned` / `surprised` |
| `amplitude` | number | no | TTS amplitude 0.0–1.0 for mouth sync |
| `sequence` | string | no | Animation sequence name |
| `test_name` | string | no | Unreal automation test name |
| `command` | string | no | Raw MCP tool or TCP command name |
| `params` | object | no | Raw params for `mcp_call` / `tcp_call` |

---

## Actions

### Editor

| Action | Description |
|--------|-------------|
| `status` | Check UE MCP connection + list available tools |
| `list_tools` | Fetch full tool manifest from UE MCP server |
| `run_test` | Run a UE automation test by name |

### Actors

| Action | Description |
|--------|-------------|
| `spawn_actor` | Spawn a new actor in the level |
| `set_transform` | Move/rotate/scale an existing actor |
| `get_actors` | List actors in the current level |
| `delete_actor` | Remove an actor by name |

### Scene

| Action | Description |
|--------|-------------|
| `set_lighting` | Set light intensity, color, position |
| `set_material` | Assign material to an actor slot |

### MetaHuman / Jarvis Face

| Action | Description |
|--------|-------------|
| `set_emotion` | Apply a named emotion preset (morph target batch) |
| `set_morph` | Set a single morph target by name and value |
| `set_amplitude` | Drive mouth open from TTS amplitude (0.0–1.0) |
| `play_animation` | Trigger a named animation sequence |

### Raw

| Action | Description |
|--------|-------------|
| `mcp_call` | Raw JSON-RPC tool call to UE HTTP MCP server |
| `tcp_call` | Raw JSON command to TCP bridge (port 55557) |

---

## Emotion Presets

| Emotion | Morphs |
|---------|--------|
| `neutral` | All zeroed |
| `happy` | mouthSmile, cheekSquint |
| `thinking` | browInnerUp, eyeLookUp |
| `focused` | browDown, eyeSquint |
| `concerned` | browInnerUp, mouthFrown |
| `surprised` | browOuterUp, eyeWide |

Custom emotions: add to `_EMOTION_MORPHS` dict in `skills/unreal.py`.

---

## Connection Architecture

```
react_server.py / agent loop
        │
        ▼
  skills/unreal.py
        │
        ├── HTTP JSON-RPC → localhost:3000/mcp   (UE 5.8 built-in MCP plugin)
        │   spawn_actor, set_transform, lighting, materials, automation tests
        │
        └── TCP JSON → localhost:55557           (unrealmcp / custom C++ bridge)
            MetaHuman morph targets, emotion, amplitude, custom Blueprint tools
```

Legacy `bridge/*.txt` files still written as fallback for systems still polling them.

---

## Examples

```
"Check unreal connection"
"Set Jarvis emotion to thinking"
"Spawn a point light at 0 0 500"
"Move BP_JarvisMetaHuman to 100 200 0"
"List actors in the level"
"Set morph CTRL_expressions_mouthSmile_L to 0.8"
"Play the idle animation on Jarvis"
"Run unreal automation test Project.Jarvis.Face"
```

---

## Config (`.env` in jarvis-os root)

```bash
UE_MCP_URL=http://localhost:3000/mcp   # Built-in UE 5.8 MCP HTTP server
UE_TCP_HOST=127.0.0.1                  # unrealmcp TCP bridge host
UE_TCP_PORT=55557                      # unrealmcp TCP bridge port
UE_BRIDGE_DIR=E:/coding/jarvis-os/bridge  # Legacy file bridge (fallback)
```
