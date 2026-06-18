# Memory Core Skill

Fast in-session working memory backed by Redis.

**File:** `skills/memory_core.py`

For long-term persistent memory see [memory.md](memory.md) (MemPalace vector store).

---

## Tools

### remember

Store a fact in working memory:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `key` | string | yes | Memory key |
| `value` | string | yes | Value to store |
| `ttl` | integer | no | Expiry in seconds (default: session lifetime) |

### recall

Retrieve a stored fact:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `key` | string | yes | Memory key to retrieve |

---

## Examples

```
"Remember that the StockWatch staging URL is staging.bullishbeat.com"
"Recall the StockWatch staging URL"
"Remember my Poro-IT VAT number is EE123456789"
```

Working memory survives for the session duration (Redis TTL). For permanent storage across sessions, use the `memory` skill (MemPalace) or `notes` skill (Obsidian vault).
