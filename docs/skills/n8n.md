# n8n Skill

Bidirectional n8n workflow automation integration.

**File:** `skills/n8n.py`  
**Config:** `infra/.env.n8n.local` (gitignored — copy from `infra/.env.n8n`)

---

## Tools

### n8n

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | See actions below |
| `workflow_id` | string | no | n8n workflow ID |
| `execution_id` | string | no | n8n execution ID |
| `webhook_path` | string | no | Webhook path, e.g. `/webhook/invoice` |
| `payload` | object | no | JSON payload sent to webhook |
| `active` | boolean | no | Filter workflows by active state |
| `status` | string | no | Filter executions by status |
| `limit` | integer | no | Max results (default 20) |

**Actions:**

| Action | Description |
|--------|-------------|
| `health` | Check if n8n is reachable |
| `list_workflows` | List all workflows |
| `get_workflow` | Get workflow details |
| `run_webhook` | Trigger a webhook-based workflow |
| `list_executions` | List recent executions |
| `get_execution` | Get execution details |
| `add_task` / `create_task` | Send a task to n8n, n8n calls back `/api/events` when done |
| `send_event` | Push a Jarvis event to n8n |

---

## Bidirectional Flow

**Jarvis → n8n:**
```
"add task to n8n: research competitor pricing"
→ POST N8N_TASK_WEBHOOK { task, callback_url: /api/events }
→ n8n workflow runs
→ n8n POSTs result back to Jarvis /api/events
```

**n8n → Jarvis:**
```
POST http://jarvis:7900/api/events
{ "type": "workflow_done", "task": "...", "data": {...} }
→ Logged as system event
→ If task field present → queued to plan_runner via Redis
```

---

## Config (`infra/.env.n8n.local`)

```bash
N8N_TASK_WEBHOOK=/webhook/jarvis-task
N8N_EVENT_WEBHOOK=/webhook/jarvis-event
JARVIS_API_URL=http://<wsl-ip>:7900
N8N_USER=jarvis
N8N_PASSWORD=strong-password
N8N_WEBHOOK_URL=http://localhost:5678
```

---

## Examples

```
"Check n8n health"
"List n8n workflows"
"Add task to n8n: generate monthly expense report"
"Trigger invoice processing workflow with company Poro-IT"
"Show last 5 n8n executions"
```

---

## Infrastructure

n8n runs in Podman: `podman-compose -f infra/podman-compose.n8n.yml up -d`
