"""Parse a raw .eml into headers, a plain-text body, attachments and a thread.

The thread split is deterministic: it finds the header blocks that mail clients
write when forwarding or quoting ("---------- Forwarded message ----------",
"> Von: ...", "On ... wrote:") and turns them into messages. The requester rule
(domain/requester.py) runs on this, not on anything the LLM says.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from app.ingest.html_text import html_to_text
from app.ingest.pdf import extract_pdf_text


@dataclass
class ParsedAttachment:
    filename: str
    content_type: str
    data: bytes
    text: str = ""
    page_count: int | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass
class ThreadMessage:
    author_name: str | None
    author_email: str | None
    sent_at: datetime | None
    subject: str | None
    text: str
    position: int  # 0 = top of the email (the sender's own text)

    def as_dict(self) -> dict:
        return {
            "author_name": self.author_name,
            "author_email": self.author_email,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "subject": self.subject,
            "text": self.text,
            "position": self.position,
        }


@dataclass
class ParsedEmail:
    message_id: str | None
    in_reply_to: str | None
    references: list[str]
    from_name: str | None
    from_email: str | None
    to: str | None
    subject: str | None
    sent_at: datetime | None  # aware
    body_text: str
    body_was_html: bool
    attachments: list[ParsedAttachment] = field(default_factory=list)
    thread: list[ThreadMessage] = field(default_factory=list)  # chronological

    @property
    def sent_at_utc(self) -> datetime | None:
        return self.sent_at.astimezone(UTC) if self.sent_at else None

    @property
    def sent_date_local(self) -> date | None:
        return self.sent_at.date() if self.sent_at else None

    @property
    def content_hash(self) -> str:
        h = hashlib.sha256(_normalise_ws(self.body_text).encode())
        for a in sorted(self.attachments, key=lambda a: a.sha256):
            h.update(a.sha256.encode())
        return h.hexdigest()


def parse_eml(raw: bytes) -> ParsedEmail:
    msg: EmailMessage = BytesParser(policy=policy.default).parsebytes(raw)  # type: ignore[assignment]

    from_name, from_email = parseaddr(str(msg.get("From", "")))
    try:
        sent_at = parsedate_to_datetime(str(msg["Date"])) if msg["Date"] else None
    except (TypeError, ValueError):
        sent_at = None
    if sent_at is not None and sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=UTC)

    plain, html, attachments = None, None, []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if filename or disposition == "attachment":
            data = part.get_payload(decode=True) or b""
            att = ParsedAttachment(filename=filename or "attachment", content_type=ctype, data=data)
            if ctype == "application/pdf" or att.filename.lower().endswith(".pdf"):
                att.content_type = "application/pdf"
                att.text, att.page_count = extract_pdf_text(data)
            elif ctype.startswith("text/"):
                att.text = data.decode(part.get_content_charset() or "utf-8", errors="replace")
            attachments.append(att)
        elif ctype == "text/plain" and plain is None:
            plain = _get_text(part)
        elif ctype == "text/html" and html is None:
            html = _get_text(part)

    body_was_html = plain is None and html is not None
    body = plain if plain is not None else html_to_text(html or "")
    body = _clean_body(body)

    refs = str(msg.get("References", "") or "").split()
    parsed = ParsedEmail(
        message_id=_strip_id(msg.get("Message-ID")),
        in_reply_to=_strip_id(msg.get("In-Reply-To")),
        references=[r for r in (_strip_id(x) for x in refs) if r],
        from_name=from_name or None,
        from_email=from_email.lower() or None,
        to=", ".join(a for _, a in getaddresses([str(msg.get("To", ""))]) if a) or None,
        subject=str(msg.get("Subject", "")) or None,
        sent_at=sent_at,
        body_text=body,
        body_was_html=body_was_html,
        attachments=attachments,
    )
    parsed.thread = split_thread(parsed)
    return parsed


def _get_text(part: EmailMessage) -> str:
    try:
        return str(part.get_content())
    except (LookupError, UnicodeDecodeError):
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


def _strip_id(value: object) -> str | None:
    if not value:
        return None
    return str(value).strip().strip("<>").strip() or None


def _normalise_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clean_body(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    lines = [ln.rstrip() for ln in text.split("\n")]
    out: list[str] = []
    for ln in lines:
        if not ln and out and not out[-1]:
            continue  # collapse blank runs
        out.append(ln)
    return "\n".join(out).strip()


# --------------------------------------------------------------------------- threads

_SEPARATOR = re.compile(
    r"^-{2,}\s*(forwarded message|original message|weitergeleitete nachricht|"
    r"urspr(ü|ue)ngliche nachricht)\s*-{2,}$|^begin forwarded message:$",
    re.IGNORECASE,
)
_FROM = re.compile(r"^(from|von|de)\s*:\s*(.+)$", re.IGNORECASE)
_DATE = re.compile(r"^(date|sent|gesendet|datum|envoy[ée])\s*:\s*(.+)$", re.IGNORECASE)
_SUBJECT = re.compile(r"^(subject|betreff|objet)\s*:\s*(.*)$", re.IGNORECASE)
_TO = re.compile(r"^(to|an|cc|à)\s*:\s*(.*)$", re.IGNORECASE)
_WROTE = re.compile(
    r"^(on|am)\s+(?P<date>.+?),?\s+(?P<who>[^,]*?<[^>]+>|[^,]+?)\s+(wrote|schrieb)\s*:\s*$",
    re.IGNORECASE,
)


def _unquote(line: str) -> tuple[int, str]:
    depth = 0
    s = line
    while True:
        m = re.match(r"^\s?>\s?", s)
        if not m:
            return depth, s
        depth += 1
        s = s[m.end() :]


def split_thread(email_: ParsedEmail) -> list[ThreadMessage]:
    """Return the messages of the thread, earliest first.

    Segment 0 is the sender's own text. Every recognised header block starts a new
    (older) message. Order of appearance is the reverse of chronological order in
    every common client, so that is the fallback when dates are missing.
    """
    lines = email_.body_text.split("\n")
    segments: list[dict] = [
        {
            "author_name": email_.from_name,
            "author_email": email_.from_email,
            "sent_at": email_.sent_at,
            "subject": email_.subject,
            "lines": [],
        }
    ]
    i = 0
    while i < len(lines):
        _, content = _unquote(lines[i])
        stripped = content.strip()

        wrote = _WROTE.match(stripped)
        if wrote:
            name, addr = parseaddr(wrote.group("who"))
            segments.append(
                {
                    "author_name": name or wrote.group("who").strip() or None,
                    "author_email": addr.lower() or None,
                    "sent_at": parse_loose_date(wrote.group("date")),
                    "subject": None,
                    "lines": [],
                }
            )
            i += 1
            continue

        start = i + 1 if _SEPARATOR.match(stripped) else i
        header = _read_header_block(lines, start)
        if header is not None:
            fields, end = header
            name, addr = parseaddr(fields.get("from", ""))
            segments.append(
                {
                    "author_name": name or None,
                    "author_email": addr.lower() or None,
                    "sent_at": parse_loose_date(fields.get("date", "")),
                    "subject": fields.get("subject"),
                    "lines": [],
                }
            )
            i = end
            continue

        segments[-1]["lines"].append(content)
        i += 1

    messages = [
        ThreadMessage(
            author_name=s["author_name"],
            author_email=s["author_email"],
            sent_at=s["sent_at"],
            subject=s["subject"],
            text=_clean_body("\n".join(s["lines"])),
            position=pos,
        )
        for pos, s in enumerate(segments)
    ]
    # Reverse appearance order = chronological. Dates refine it when every message has one.
    messages.reverse()
    if all(m.sent_at for m in messages):
        messages.sort(key=lambda m: m.sent_at.astimezone(UTC))  # type: ignore[union-attr]
    return messages


def _read_header_block(lines: list[str], start: int) -> tuple[dict[str, str], int] | None:
    """A header block is a From/Von line followed within a few lines by Date or Subject."""
    # Skip blank lines right after a separator.
    i = start
    while i < len(lines) and not _unquote(lines[i])[1].strip():
        i += 1
    if i >= len(lines):
        return None
    first = _unquote(lines[i])[1].strip()
    m = _FROM.match(first)
    if not m:
        return None
    fields = {"from": m.group(2).strip()}
    j = i + 1
    while j < len(lines) and j <= i + 6:
        content = _unquote(lines[j])[1].strip()
        if not content:
            break
        if dm := _DATE.match(content):
            fields["date"] = dm.group(2).strip()
        elif sm := _SUBJECT.match(content):
            fields["subject"] = sm.group(2).strip()
        elif _TO.match(content):
            pass
        else:
            break
        j += 1
    if "date" not in fields and "subject" not in fields:
        return None
    return fields, j


_MONTHS = {
    "jan": 1, "januar": 1, "january": 1, "feb": 2, "februar": 2, "february": 2,
    "mär": 3, "maerz": 3, "märz": 3, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "mai": 5, "may": 5, "jun": 6, "juni": 6, "june": 6, "jul": 7, "juli": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "okt": 10, "oct": 10,
    "oktober": 10, "october": 10, "nov": 11, "november": 11, "dez": 12, "dec": 12,
    "dezember": 12, "december": 12,
}  # fmt: skip


def parse_loose_date(text: str) -> datetime | None:
    """RFC 2822 dates, plus the German long form Outlook writes ("Donnerstag, 14. Mai 2026 16:30")."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError, IndexError):
        pass
    m = re.search(
        r"(\d{1,2})\.?\s+([A-Za-zäÄ]+)\.?\s+(\d{4})(?:[, ]+(?:um\s+)?(\d{1,2}):(\d{2}))?", text
    )
    if m and m.group(2).lower() in _MONTHS:
        hour = int(m.group(4) or 0)
        minute = int(m.group(5) or 0)
        try:
            return datetime(
                int(m.group(3)),
                _MONTHS[m.group(2).lower()],
                int(m.group(1)),
                hour,
                minute,
                tzinfo=UTC,
            )
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", text)
    if m:
        try:
            return datetime(
                int(m.group(3)),
                int(m.group(2)),
                int(m.group(1)),
                int(m.group(4) or 0),
                int(m.group(5) or 0),
                tzinfo=UTC,
            )
        except ValueError:
            return None
    return None
