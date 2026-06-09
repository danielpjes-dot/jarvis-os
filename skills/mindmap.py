"""
JARVIS Skill — Mind map generator.

Builds a mind map from a topic using:
  - Web search (web.py) for live research
  - Redis memory (memory.py) for context from agent state + working memory
  - LLM to structure nodes
  - Outputs interactive HTML file + opens in browser
  - Saves map summary to Redis working memory
"""

import json
import subprocess
import tempfile
import os
from datetime import datetime
from pathlib import Path

SKILL_NAME = "mindmap"
SKILL_DESCRIPTION = "Generate an interactive mind map from a topic — uses web search + agent memory, saves HTML, opens in browser"

# Output directory — saves maps here
MINDMAP_DIR = Path(__file__).parent.parent / "output" / "mindmaps"


# -- Helpers --

def _web_search(query: str) -> str:
    """Call web skill search directly."""
    try:
        from ddgs import DDGS
        results = DDGS().text(query, max_results=6)
        if not results:
            return ""
        return "\n".join(f"- {r.get('title', '')}: {r.get('body', '')}" for r in results)[:3000]
    except Exception as e:
        return f"(search unavailable: {e})"


def _read_agent_context() -> str:
    """Pull relevant context from Redis memory skill."""
    try:
        from skills.memory import read_agent_state, read_working_memory, get_current_task
        state = read_agent_state()
        wm = read_working_memory()
        task = get_current_task()
        lines = []
        if state.get("identity"):
            lines.append(f"Agent identity: {state['identity']}")
        if task and task != "none":
            lines.append(f"Current task: {task}")
        if wm:
            lines.append("Recent context:\n" + "\n".join(f"  - {m}" for m in wm[-5:]))
        return "\n".join(lines) if lines else ""
    except Exception:
        return ""


def _push_to_memory(summary: str):
    """Log mind map creation to working memory."""
    try:
        from skills.memory import push_working_memory
        push_working_memory(f"[mindmap] {summary}")
    except Exception:
        pass


def _build_nodes_with_llm(topic: str, search_results: str, agent_context: str) -> dict:
    """Ask Ollama to structure the mind map as JSON."""
    try:
        import urllib.request

        context_block = ""
        if agent_context:
            context_block = f"\nAgent context:\n{agent_context}\n"
        if search_results:
            context_block += f"\nSearch results:\n{search_results}\n"

        prompt = f"""You are building a mind map for the topic: "{topic}"
{context_block}
Return ONLY valid JSON in this exact structure, no markdown, no explanation:
{{
  "center": "{topic}",
  "branches": [
    {{
      "label": "Branch Name",
      "color": "#hex",
      "children": ["child 1", "child 2", "child 3"]
    }}
  ]
}}

Rules:
- 4 to 6 branches
- 2 to 4 children per branch
- Colors should be distinct and vivid
- Be specific and informative using the search results
- Keep labels concise (max 5 words)"""

        payload = json.dumps({
            "model": "mistral",
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.4}
        }).encode()

        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            raw = data.get("response", "").strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
    except Exception as e:
        # Fallback structure if LLM fails
        return {
            "center": topic,
            "branches": [
                {"label": "Overview", "color": "#4A90D9", "children": ["Definition", "History", "Purpose"]},
                {"label": "Key Concepts", "color": "#7ED321", "children": ["Core idea 1", "Core idea 2", "Core idea 3"]},
                {"label": "Applications", "color": "#F5A623", "children": ["Use case 1", "Use case 2"]},
                {"label": "Resources", "color": "#D0021B", "children": ["Further reading", "Tools", "Communities"]},
            ]
        }


def _render_html(map_data: dict, topic: str) -> str:
    """Render mind map as a self-contained interactive HTML file."""
    branches_json = json.dumps(map_data["branches"])
    center = map_data["center"]
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Mind Map: {center}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0d0d0d; font-family: 'Segoe UI', sans-serif; overflow: hidden; }}
  canvas {{ display: block; }}
  #info {{ position: fixed; top: 12px; left: 12px; color: #666; font-size: 12px; }}
  #title {{ position: fixed; top: 12px; left: 50%; transform: translateX(-50%);
            color: #fff; font-size: 18px; font-weight: 600; letter-spacing: 1px; }}
  #controls {{ position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
               display: flex; gap: 8px; }}
  button {{ background: #1e1e1e; color: #ccc; border: 1px solid #333; padding: 6px 14px;
            border-radius: 6px; cursor: pointer; font-size: 13px; }}
  button:hover {{ background: #2a2a2a; color: #fff; }}
</style>
</head>
<body>
<div id="title">{center}</div>
<div id="info">Generated {generated} · JARVIS OS</div>
<div id="controls">
  <button onclick="resetView()">Reset</button>
  <button onclick="exportPNG()">Save PNG</button>
</div>
<canvas id="c"></canvas>
<script>
const branches = {branches_json};
const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');

let W, H, cx, cy;
let scale = 1, offsetX = 0, offsetY = 0;
let dragging = false, lastX, lastY;

function resize() {{
  W = canvas.width = window.innerWidth;
  H = canvas.height = window.innerHeight;
  cx = W / 2; cy = H / 2;
  draw();
}}

function worldToScreen(x, y) {{
  return [(x + offsetX) * scale + W/2, (y + offsetY) * scale + H/2];
}}

function drawRoundedRect(x, y, w, h, r, fill, stroke) {{
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
  if (fill) {{ ctx.fillStyle = fill; ctx.fill(); }}
  if (stroke) {{ ctx.strokeStyle = stroke; ctx.lineWidth = 1.5; ctx.stroke(); }}
}}

function drawLabel(text, x, y, color, size, bold) {{
  ctx.font = (bold ? 'bold ' : '') + size + 'px Segoe UI';
  ctx.fillStyle = color;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, x, y);
}}

function draw() {{
  ctx.clearRect(0, 0, W, H);

  // Grid dots
  ctx.fillStyle = '#1a1a1a';
  for (let gx = 0; gx < W; gx += 40) {{
    for (let gy = 0; gy < H; gy += 40) {{
      ctx.beginPath();
      ctx.arc(gx, gy, 1, 0, Math.PI * 2);
      ctx.fill();
    }}
  }}

  const n = branches.length;
  const branchR = Math.min(W, H) * 0.28;
  const childR = Math.min(W, H) * 0.42;

  branches.forEach((branch, i) => {{
    const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
    const [bx, by] = worldToScreen(
      Math.cos(angle) * branchR,
      Math.sin(angle) * branchR
    );
    const [ox, oy] = worldToScreen(0, 0);

    // Line: center → branch
    ctx.beginPath();
    ctx.moveTo(ox, oy);
    ctx.lineTo(bx, by);
    ctx.strokeStyle = branch.color + '88';
    ctx.lineWidth = 2 * scale;
    ctx.stroke();

    // Branch node
    const bw = Math.max(100, branch.label.length * 9) * scale;
    const bh = 32 * scale;
    drawRoundedRect(bx - bw/2, by - bh/2, bw, bh, 8 * scale, branch.color + 'cc', branch.color);
    drawLabel(branch.label, bx, by, '#fff', 13 * scale, true);

    // Children
    const nc = branch.children.length;
    branch.children.forEach((child, j) => {{
      const spreadAngle = 0.55;
      const childAngle = angle - spreadAngle * (nc - 1) / 2 + j * spreadAngle;
      const [ccx, ccy] = worldToScreen(
        Math.cos(childAngle) * childR,
        Math.sin(childAngle) * childR
      );

      // Line: branch → child
      ctx.beginPath();
      ctx.moveTo(bx, by);
      ctx.lineTo(ccx, ccy);
      ctx.strokeStyle = branch.color + '55';
      ctx.lineWidth = 1.2 * scale;
      ctx.stroke();

      // Child node
      const cw = Math.max(80, child.length * 8) * scale;
      const ch = 26 * scale;
      drawRoundedRect(ccx - cw/2, ccy - ch/2, cw, ch, 6 * scale, '#1e1e1e', branch.color + '99');
      drawLabel(child, ccx, ccy, '#ddd', 11 * scale, false);
    }});
  }});

  // Center node
  const [ox, oy] = worldToScreen(0, 0);
  const cr = 54 * scale;
  ctx.beginPath();
  ctx.arc(ox, oy, cr, 0, Math.PI * 2);
  ctx.fillStyle = '#ffffff18';
  ctx.fill();
  ctx.strokeStyle = '#ffffff55';
  ctx.lineWidth = 2;
  ctx.stroke();
  drawLabel('{center}', ox, oy, '#fff', 15 * scale, true);
}}

// Pan
canvas.addEventListener('mousedown', e => {{ dragging = true; lastX = e.clientX; lastY = e.clientY; }});
canvas.addEventListener('mouseup', () => dragging = false);
canvas.addEventListener('mousemove', e => {{
  if (!dragging) return;
  offsetX += (e.clientX - lastX) / scale;
  offsetY += (e.clientY - lastY) / scale;
  lastX = e.clientX; lastY = e.clientY;
  draw();
}});

// Zoom
canvas.addEventListener('wheel', e => {{
  e.preventDefault();
  scale *= e.deltaY < 0 ? 1.1 : 0.9;
  scale = Math.max(0.3, Math.min(3, scale));
  draw();
}}, {{ passive: false }});

function resetView() {{ scale = 1; offsetX = 0; offsetY = 0; draw(); }}

function exportPNG() {{
  const link = document.createElement('a');
  link.download = 'mindmap-{topic.replace(" ", "_")}.png';
  link.href = canvas.toDataURL();
  link.click();
}}

window.addEventListener('resize', resize);
resize();
</script>
</body>
</html>"""


# -- Tool executor --

def exec_mindmap(topic: str) -> str:
    """Generate a mind map for the given topic."""
    if not topic or not topic.strip():
        return "Please provide a topic for the mind map."

    topic = topic.strip()

    # 1. Pull agent context from Redis
    agent_context = _read_agent_context()

    # 2. Web search for live data
    search_results = _web_search(topic)

    # 3. Build nodes via LLM
    map_data = _build_nodes_with_llm(topic, search_results, agent_context)

    # 4. Render HTML
    html = _render_html(map_data, topic)

    # 5. Save to file
    MINDMAP_DIR.mkdir(parents=True, exist_ok=True)
    slug = topic.lower().replace(" ", "_")[:40]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = MINDMAP_DIR / f"mindmap_{slug}_{timestamp}.html"
    filename.write_text(html, encoding="utf-8")

    # 6. Open in browser
    try:
        subprocess.Popen(
            ["powershell.exe", "-Command", f"Start-Process '{filename}'"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass

    # 7. Log to Redis working memory
    branch_labels = [b["label"] for b in map_data.get("branches", [])]
    summary = f"Mind map '{topic}' — branches: {', '.join(branch_labels)}"
    _push_to_memory(summary)

    return f"Mind map generated: {topic}\nBranches: {', '.join(branch_labels)}\nSaved: {filename}"


# -- Tool definitions --

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "mindmap",
            "description": "Generate an interactive mind map for any topic. Uses web search for current info and agent memory for context. Opens in browser as a pannable/zoomable HTML canvas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The topic or concept to map, e.g. 'Redis memory architecture' or 'Jun kombucha fermentation'",
                    }
                },
                "required": ["topic"],
            },
        },
    },
]

TOOL_MAP = {
    "mindmap": lambda args: exec_mindmap(args["topic"]),
}

KEYWORDS = {
    "mindmap": ["mind map", "mindmap", "map out", "visualize", "diagram", "brainstorm", "map idea", "concept map"],
}
