# Dictate Skill

Continuous dictation mode — transcribe speech to a file in real time.

**File:** `skills/dictate.py`

---

## Tools

### dictate

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `start`, `stop`, `status` |
| `output` | string | no | Output file path (default: `data/dictation/YYYY-MM-DD.md`) |
| `append` | boolean | no | Append to existing file instead of overwriting (default: true) |

**Examples:**
```
"Start dictation"
"Stop dictation"
"Start dictating to Projects/Caskra/notes.md"
"Dictation status"
```

While active, all Whisper transcriptions are appended to the output file. Normal command processing is paused until `stop` is called.
