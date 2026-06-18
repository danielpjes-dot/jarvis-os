# Project Ops Skill

Project management operations — create, list, archive, and track active projects.

**File:** `skills/project_ops.py`

---

## Tools

### project_ops

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `create`, `list`, `archive`, `status`, `switch` |
| `name` | string | no | Project name |
| `description` | string | no | Project description |
| `template` | string | no | Vault template to use (e.g. `project`) |

**Examples:**
```
"Create project InvoiceBot"
"List active projects"
"Archive project OldTool"
"Project status for StockWatch"
"Switch to project Caskra"
```

Projects are tracked as vault notes in `Projects/` with frontmatter (`status`, `created`, `tags`). Switching context sets the active project in Redis so other skills know which project to target.
