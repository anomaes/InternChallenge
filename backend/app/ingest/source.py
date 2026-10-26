"""The labelled text the model sees. Data minimisation: only From, Date and Subject
headers, the body and attachment text; no To/CC lists, no routing headers."""

from app.ingest.eml import ParsedEmail


def build_source(parsed: ParsedEmail, attachment_texts: list[str] | None = None) -> str:
    """`attachment_texts` overrides the attachment text (used to pass redacted text)."""
    sender = parsed.from_email or ""
    if parsed.from_name:
        sender = f"{parsed.from_name} <{sender}>"
    date = parsed.sent_at.strftime("%Y-%m-%d %H:%M %z") if parsed.sent_at else "unknown"
    parts = [
        "### EMAIL HEADERS",
        f"From: {sender}",
        f"Date: {date}",
        f"Subject: {parsed.subject or ''}",
        "",
        "### EMAIL BODY" + (" (converted from HTML)" if parsed.body_was_html else ""),
        parsed.body_text or "(empty)",
    ]
    for i, att in enumerate(parsed.attachments, start=1):
        text = attachment_texts[i - 1] if attachment_texts is not None else att.text
        kind = "PDF" if att.content_type == "application/pdf" else att.content_type
        pages = (
            f", {att.page_count} page{'s' if att.page_count != 1 else ''}" if att.page_count else ""
        )
        parts += ["", f"### ATTACHMENT {i}: {att.filename} ({kind}{pages})"]
        parts.append(text or "(no extractable text)")
    return "\n".join(parts)
