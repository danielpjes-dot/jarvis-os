# SMS Skill

Send and receive SMS text messages via Twilio.

**File:** `skills/sms.py`  
**Config:** `config/twilio.json` (gitignored — shared with Phone skill)

---

## Tools

### sms

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `send`, `recent`, `inbox`, `status` |
| `number` | string | no | Phone number in E.164 format, e.g. `+358401234567` |
| `message` | string | no | SMS text to send |

**Examples:**
```
"Send SMS to +358401234567 I'm on my way"
"Show recent texts"
"SMS inbox"
"SMS status"
```

---

## Config (`config/twilio.json`)

See [phone.md](phone.md) — same config file used by both skills.

Incoming SMS is handled via Twilio webhook → `scripts/twilio_webhook.py`.
