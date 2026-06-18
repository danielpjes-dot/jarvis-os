# Podman Skill

Run code and tests inside isolated Podman containers. Used by the plan system for complex project testing.

**File:** `skills/podman.py`

---

## Tools

### podman

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `test`, `run`, `shell` |
| `path` | string | no | Workspace directory (default: current) |
| `image` | string | no | Override auto-detected image, e.g. `python:3.11-slim` |
| `command` | string | no | Override auto-detected run command |
| `timeout` | integer | no | Max seconds before container is killed (default 120) |
| `network` | boolean | no | Allow network access inside container (default: false) |

**Auto-Detection:**

| Project Type | Image | Command |
|-------------|-------|---------|
| Node.js (`package.json`) | `node:20-alpine` | `npm test` or `node index.js` |
| Python (`requirements.txt`) | `python:3.11-slim` | `pytest` or `python main.py` |
| Python (`Dockerfile`) | From Dockerfile | `docker-compose up` |

**Examples:**
```
"Test staging/dev/PLAN-20260619-001 in a container"
"Run the lottery app in podman"
"Podman test for my Flask app"
```

The plan system automatically uses Podman for complex projects (>8 files or has `package.json`/`requirements.txt`/`Dockerfile`). Simple static sites use [Playwright](https://playwright.dev/) instead.
