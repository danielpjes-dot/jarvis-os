# Notes Skill

Quick note creation and management in the Obsidian vault.

**File:** `skills/notes.py`  
**Vault:** `D:/Jarvis_vault` (see also [vault.md](vault.md))

---

## Tools

### notes

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `create`, `append`, `daily`, `search`, `tag`, `list`, `link`, `todo` |
| `path` | string | no | Path relative to vault, e.g. `Projects/MyProject/overview.md` |
| `content` | string | no | Note body, appended text, or todo text |
| `tags` | string | no | Comma-separated tags, e.g. `project,active` |
| `query` | string | no | Search term for `search` action |

**Actions:**

| Action | Description |
|--------|-------------|
| `create` | Create a new note at `path` with `content` |
| `append` | Append `content` to existing note |
| `daily` | Append to today's daily note (`Daily/YYYY-MM-DD.md`) |
| `search` | Full-text search across vault |
| `tag` | Find notes with specific tag |
| `list` | List notes in a folder |
| `link` | Add a wikilink to a note |
| `todo` | Append a `- [ ] item` to daily note |

**Examples:**
```
"Note: StockWatch — decided to use Nile instead of Supabase"
"Add to daily note: reviewed Caskra API design"
"Search notes for DRAVN architecture"
"List notes in Projects/TenderApp"
"Todo: review n8n webhook flow"
```
