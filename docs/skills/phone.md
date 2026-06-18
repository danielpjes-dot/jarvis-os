# Phone Skill

Make phone calls and check call history via Twilio.

**File:** `skills/phone.py`  
**Config:** `config/twilio.json` (gitignored)

---

## Tools

### phone

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `call`, `recent`, `voicemail`, `messages`, `status` |
| `number` | string | no | Phone number in E.164 format, e.g. `+358401234567` |
| `message` | string | no | Optional spoken message for outbound calls (TTS) |

**Examples:**
```
"Call +358401234567"
"Call Sami and say I'll be late"
"Show recent calls"
"Check voicemail"
"Phone status"
```

---

## Config (`config/twilio.json`)

```json
{
  "account_sid": "ACxxxxxxxx",
  "auth_token": "your-auth-token",
  "from_number": "+1234567890",
  "twiml_voice": "Polly.Matthew"
}
```

Outbound calls use Twilio TTS with the configured voice. JARVIS dials the number and speaks the `message` when answered.
