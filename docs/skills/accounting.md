# Accounting Skill

Financial queries, invoice tracking, and basic bookkeeping.

**File:** `skills/accounting.py`

---

## Tools

### accounting

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `invoice`, `expenses`, `income`, `summary`, `vat` |
| `period` | string | no | Time period, e.g. `2026-Q1`, `2026-06`, `this month` |
| `amount` | number | no | Amount for calculations |
| `description` | string | no | Transaction description |
| `currency` | string | no | Currency code (default: EUR) |

**Examples:**
```
"Show expenses for this month"
"Create invoice for Varha 5000 EUR for May services"
"VAT summary for Q1 2026"
"Total income for 2025"
```

Data is stored in `data/accounting/` (gitignored).
