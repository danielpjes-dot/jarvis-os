# Chat Log Skill

Read and search JARVIS conversation history.

**File:** `skills/chat_log.py`

---

## Tools

### chat_log

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `recent`, `search`, `today`, `export` |
| `query` | string | no | Search term |
| `limit` | integer | no | Number of messages to return (default 20) |
| `date` | string | no | Date filter, e.g. `2026-06-18` |

**Examples:**
```
"Show recent conversation"
"Search chat for StockWatch"
"What did I ask today"
"Export conversation to vault"
```

Logs are stored in `data/chat_log/` (gitignored).
