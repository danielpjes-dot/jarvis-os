# skills/accounting_missing_receipts.py

from __future__ import annotations

import os
import re
import json
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


RECEIPT_ROOT = Path(os.getenv("JARVIS_RECEIPT_ROOT", "/tmp/receipts"))
DEFAULT_WINDOW_DAYS = int(os.getenv("JARVIS_RECEIPT_SEARCH_WINDOW_DAYS", "14"))


@dataclass
class MissingReceipt:
    date: str
    company: str
    sum: Optional[str] = None
    currency: str = "EUR"
    source: str = ""
    status: str = "missing"
    found_files: List[str] = None
    notes: str = ""

    def __post_init__(self):
        if self.found_files is None:
            self.found_files = []


def skill_info() -> Dict[str, Any]:
    return {
        "name": "accounting_missing_receipts",
        "description": "Finds missing receipts/invoices from accounting emails, searches mailbox, saves attachments, and sends report.",
        "intent_aliases": [
            "find missing receipts",
            "accounting missing invoices",
            "search receipts for accounting",
            "send receipts to accountant",
        ],
        "args_schema": {
            "sender": "Accounting email address to read missing receipt requests from",
            "accounting_to": "Email address where report should be sent",
            "cc": "Optional CC address",
            "max_requests": "How many recent accounting request emails to process",
            "execute": "false=dry run, true=send email",
        },
    }


# ---------------------------------------------------------------------
# Main entry point called by Jarvis
# ---------------------------------------------------------------------

def exec_accounting_missing(
    sender: str,
    accounting_to: str = "",
    cc: str = "",
    max_requests: int = 1,
    execute: bool = False,
) -> dict:


    if not sender:
        return {"ok": False, "error": "Missing required arg: sender"}

    RECEIPT_ROOT.mkdir(parents=True, exist_ok=True)

    email = EmailSkillClient()

    request_emails = email.search_emails(
        query=f'from:{sender} newer_than:180d (invoice OR receipt OR kuitti OR lasku OR puuttuu OR missing)',
        max_results=max_requests,
    )

    all_missing: List[MissingReceipt] = []

    for msg in request_emails:
        full = email.read_email(msg["id"])
        extracted = extract_missing_receipts_from_email(full)

        for item in extracted:
            find_receipt_for_item(email, item)
            all_missing.append(item)

    report_md = create_report(all_missing)
    report_path = RECEIPT_ROOT / f"accounting_report_{datetime.now():%Y%m%d_%H%M%S}.md"
    report_path.write_text(report_md, encoding="utf-8")

    csv_path = RECEIPT_ROOT / f"accounting_report_{datetime.now():%Y%m%d_%H%M%S}.csv"
    csv_path.write_text(create_csv(all_missing), encoding="utf-8")

    attachments = [str(report_path), str(csv_path)]
    for item in all_missing:
        attachments.extend(item.found_files)

    result = {
        "ok": True,
        "execute": execute,
        "items": [asdict(x) for x in all_missing],
        "report": str(report_path),
        "csv": str(csv_path),
        "attachments": attachments,
    }

    if execute and accounting_to:
        email.send_email(
            to=accounting_to,
            cc=cc,
            subject=f"Missing receipts report {datetime.now():%Y-%m-%d}",
            body=report_md,
            attachments=attachments,
        )
        result["sent_to"] = accounting_to

    return result


# ---------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------

def extract_missing_receipts_from_email(email_obj: Dict[str, Any]) -> List[MissingReceipt]:
    text_parts = []

    body = email_obj.get("body") or email_obj.get("text") or ""
    text_parts.append(body)

    for att in email_obj.get("attachments", []):
        content_text = att.get("text")
        if content_text:
            text_parts.append(content_text)

    text = "\n".join(text_parts)
    return parse_missing_rows(text, source=email_obj.get("subject", ""))


def parse_missing_rows(text: str, source: str = "") -> List[MissingReceipt]:
    """
    Handles rows like:
    2026-05-10 Verkkokauppa.com 129.90
    10.5.2026 Bolt 18,40
    Missing receipt: Telia, 2026-04-03, 59.99 EUR
    """

    rows: List[MissingReceipt] = []

    date_patterns = [
        r"(?P<date>\d{4}-\d{2}-\d{2})",
        r"(?P<date>\d{1,2}\.\d{1,2}\.\d{4})",
        r"(?P<date>\d{1,2}/\d{1,2}/\d{4})",
    ]

    amount_pattern = r"(?P<sum>\d+[,.]\d{2})"

    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue

        date_match = None
        for pat in date_patterns:
            date_match = re.search(pat, raw)
            if date_match:
                break

        if not date_match:
            continue

        amount_match = re.search(amount_pattern, raw)
        date_norm = normalize_date(date_match.group("date"))

        # Remove date and amount from line, remaining text is likely company/hint.
        company = raw
        company = company.replace(date_match.group("date"), " ")
        if amount_match:
            company = company.replace(amount_match.group("sum"), " ")

        company = re.sub(r"\b(EUR|€|invoice|receipt|kuitti|lasku|missing|puuttuu)\b", " ", company, flags=re.I)
        company = re.sub(r"[^A-Za-zÅÄÖåäö0-9 .,&_-]+", " ", company)
        company = re.sub(r"\s+", " ", company).strip(" -,:;")

        if len(company) < 2:
            company = "UNKNOWN"

        rows.append(
            MissingReceipt(
                date=date_norm,
                company=company,
                sum=amount_match.group("sum").replace(",", ".") if amount_match else None,
                source=source,
            )
        )

    return dedupe_missing(rows)


def normalize_date(value: str) -> str:
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return value


def dedupe_missing(items: List[MissingReceipt]) -> List[MissingReceipt]:
    seen = set()
    out = []
    for x in items:
        key = (x.date, x.company.lower(), x.sum)
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


# ---------------------------------------------------------------------
# Search and save receipts
# ---------------------------------------------------------------------

def find_receipt_for_item(email: "EmailSkillClient", item: MissingReceipt) -> None:
    dt = datetime.strptime(item.date, "%Y-%m-%d")
    after = (dt - timedelta(days=DEFAULT_WINDOW_DAYS)).strftime("%Y/%m/%d")
    before = (dt + timedelta(days=DEFAULT_WINDOW_DAYS)).strftime("%Y/%m/%d")

    queries = build_email_queries(item, after, before)

    for query in queries:
        results = email.search_emails(query=query, max_results=10)

        for msg in results:
            full = email.read_email(msg["id"])
            saved = save_matching_attachments(email, full, item)

            if saved:
                item.status = "found"
                item.found_files.extend(saved)
                item.notes = f"Matched query: {query}"
                return

    item.status = "not_found"
    item.notes = "No matching attachment found"


def build_email_queries(item: MissingReceipt, after: str, before: str) -> List[str]:
    company = item.company.replace('"', "")
    terms = f'"{company}"'

    queries = [
        f'{terms} after:{after} before:{before} has:attachment',
        f'{terms} (invoice OR receipt OR kuitti OR lasku) after:{after} before:{before}',
    ]

    if item.sum:
        queries.insert(0, f'{terms} "{item.sum}" after:{after} before:{before}')

    return queries


def save_matching_attachments(email: "EmailSkillClient", msg: Dict[str, Any], item: MissingReceipt) -> List[str]:
    attachments = msg.get("attachments", [])
    if not attachments:
        return []

    safe_company = re.sub(r"[^A-Za-z0-9ÅÄÖåäö_-]+", "_", item.company).strip("_")
    target_dir = RECEIPT_ROOT / f"{item.date}_{safe_company}"
    target_dir.mkdir(parents=True, exist_ok=True)

    saved = []

    for att in attachments:
        filename = att.get("filename", "").lower()

        if not filename.endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic")):
            continue

        local_file = email.download_attachment(
            message_id=msg["id"],
            attachment_id=att.get("attachment_id"),
            filename=att.get("filename"),
            target_dir=str(target_dir),
        )

        if local_file:
            saved.append(local_file)

    return saved


# ---------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------

def create_report(items: List[MissingReceipt]) -> str:
    lines = [
        "# Missing receipts report",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M}",
        "",
        "| Date | Company | Sum | Status | Files | Notes |",
        "|---|---|---:|---|---|---|",
    ]

    for x in items:
        files = "<br>".join(Path(f).name for f in x.found_files) if x.found_files else ""
        lines.append(
            f"| {x.date} | {x.company} | {x.sum or ''} {x.currency} | {x.status} | {files} | {x.notes} |"
        )

    return "\n".join(lines)


def create_csv(items: List[MissingReceipt]) -> str:
    lines = ["date,company,sum,currency,status,files,notes"]
    for x in items:
        files = ";".join(x.found_files)
        lines.append(
            csv_escape([
                x.date,
                x.company,
                x.sum or "",
                x.currency,
                x.status,
                files,
                x.notes,
            ])
        )
    return "\n".join(lines)


def csv_escape(values: List[str]) -> str:
    out = []
    for v in values:
        v = str(v).replace('"', '""')
        out.append(f'"{v}"')
    return ",".join(out)


# ---------------------------------------------------------------------
# Adapter to your existing Jarvis email skill
# ---------------------------------------------------------------------
class EmailSkillClient:
    def search_emails(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        from skills.email import exec_email
        result = exec_email(
            action="search_structured",
            query=query,
            count=max_results,
        )
        return result if isinstance(result, list) else []

    def read_email(self, message_id: str) -> Dict[str, Any]:
        from skills.email import exec_email
        result = exec_email(
            action="read_structured",
            message_id=message_id,
        )
        return result if isinstance(result, dict) else {}

    def download_attachment(
        self,
        message_id: str,
        attachment_id: Optional[str],
        filename: Optional[str],
        target_dir: str,
    ) -> Optional[str]:
        from skills.email import exec_email
        return exec_email(
            action="download_attachment",
            message_id=message_id,
            attachment_id=attachment_id or "",
            filename=filename or "",
            target_dir=target_dir,
        )

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        attachments: List[str],
        cc: Optional[str] = None,
    ) -> Any:
        from skills.email import exec_email
        return exec_email(
            action="send_with_attachments",
            to=to,
            cc=cc or "",
            subject=subject,
            body=body,
            attachments=attachments,
        )
    
SKILL_NAME = "accounting_missing_receipts"
SKILL_DESCRIPTION = "Find missing receipts and invoices from email requests, search mailbox, save attachments, and send accounting report"
SKILL_VERSION = "1.0.0"
SKILL_AUTHOR = "Sami Porokka"
SKILL_CATEGORY = "accounting"
SKILL_TAGS = ["accounting", "receipts", "invoices", "email", "ocr", "attachments", "sqlite"]
SKILL_REQUIREMENTS = ["email"]
SKILL_CAPABILITIES = [
    "read_missing_receipt_request",
    "extract_invoice_rows",
    "search_matching_receipts",
    "save_attachments",
    "create_report",
    "send_accounting_email",
]

SKILL_META = {
    "name": SKILL_NAME,
    "description": SKILL_DESCRIPTION,
    "version": SKILL_VERSION,
    "author": SKILL_AUTHOR,
    "category": SKILL_CATEGORY,
    "tags": SKILL_TAGS,
    "requirements": SKILL_REQUIREMENTS,
    "capabilities": SKILL_CAPABILITIES,
    "writes_files": True,
    "reads_files": True,
    "network_access": True,
    "entrypoint": "exec_accounting_missing",
    "route": "tools",
    "intent_aliases": [
        "missing receipts",
        "missing invoices",
        "find receipts",
        "find invoices for accounting",
        "accounting receipts",
        "send receipts to accountant",
    ],
    "keywords": [
        "accounting",
        "receipt",
        "receipts",
        "invoice",
        "invoices",
        "missing receipt",
        "missing invoice",
        "kuitti",
        "lasku",
        "bookkeeping",
        "accountant",
    ],
    "direct_match": [
        "missing receipts",
        "find missing receipts",
        "accounting missing invoices",
        "send receipts to accountant",
    ],
    "response_style": {
        "default": "structured_accounting_report",
        "avoid_raw_dump": True,
        "followup_hint": True,
    },
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "accounting_missing_receipts",
            "description": "Find missing receipts/invoices from accounting emails, search matching emails, save attachments, and optionally send report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sender": {
                        "type": "string",
                        "description": "Accounting sender email address to read missing receipt requests from.",
                    },
                    "accounting_to": {
                        "type": "string",
                        "description": "Recipient address for final accounting report.",
                    },
                    "cc": {
                        "type": "string",
                        "description": "Optional CC address.",
                    },
                    "max_requests": {
                        "type": "integer",
                        "description": "How many recent accounting request emails to process. Default 1.",
                    },
                    "execute": {
                        "type": "boolean",
                        "description": "False for dry run, true to send final email.",
                    },
                },
                "required": ["sender"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "accounting_missing_receipts": exec_accounting_missing,
}

KEYWORDS = {
    "accounting_missing_receipts": [
        "accounting",
        "receipt",
        "receipts",
        "invoice",
        "invoices",
        "missing receipt",
        "missing invoice",
        "kuitti",
        "lasku",
        "bookkeeping",
        "accountant",
    ],
}

SKILL_EXAMPLES = [
    {
        "command": "find missing receipts from accounting email",
        "tool": "accounting_missing_receipts",
        "args": {
            "sender": "accounting@example.com",
            "max_requests": 1,
            "execute": False,
        },
    },
    {
        "command": "send missing receipts report to accountant",
        "tool": "accounting_missing_receipts",
        "args": {
            "sender": "accounting@example.com",
            "accounting_to": "accounting@example.com",
            "max_requests": 1,
            "execute": True,
        },
    },
]