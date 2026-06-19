#!/usr/bin/env python3
"""
PST -> IMAP Migration Script - fixed attachment version

Fixes compared to the earlier script:
  - Attachments are included even when transport_headers exists.
  - Attachment names use long_filename / filename / display_name / name fallback.
  - Attachment stream reading is safer and seeks to start when possible.
  - Duplicate delete-by-Message-ID is a real IMAPClient method.
  - Message-ID is generated when missing so reruns can delete/reinsert reliably.
  - MIME is always rebuilt as valid RFC822 with multipart/mixed when attachments exist.
  - Plain + HTML body are preserved as multipart/alternative.

Dependencies:
    pip install libpff-python vobject

Usage:
    python3 pst_to_imap_fixed.py --pst file.pst --host imap.titan.email \
        --user you@domain.com --password 'pw' --dry-run

    python3 pst_to_imap_fixed.py --pst file.pst --host imap.titan.email \
        --user you@domain.com --password 'pw'
"""

import argparse
import imaplib
import email
import email.utils
import email.header
import email.policy
import sys
import time
import logging
import traceback
import subprocess
import tempfile
import shutil
import mimetypes
import hashlib
from pathlib import Path
from email.message import EmailMessage
from email.utils import make_msgid

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("pst_migration.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ─── Dependencies ────────────────────────────────────────────────────────────

try:
    import pypff
except ImportError:
    log.error("pypff not found. Install with: pip install libpff-python")
    sys.exit(1)

try:
    import vobject
    HAS_VOBJECT = True
except ImportError:
    log.warning("vobject not found — contact/calendar fallback building disabled. Install with: pip install vobject")
    HAS_VOBJECT = False

# ─── Constants ───────────────────────────────────────────────────────────────

DEFAULT_SKIP_FOLDERS = {
    "sync issues", "conflicts", "local failures", "server failures",
    "personmetadata", "recipient cache", "quick step settings",
    "suggested contacts", "united states holidays", "yammer root",
    "social activity feeds", "social activity notifications",
    "files", "at", "eventcheckpoints", "conversation action settings",
    "externalcontacts", "conversation history", "notes", "journal",
    "tasks", "search root", "ipm_common_views", "itemprocsearch",
}

PST_ROOT_NAMES = {
    "top of outlook data file", "personal folders", "outlook data file", "mailbox",
}

FOLDER_MAP = {
    "inbox": "INBOX",
    "sent items": "Sent",
    "sent mail": "Sent",
    "deleted items": "Trash",
    "junk e-mail": "Junk",
    "junk email": "Junk",
    "junk": "Junk",
    "drafts": "Drafts",
    "archive": "Archive",
    "outbox": "Sent",
    "trash": "Trash",
}

CONTACT_FOLDERS = {"contacts"}
CALENDAR_FOLDERS = {"calendar"}

EMAIL_SKIP_CLASSES = {
    "ipm.contact", "ipm.distlist", "ipm.appointment",
    "ipm.task", "ipm.stickynote", "ipm.schedule",
}

# ─── Generic helpers ─────────────────────────────────────────────────────────

def safe_str(obj, attr, default=""):
    try:
        v = getattr(obj, attr, None)
        if v is None:
            return default
        if callable(v):
            v = v()
        if isinstance(v, bytes):
            return v.decode("utf-8", errors="replace")
        return str(v)
    except Exception:
        return default


def decode_hdr(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    try:
        parts = email.header.decode_header(value)
        out = []
        for part, charset in parts:
            if isinstance(part, bytes):
                out.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                out.append(part)
        return "".join(out)
    except Exception:
        return str(value)


def first_nonempty(*values):
    for v in values:
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def get_ts(msg) -> float:
    for attr in ("client_submit_time", "delivery_time", "creation_time"):
        try:
            t = getattr(msg, attr, None)
            if t:
                return t.timestamp()
        except Exception:
            pass
    return time.time()


def get_flags(msg) -> str:
    try:
        f = getattr(msg, "message_flags", 0) or 0
        if isinstance(f, int) and (f & 0x01):
            return "\\Seen"
    except Exception:
        pass
    return ""


def imap_folder_name(pst_path: str) -> str:
    parts = pst_path.split("/")
    cleaned = []
    for p in parts:
        s = p.strip()
        if not s:
            continue
        if s.lower() in PST_ROOT_NAMES:
            continue
        if any(s.lower().startswith(r) for r in PST_ROOT_NAMES):
            continue
        cleaned.append(s)
    if not cleaned:
        return "INBOX"
    mapped = [FOLDER_MAP.get(p.lower(), p) for p in cleaned]
    return "/".join(mapped)


def should_skip(name: str, extra: set) -> bool:
    return name.strip().lower() in DEFAULT_SKIP_FOLDERS or name.strip().lower() in extra


def sanitize_filename(name: str, fallback="attachment.bin") -> str:
    name = (name or fallback).replace("\x00", "").strip()
    name = name.replace("/", "_").replace("\\", "_")
    safe = "".join(c if c.isalnum() or c in "._- ()[]" else "_" for c in name)
    safe = safe.strip(" ._")
    return safe or fallback


def detect_ext(data: bytes) -> str:
    d = data[:32]
    if d.startswith(b"%PDF"):
        return ".pdf"
    if d.startswith(b"\x89PNG"):
        return ".png"
    if d.startswith(b"\xff\xd8"):
        return ".jpg"
    if d.startswith(b"GIF87a") or d.startswith(b"GIF89a"):
        return ".gif"
    if d.startswith(b"PK"):
        return ".zip"
    if d.lstrip().upper().startswith(b"BEGIN:VCALENDAR"):
        return ".ics"
    if d.lstrip().upper().startswith(b"BEGIN:VCARD"):
        return ".vcf"
    return ".bin"

# ─── Attachment extraction helpers ───────────────────────────────────────────
def get_record_entry_string(obj, wanted_types):
    try:
        for rsi in range(obj.number_of_record_sets):
            rs = obj.get_record_set(rsi)

            for ei in range(rs.number_of_entries):
                entry = rs.get_entry(ei)

                et = getattr(entry, "entry_type", None)
                if et not in wanted_types:
                    continue

                value = getattr(entry, "data_as_string", None)
                if value:
                    return str(value)
    except Exception:
        pass

    return ""

def attachment_filename(att, index: int, data: bytes = b"") -> str:

    # MAPI properties from record set
    name = get_record_entry_string(att, {
        0x3707,  # PR_ATTACH_LONG_FILENAME
        0x3704,  # PR_ATTACH_FILENAME
        0x3001,  # PR_DISPLAY_NAME
    })

    if not name:
        name = first_nonempty(
            safe_str(att, "long_filename"),
            safe_str(att, "filename"),
            safe_str(att, "display_name"),
            safe_str(att, "name"),
            f"attachment_{index}",
        )

    name = sanitize_filename(name, fallback=f"attachment_{index}")

    if not Path(name).suffix and data:
        ext = get_record_entry_string(att, {
            0x3703,  # PR_ATTACH_EXTENSION
        })

        if ext:
            name += ext
        else:
            name += detect_ext(data)

    return name

def attachment_size(att) -> int:
    for attr in ("size", "get_size"):
        try:
            v = getattr(att, attr, None)
            if callable(v):
                v = v()
            if v:
                return int(v)
        except Exception:
            pass
    return 0


def read_attachment_data(att) -> bytes:
    size = attachment_size(att)

    # pypff often needs seek(0), and some builds return empty if buffer is too large.
    try:
        if hasattr(att, "seek"):
            att.seek(0)
    except Exception:
        pass

    if size > 0:
        try:
            data = att.read_buffer(size)
            if data:
                return data
        except Exception:
            pass

    # Chunk fallback.
    try:
        if hasattr(att, "seek"):
            att.seek(0)
    except Exception:
        pass

    chunks = []
    try:
        while True:
            chunk = att.read_buffer(1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    except Exception:
        pass

    return b"".join(chunks)


def iter_attachments(msg):
    """Yield (name, data_bytes) for all normal attachments on a pypff message."""
    try:
        n = msg.number_of_attachments
    except Exception:
        return

    for i in range(n):
        try:
            att = msg.get_attachment(i)
            data = read_attachment_data(att)
            name = attachment_filename(att, i, data)
            if data:
                yield name, data
            else:
                log.warning(f"    Attachment {i} had no readable data: {name}")
        except Exception as e:
            log.warning(f"    Attachment {i} failed: {e}")

# ─── Calendar/contact extraction ─────────────────────────────────────────────

def extract_ics_from_item(msg):
    for name, data in iter_attachments(msg):
        if name.lower().endswith((".ics", ".vcs")):
            return data
        if data.lstrip().upper().startswith(b"BEGIN:VCALENDAR"):
            return data

    body = safe_str(msg, "plain_text_body")
    if "BEGIN:VCALENDAR" in body:
        start = body.find("BEGIN:VCALENDAR")
        end = body.find("END:VCALENDAR", start)
        if end > 0:
            return body[start:end + len("END:VCALENDAR")].encode("utf-8")

    html = safe_str(msg, "html_body")
    if "BEGIN:VCALENDAR" in html:
        start = html.find("BEGIN:VCALENDAR")
        end = html.find("END:VCALENDAR", start)
        if end > 0:
            return html[start:end + len("END:VCALENDAR")].encode("utf-8")

    return None


def build_ics_from_item(msg):
    if not HAS_VOBJECT:
        return None
    try:
        cal = vobject.iCalendar()
        vevent = cal.add("vevent")
        subject = safe_str(msg, "subject") or safe_str(msg, "conversation_topic") or "Untitled"
        vevent.add("summary").value = subject
        for attr in ("client_submit_time", "creation_time", "delivery_time"):
            t = getattr(msg, attr, None)
            if t:
                try:
                    vevent.add("dtstart").value = t
                    break
                except Exception:
                    pass
        body = safe_str(msg, "plain_text_body") or safe_str(msg, "html_body")
        if body:
            vevent.add("description").value = body[:1000]
        sender = safe_str(msg, "sender_name")
        if sender:
            vevent.add("organizer").value = f"CN={sender}"
        return cal.serialize().encode("utf-8")
    except Exception as e:
        log.debug(f"build_ics_from_item error: {e}")
        return None


def extract_vcf_from_item(msg):
    for name, data in iter_attachments(msg):
        if name.lower().endswith((".vcf", ".vcard")):
            return data
        if data.lstrip().upper().startswith(b"BEGIN:VCARD"):
            return data
    body = safe_str(msg, "plain_text_body")
    if "BEGIN:VCARD" in body:
        start = body.find("BEGIN:VCARD")
        end = body.find("END:VCARD", start)
        if end > 0:
            return body[start:end + len("END:VCARD")].encode("utf-8")
    return None


def build_vcf_from_item(msg):
    if not HAS_VOBJECT:
        return None
    try:
        name = safe_str(msg, "subject") or safe_str(msg, "sender_name") or "Unknown"
        if not name or name == "Unknown":
            return None
        card = vobject.vCard()
        card.add("fn").value = name
        n = card.add("n")
        parts = name.strip().split()
        n.value = vobject.vcard.Name(
            family=parts[-1] if len(parts) > 1 else name,
            given=" ".join(parts[:-1]) if len(parts) > 1 else "",
        )
        return card.serialize().encode("utf-8")
    except Exception as e:
        log.debug(f"build_vcf_from_item error: {e}")
        return None

# ─── readpst fallback ────────────────────────────────────────────────────────

def try_readpst_contacts(pst_path: str, output_dir: Path) -> int:
    if not shutil.which("readpst"):
        return -1
    tmpdir = Path(tempfile.mkdtemp())
    try:
        subprocess.run(["readpst", "-S", "-o", str(tmpdir), str(pst_path)], capture_output=True, text=True, timeout=300)
        count = 0
        for vcf in tmpdir.rglob("*.vcf"):
            dest = output_dir / f"readpst_{count:04d}_{vcf.name}"
            shutil.copy(vcf, dest)
            count += 1
        return count
    except Exception as e:
        log.warning(f"readpst contacts error: {e}")
        return -1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def try_readpst_calendar(pst_path: str, output_dir: Path) -> int:
    if not shutil.which("readpst"):
        return -1
    tmpdir = Path(tempfile.mkdtemp())
    try:
        subprocess.run(["readpst", "-S", "-o", str(tmpdir), str(pst_path)], capture_output=True, text=True, timeout=300)
        count = 0
        for ics in tmpdir.rglob("*.ics"):
            dest = output_dir / f"readpst_{count:04d}_{ics.name}"
            shutil.copy(ics, dest)
            count += 1
        return count
    except Exception as e:
        log.warning(f"readpst calendar error: {e}")
        return -1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# ─── IMAP client ─────────────────────────────────────────────────────────────

class IMAPClient:
    def __init__(self, host, port, user, password, ssl=True, delete_existing=True):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.ssl = ssl
        self.delete_existing = delete_existing
        self.conn = None
        self._folders: set[str] = set()

    def connect(self):
        log.info(f"Connecting to {self.host}:{self.port} ({'SSL' if self.ssl else 'STARTTLS'})")
        if self.ssl:
            self.conn = imaplib.IMAP4_SSL(self.host, self.port)
        else:
            self.conn = imaplib.IMAP4(self.host, self.port)
            self.conn.starttls()
        self.conn.login(self.user, self.password)
        log.info("Logged in successfully.")
        self._refresh()

    def _refresh(self):
        status, folders = self.conn.list()
        self._folders = set()
        if status != "OK":
            return
        for f in folders or []:
            if not f:
                continue
            decoded = f.decode("utf-8", errors="replace")
            name = decoded.split('"')[-1].strip().strip('"') if '"' in decoded else decoded.rsplit(" ", 1)[-1].strip()
            if name:
                self._folders.add(name)

    def ensure_folder(self, name: str):
        if name == "INBOX" or name in self._folders:
            return
        parts = name.split("/")
        for i in range(1, len(parts) + 1):
            partial = "/".join(parts[:i])
            if partial not in self._folders and partial != "INBOX":
                try:
                    status, _ = self.conn.create(f'"{partial}"')
                    if status == "OK":
                        log.info(f"  Created folder: {partial}")
                        self._folders.add(partial)
                except imaplib.IMAP4.error as e:
                    log.warning(f"  Create folder '{partial}' failed: {e}")

    def delete_by_message_id(self, folder: str, raw: bytes):
        if not self.delete_existing:
            return
        try:
            parsed = email.message_from_bytes(raw, policy=email.policy.default)
            msgid = parsed.get("Message-ID")
            if not msgid:
                return

            self.ensure_folder(folder)
            status, _ = self.conn.select(f'"{folder}"', readonly=False)
            if status != "OK":
                return

            # HEADER search expects the Message-ID value including angle brackets.
            status, data = self.conn.search(None, "HEADER", "Message-ID", f'"{msgid}"')
            if status != "OK" or not data or not data[0]:
                return

            ids = data[0].split()
            for seq_id in ids:
                self.conn.store(seq_id, "+FLAGS", "\\Deleted")

            if ids:
                log.info(f"  Deleted {len(ids)} existing message(s) with Message-ID {msgid}")
                self.conn.expunge()
        except Exception as e:
            log.warning(f"Delete existing message failed: {e}")

    def append(self, folder: str, raw: bytes, flags: str = "", ts=None) -> bool:
        self.ensure_folder(folder)
        self.delete_by_message_id(folder, raw)
        try:
            imap_date = imaplib.Time2Internaldate(ts or time.time())
            flag_str = f"({flags})" if flags else "()"
            status, _ = self.conn.append(f'"{folder}"', flag_str, imap_date, raw)
            return status == "OK"
        except imaplib.IMAP4.error as e:
            log.error(f"  APPEND '{folder}' failed: {e}")
            return False
        except Exception as e:
            log.error(f"  APPEND '{folder}' failed: {e}")
            return False

    def disconnect(self):
        if self.conn:
            try:
                self.conn.logout()
            except Exception:
                pass

# ─── PST -> RFC822 ───────────────────────────────────────────────────────────

def get_transport_header_map(msg):
    """Parse original transport headers only for useful fields; do not reuse raw MIME body."""
    headers = safe_str(msg, "transport_headers")
    if not headers.strip():
        return {}
    try:
        parsed = email.message_from_string(headers, policy=email.policy.default)
        return {k.lower(): str(v) for k, v in parsed.items()}
    except Exception:
        return {}


def stable_message_id(msg, subject: str, sender: str, ts: float) -> str:
    existing = ""
    h = get_transport_header_map(msg)
    if h.get("message-id"):
        return h["message-id"]

    raw_key = "|".join([
        subject or "",
        sender or "",
        str(int(ts or 0)),
        safe_str(msg, "conversation_topic"),
        safe_str(msg, "identifier"),
    ])
    digest = hashlib.sha1(raw_key.encode("utf-8", errors="replace")).hexdigest()[:24]
    return f"<pst-{digest}@pst-migration.local>"


def add_recipients(m: EmailMessage, msg, header_map: dict):
    if header_map.get("to"):
        m["To"] = header_map["to"]
    else:
        rcpts = []
        try:
            for i in range(msg.number_of_recipients):
                r = msg.get_recipient(i)
                addr = first_nonempty(
                    safe_str(r, "email_address"),
                    safe_str(r, "smtp_address"),
                )
                name = first_nonempty(
                    safe_str(r, "display_name"),
                    safe_str(r, "name"),
                )
                if addr:
                    rcpts.append(email.utils.formataddr((name, addr)) if name else addr)
        except Exception:
            pass
        m["To"] = ", ".join(rcpts) if rcpts else "undisclosed-recipients:;"

    if header_map.get("cc"):
        m["Cc"] = header_map["cc"]
    if header_map.get("bcc"):
        m["Bcc"] = header_map["bcc"]


def msg_to_rfc822(msg) -> bytes | None:
    """
    Build a clean RFC822 message and always attach PST attachments.

    Important: we intentionally do NOT return transport_headers + body directly,
    because that loses attachments in many pypff PST messages.
    """
    try:
        header_map = get_transport_header_map(msg)

        plain = safe_str(msg, "plain_text_body")
        html = safe_str(msg, "html_body")

        subject = decode_hdr(first_nonempty(
            header_map.get("subject"),
            safe_str(msg, "subject"),
            safe_str(msg, "conversation_topic"),
            "(no subject)",
        ))

        sender_addr = first_nonempty(
            header_map.get("from"),
            safe_str(msg, "sender_email_address"),
            safe_str(msg, "sender_name"),
            "unknown@unknown",
        )

        ts = get_ts(msg)
        msgid = stable_message_id(msg, subject, sender_addr, ts)

        attachments = list(iter_attachments(msg))

        m = EmailMessage(policy=email.policy.SMTP)
        m["Subject"] = subject
        m["From"] = sender_addr
        add_recipients(m, msg, header_map)
        m["Date"] = header_map.get("date") or email.utils.formatdate(ts, usegmt=True)
        m["Message-ID"] = msgid

        # Optional useful threading headers.
        for hdr in ("references", "in-reply-to", "reply-to"):
            if header_map.get(hdr):
                proper = "-".join(part.capitalize() for part in hdr.split("-"))
                m[proper] = header_map[hdr]

        if plain and html:
            m.set_content(plain, subtype="plain", charset="utf-8")
            m.add_alternative(html, subtype="html", charset="utf-8")
        elif html:
            # Some clients prefer a plain fallback even for HTML-only Outlook mail.
            m.set_content("This message contains HTML content.", subtype="plain", charset="utf-8")
            m.add_alternative(html, subtype="html", charset="utf-8")
        else:
            m.set_content(plain or "", subtype="plain", charset="utf-8")

        for att_name, att_data in attachments:
            ctype, _ = mimetypes.guess_type(att_name)
            if ctype:
                maintype, subtype = ctype.split("/", 1)
            else:
                maintype, subtype = "application", "octet-stream"

            m.add_attachment(
                att_data,
                maintype=maintype,
                subtype=subtype,
                filename=att_name,
            )

        log.debug(f"Built MIME: subject={subject!r}, attachments={len(attachments)}, bytes={len(m.as_bytes())}")
        return m.as_bytes(policy=email.policy.SMTP)

    except Exception as e:
        log.debug(f"msg_to_rfc822 error: {e}")
        return None

# ─── Export folders ──────────────────────────────────────────────────────────

def export_calendar_folder(folder, output_dir: Path, stats: dict):
    subject = safe_str(folder, "name")
    log.info(f"  Calendar folder [{subject}]: {folder.number_of_sub_messages} items")
    for i in range(folder.number_of_sub_messages):
        try:
            msg = folder.get_sub_message(i)
            data = extract_ics_from_item(msg) or build_ics_from_item(msg)
            if data:
                subj = safe_str(msg, "subject") or safe_str(msg, "conversation_topic") or f"event_{i}"
                safe_name = sanitize_filename(subj, fallback=f"event_{i}")[:60]
                path = output_dir / f"{safe_name}_{stats['calendar']:04d}.ics"
                path.write_bytes(data)
                stats["calendar"] += 1
        except Exception as e:
            log.debug(f"  Calendar item [{i}] error: {e}")


def export_contacts_folder(folder, output_dir: Path, stats: dict):
    log.info(f"  Contacts folder: {folder.number_of_sub_messages} items")
    for i in range(folder.number_of_sub_messages):
        try:
            msg = folder.get_sub_message(i)
            data = extract_vcf_from_item(msg) or build_vcf_from_item(msg)
            if data:
                name = safe_str(msg, "subject") or f"contact_{i}"
                safe_name = sanitize_filename(name, fallback=f"contact_{i}")[:60]
                path = output_dir / f"{safe_name}_{stats['contacts']:04d}.vcf"
                path.write_bytes(data)
                stats["contacts"] += 1
        except Exception as e:
            log.debug(f"  Contact item [{i}] error: {e}")

# ─── Folder traversal ────────────────────────────────────────────────────────

def migrate_emails(folder, imap: IMAPClient | None, stats: dict, dry_run: bool,
                   extra_skips: set, contacts_dir: Path, calendar_dir: Path,
                   skip_emails: bool, skip_contacts: bool, skip_calendar: bool,
                   path_str: str = ""):

    name = safe_str(folder, "name")
    current_path = f"{path_str}/{name}" if path_str else name
    name_lc = name.strip().lower()

    if name_lc in CALENDAR_FOLDERS:
        if not skip_calendar:
            export_calendar_folder(folder, calendar_dir, stats)
        try:
            for i in range(folder.number_of_sub_folders):
                sub = folder.get_sub_folder(i)
                migrate_emails(sub, imap, stats, dry_run, extra_skips, contacts_dir, calendar_dir,
                               skip_emails, skip_contacts, skip_calendar, current_path)
        except Exception:
            pass
        return

    if name_lc in CONTACT_FOLDERS:
        if not skip_contacts:
            export_contacts_folder(folder, contacts_dir, stats)
        return

    if should_skip(name, extra_skips):
        log.info(f"  SKIP [{current_path}]")
        return

    target = imap_folder_name(current_path)
    try:
        n_msg = folder.number_of_sub_messages
    except Exception:
        n_msg = 0

    if n_msg > 0 and not skip_emails:
        log.info(f"  [{current_path}] -> [{target}]  ({n_msg} items)")

    uploaded = skipped = errors = 0

    if not skip_emails:
        for i in range(n_msg):
            try:
                msg = folder.get_sub_message(i)
            except Exception as e:
                log.debug(f"  get_sub_message({i}) failed in {current_path}: {e}")
                errors += 1
                stats["errors"] += 1
                continue

            try:
                mc = safe_str(msg, "message_class").lower().strip()
                if any(mc.startswith(c) for c in EMAIL_SKIP_CLASSES):
                    skipped += 1
                    continue

                raw = msg_to_rfc822(msg)
                if not raw:
                    errors += 1
                    stats["errors"] += 1
                    continue

                flags = get_flags(msg)
                ts = get_ts(msg)

                if dry_run:
                    # Validate parse/build only.
                    parsed = email.message_from_bytes(raw, policy=email.policy.default)
                    att_count = sum(1 for part in parsed.walk() if part.get_content_disposition() == "attachment")
                    log.debug(f"    DRY {i}: {parsed.get('Subject')} attachments={att_count}")
                    uploaded += 1
                    stats["emails"] += 1
                else:
                    if imap and imap.append(target, raw, flags, ts):
                        uploaded += 1
                        stats["emails"] += 1
                    else:
                        errors += 1
                        stats["errors"] += 1

            except Exception as e:
                log.debug(f"  item error [{current_path}][{i}]: {e}")
                errors += 1
                stats["errors"] += 1

    if n_msg > 0 and not skip_emails:
        parts = [f"uploaded {uploaded}"]
        if skipped:
            parts.append(f"skipped {skipped} non-email")
        if errors:
            parts.append(f"errors {errors}")
        log.info(f"    ↳ {', '.join(parts)}")

    try:
        for i in range(folder.number_of_sub_folders):
            sub = folder.get_sub_folder(i)
            migrate_emails(sub, imap, stats, dry_run, extra_skips, contacts_dir, calendar_dir,
                           skip_emails, skip_contacts, skip_calendar, current_path)
    except Exception as e:
        log.warning(f"  sub-folder error in {current_path}: {e}")

# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Migrate PST -> IMAP with fixed attachment handling")
    p.add_argument("--pst", required=True)
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, default=993)
    p.add_argument("--user", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--no-ssl", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="Parse only, do not upload")
    p.add_argument("--contacts-dir", default="./exported_contacts")
    p.add_argument("--calendar-dir", default="./exported_calendar")
    p.add_argument("--skip-emails", action="store_true")
    p.add_argument("--skip-contacts", action="store_true")
    p.add_argument("--skip-calendar", action="store_true")
    p.add_argument("--skip-folder", action="append", default=[], metavar="NAME")
    p.add_argument("--no-delete-existing", action="store_true", help="Do not delete same Message-ID before APPEND")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    if args.debug:
        log.setLevel(logging.DEBUG)

    pst_path = Path(args.pst)
    contacts_dir = Path(args.contacts_dir)
    calendar_dir = Path(args.calendar_dir)
    extra_skips = {s.lower() for s in args.skip_folder}

    if not pst_path.exists():
        log.error(f"PST not found: {pst_path}")
        sys.exit(1)

    contacts_dir.mkdir(parents=True, exist_ok=True)
    calendar_dir.mkdir(parents=True, exist_ok=True)

    stats = {"emails": 0, "contacts": 0, "calendar": 0, "errors": 0}

    imap = None
    if not args.dry_run and not args.skip_emails:
        imap = IMAPClient(
            args.host,
            args.port,
            args.user,
            args.password,
            ssl=not args.no_ssl,
            delete_existing=not args.no_delete_existing,
        )
        imap.connect()
    elif args.dry_run:
        log.info("DRY RUN — nothing will be uploaded.")

    log.info(f"Opening PST: {pst_path}")
    pst = pypff.file()
    pst.open(str(pst_path))

    try:
        root = pst.get_root_folder()
        log.info("Processing PST...")
        for i in range(root.number_of_sub_folders):
            folder = root.get_sub_folder(i)
            migrate_emails(
                folder,
                imap,
                stats,
                args.dry_run,
                extra_skips,
                contacts_dir,
                calendar_dir,
                args.skip_emails,
                args.skip_contacts,
                args.skip_calendar,
            )
    except Exception as e:
        log.error(f"Error: {e}")
        traceback.print_exc()
    finally:
        try:
            pst.close()
        except Exception:
            pass
        if imap:
            imap.disconnect()

    # readpst fallback for contacts/calendar if pypff got nothing
    if stats["contacts"] == 0 and not args.skip_contacts:
        log.info("No contacts via pypff — trying readpst fallback...")
        n = try_readpst_contacts(str(pst_path), contacts_dir)
        if n == -1:
            log.warning("  readpst not installed. Run: sudo apt-get install pst-utils")
        elif n == 0:
            log.warning("  readpst found no .vcf files either.")
        else:
            stats["contacts"] = n
            log.info(f"  readpst exported {n} contact(s)")

    if stats["calendar"] == 0 and not args.skip_calendar:
        log.info("No calendar events via pypff — trying readpst fallback...")
        n = try_readpst_calendar(str(pst_path), calendar_dir)
        if n == -1:
            log.warning("  readpst not installed. Run: sudo apt-get install pst-utils")
        elif n == 0:
            log.warning("  readpst found no .ics files either.")
        else:
            stats["calendar"] = n
            log.info(f"  readpst exported {n} calendar file(s)")

    log.info("=" * 55)
    log.info("DONE")
    log.info(f"  Emails   : {stats['emails']:,}")
    log.info(f"  Contacts : {stats['contacts']:,}  ->  {contacts_dir}/")
    log.info(f"  Calendar : {stats['calendar']:,}  ->  {calendar_dir}/")
    log.info(f"  Errors   : {stats['errors']:,}")
    log.info("=" * 55)

    if stats["contacts"] > 0:
        log.info("Import contacts: Titan webmail -> Contacts -> Import .vcf")
    if stats["calendar"] > 0:
        log.info("Import calendar: Titan Calendar -> Import .ics")


if __name__ == "__main__":
    main()
