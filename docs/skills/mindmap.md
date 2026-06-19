# Mindmap Skill

Generate structured mind maps from topics or notes.

**File:** `skills/mindmap.py`

---

## Tools

### mindmap

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic` | string | yes | Central topic or concept |
| `depth` | integer | no | Tree depth (default 3) |
| `format` | string | no | `markdown`, `mermaid`, `text` (default: markdown) |
| `context` | string | no | Additional context or constraints |

**Examples:**
```
"Create a mindmap for DRAVN architecture"
"Mindmap of StockWatch features"
"Generate a mermaid mindmap for the plan system"
```

Output is displayed in the HUD and can be saved as a vault note.
