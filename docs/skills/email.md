# Email Skill

Send, read, and search email via SMTP/IMAP.

**File:** `skills/email.py`  
**Config:** `config/email.json` (gitignored — use `config/email.json.example` as template)

---

## Tools

### email

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `send`, `inbox`, `read`, `search`, `status` |
| `to` | string | no | Recipient email address (for `send`) |
| `subject` | string | no | Email subject (for `send`) |
| `body` | string | no | Email body text (for `send`) |
| `query` | string | no | Search query (for `search`) |

**Examples:**
```
"Send email to john@example.com subject Meeting body I'll be 5 minutes late"
"Check inbox"
"Search email for invoice"
"Read latest email"
"Email status"
```

---

## Config (`config/email.json`)

```json
{
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "imap_host": "imap.gmail.com",
  "imap_port": 993,
  "username": "you@gmail.com",
  "password": "your-app-password",
  "from_name": "JARVIS"
}
```

For Gmail, use an **App Password** (Google Account → Security → 2-Step Verification → App passwords).
