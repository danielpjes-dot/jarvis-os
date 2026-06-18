# Weather Skill

Current weather and multi-day forecasts.

**File:** `skills/weather.py`  
**API:** Open-Meteo (no key required)

---

## Tools

### weather

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `current`, `forecast`, `hourly` |
| `location` | string | yes | City or region, e.g. `Tallinn`, `Helsinki`, `London` |
| `days` | integer | no | Days for forecast/hourly (default 5) |

**Examples:**
```
"Weather in Tallinn"
"5-day forecast for Helsinki"
"Hourly weather today in Tallinn"
"Is it going to rain tomorrow in London"
```
