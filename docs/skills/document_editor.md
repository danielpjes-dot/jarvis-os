# Document Editor Skill

Edit, reformat, and structure documents in the vault or staging area.

**File:** `skills/document_editor.py`

---

## Tools

### edit_document

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `edit`, `reformat`, `summarize`, `translate`, `proofread` |
| `path` | string | no | File path (relative to vault or absolute) |
| `content` | string | no | Document text to process |
| `instruction` | string | no | Specific editing instruction |
| `language` | string | no | Target language for `translate` |

**Examples:**
```
"Proofread Projects/TenderApp/overview.md"
"Reformat my meeting notes in Projects/Caskra/decisions.md"
"Translate this document to Finnish"
"Summarize People/sami.md"
```
