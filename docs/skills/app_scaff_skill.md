# App Scaffold Skill

Scaffold new projects from templates in one command.

**File:** `skills/app_scaff_skill.py`

---

## Tools

### scaffold_app

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `template` | string | yes | `nextjs`, `react`, `python-api`, `flask`, `express`, `static` |
| `name` | string | yes | Project name (used as directory name) |
| `path` | string | no | Parent directory (default: `E:/coding/`) |
| `features` | string | no | Comma-separated features, e.g. `tailwind,auth,prisma` |

**Templates:**

| Template | Stack |
|----------|-------|
| `nextjs` | Next.js 15 + TypeScript + Tailwind |
| `react` | React + Vite + TypeScript |
| `python-api` | FastAPI + Pydantic |
| `flask` | Flask + SQLAlchemy |
| `express` | Express.js + TypeScript |
| `static` | Plain HTML/CSS/JS |

**Examples:**
```
"Scaffold a nextjs project called InvoiceBot"
"Create a flask API called budget-tracker at E:/coding"
"New static site called lottery-app with tailwind"
```

After scaffolding, the project is registered as a vault note in `Projects/` and set as the active project context.
