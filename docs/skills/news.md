# News Skill

Live news headlines via RSS feeds and newsapi.

**File:** `skills/news.py`

---

## Tools

### get_news

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `top`, `search` |
| `topic` | string | no | Topic to search for, e.g. `AI`, `NVIDIA`, `Ukraine` |
| `location` | string | no | Location filter, e.g. `Estonia`, `Helsinki` |
| `limit` | integer | no | Max headlines to return (default 6) |

**Examples:**
```
"Top news"
"Latest AI news"
"News about NVIDIA"
"What's happening in Estonia"
"Tech headlines today"
```
