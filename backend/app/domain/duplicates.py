"""Repeats and corrections (brief 5): link to the original and flag; never silently
create a second requisition or overwrite the first. The clerk decides.

Signals, strongest first: an explicit request ID in the text, In-Reply-To/References,
identical content (a resend), and a fingerprint (same requester and supplier, same
lines or amount, within 30 days).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from rapidfuzz import fuzz

from app.domain.issues import Finding

WINDOW = timedelta(days=30)


@dataclass
class Candidate:
    id: int
    public_id: str
    state: str
    requester_id: str | None
    supplier_id: str | None
    cost_center_code: str | None
    po_total: Decimal | None
    sent_date: date | None
    content_hash: str
    body_key: str  # sender + normalised body text, to catch a resend with different attachments
    message_id: str | None
    lines_text: str
    title: str | None


@dataclass
class DuplicateResult:
    linked_to_id: int | None = None
    link_type: str | None = None
    link_reason: str | None = None
    findings: list[Finding] = field(default_factory=list)


def find_duplicates(
    *,
    me: Candidate,
    message_kind: str | None,
    referenced: list[str],
    in_reply_to: list[str],
    others: list[Candidate],
) -> DuplicateResult:
    res = DuplicateResult()
    kind_word = "correction" if message_kind == "correction" else "duplicate"
    by_public = {c.public_id.upper(): c for c in others}

    def link(
        c: Candidate, link_type: str, reason: str, severity: str = "blocking"
    ) -> DuplicateResult:
        res.linked_to_id, res.link_type, res.link_reason = c.id, link_type, reason
        code = "suspected_correction" if link_type == "correction" else "suspected_duplicate"
        if severity != "blocking":
            code = "possibly_related"
        res.findings.append(
            Finding(
                code,
                severity,  # type: ignore[arg-type]
                f"{reason} Linked to {c.public_id}"
                + (f" ({c.title})" if c.title else "")
                + ". Decide: close as duplicate, apply as correction, or keep both.",
                field="link",
                details={"linked_to": c.public_id},
            )
        )
        return res

    for ref in referenced:
        c = by_public.get(ref.strip().upper())
        if c:
            lt = "correction" if message_kind == "correction" else "repeat"
            return link(c, lt, f"The email refers to {ref}.")
        res.findings.append(
            Finding(
                "referenced_request_not_found",
                "blocking",
                f"The email refers to {ref}, which isn't in this system (possibly from before it "
                f"went live). The items and supplier can't be taken from it automatically.",
                field="link",
                details={"reference": ref},
            )
        )

    for mid in in_reply_to:
        c = next((o for o in others if o.message_id and o.message_id == mid), None)
        if c:
            lt = "correction" if message_kind == "correction" else "related"
            return link(c, lt, f"This is a reply in the same thread as {c.public_id}.")

    for c in others:
        if c.content_hash == me.content_hash:
            return link(c, "duplicate", "Same text and attachments as an earlier email (a resend).")
    for c in others:
        if c.body_key == me.body_key and _within_window(me.sent_date, c.sent_date):
            return link(
                c,
                "duplicate",
                "Same sender and same text as an earlier email (resent, attachments differ).",
            )

    recent = [c for c in others if _within_window(me.sent_date, c.sent_date)]
    for c in recent:
        if not (me.supplier_id and c.supplier_id == me.supplier_id):
            continue
        same_requester = me.requester_id and c.requester_id == me.requester_id
        same_amount = (
            me.po_total is not None
            and c.po_total is not None
            and abs(me.po_total - c.po_total) <= Decimal("0.01")
        )
        similar_lines = (
            bool(me.lines_text and c.lines_text)
            and fuzz.token_sort_ratio(me.lines_text, c.lines_text) >= 85
        )
        if same_requester and (same_amount or similar_lines):
            return link(c, kind_word, "Same requester, supplier and items/amount within 30 days.")
        if similar_lines and me.cost_center_code == c.cost_center_code:
            return link(
                c,
                "related",
                "Similar items from the same supplier for the same cost center within 30 days.",
                severity="warning",
            )

    if message_kind in ("correction", "repeat") and not res.findings:
        mine = [c for c in recent if me.requester_id and c.requester_id == me.requester_id]
        res.findings.append(
            Finding(
                "unlinked_correction" if message_kind == "correction" else "unlinked_repeat",
                "blocking",
                f"This message is a {message_kind} of an earlier request but doesn't say which one. "
                + (
                    "Recent requests from the same person: "
                    + ", ".join(c.public_id for c in mine[:5])
                    + "."
                    if mine
                    else "No recent request from the same person was found."
                ),
                field="link",
                details={"candidates": [c.public_id for c in mine[:5]]},
            )
        )
    return res


def _within_window(a: date | None, b: date | None) -> bool:
    if a is None or b is None:
        return True
    return abs(a - b) <= WINDOW
