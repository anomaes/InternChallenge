"""Deterministic evaluation of a requisition's current values.

Runs after extraction and again after every clerk edit, so the same rules decide in
both cases. It recomputes amounts, matches, the approval chain preview and the set of
`evaluate`-origin issues. Issues from ingest (duplicates, extraction failure) are
sticky and left alone here.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal

from sqlmodel import Session, select

from app.db.models import Attachment, Email, Issue, LineItem, Requisition, utcnow
from app.domain.approval import ChainPlan, plan_chain
from app.domain.issues import Finding
from app.domain.master import MasterData
from app.domain.matching import (
    cost_center_suggestions,
    match_cost_center,
    match_supplier,
    supplier_status_findings,
)
from app.domain.reconcile import LineIn, StatedTotalIn, fmt, reconcile, to_chf
from app.services.settings_store import get_setting

# Values whose doubt blocks routing; doubt on anything else only warns.
ROUTING_LINE_FIELDS = {"quantity", "unit_price", "price_basis", "stated_line_total", "line"}
ROUTING_HEADER_FIELDS = {"supplier", "supplier_vat", "cost_center", "currency"}
LINE_FIELD_LABELS = {
    "quantity": "quantity",
    "unit_price": "unit price",
    "price_basis": "price basis",
    "stated_line_total": "line total",
    "item_code": "item code",
    "source_quote": "evidence",
    "line": "quantity and price",
}
HEADER_LABELS = {
    "supplier": "Supplier name",
    "supplier_vat": "Supplier VAT ID",
    "cost_center": "Cost center",
    "currency": "Currency",
    "vat_amount": "VAT amount",
    "vat_rate": "VAT rate",
    "delivery_date": "Delivery date",
    "quote_valid_until": "Quote validity",
    "referenced_requests": "Referenced request",
}


_ATTACHMENT_WORDS = re.compile(
    r"\b(attached|attachment|enclosed|im anhang|anhang|angeh(ae|ä)ngt\w*|beiliegend\w*|anbei)\b",
    re.IGNORECASE,
)


def _mentions_attachment(text: str) -> bool:
    return bool(_ATTACHMENT_WORDS.search(text or ""))


@dataclass
class Evaluation:
    findings: list[Finding] = field(default_factory=list)
    plan: ChainPlan | None = None
    cost_center_suggestions: list[dict] = field(default_factory=list)
    supplier_candidates: list[dict] = field(default_factory=list)


def is_confirmed(prov: dict | None) -> bool:
    return bool(prov) and prov.get("status") == "confirmed"


def is_clerk(prov: dict | None) -> bool:
    return bool(prov) and prov.get("source") == "clerk"


def lines_of(session: Session, req: Requisition) -> list[LineItem]:
    return list(
        session.exec(
            select(LineItem).where(LineItem.requisition_id == req.id).order_by(LineItem.position)
        )
    )


def evaluate(session: Session, req: Requisition, md: MasterData | None = None) -> Evaluation:
    md = md or MasterData.load(session)
    ev = Evaluation()
    f = ev.findings
    prov = dict(req.provenance or {})
    lines = lines_of(session, req)
    email = session.get(Email, req.email_id)

    if req.message_kind == "not_a_purchase_request":
        f.append(
            Finding(
                "not_a_purchase_request",
                "blocking",
                "This email doesn't look like a purchase request. Close it, or acknowledge and fill in the details.",
            )
        )

    if (
        email
        and _mentions_attachment(email.body_text)
        and not session.exec(select(Attachment.id).where(Attachment.email_id == email.id)).first()
    ):
        f.append(
            Finding(
                "attachment_missing",
                "warning",
                "The email refers to an attachment, but nothing is attached. Ask the requester to resend it.",
                field="attachments",
            )
        )

    # -- requester ---------------------------------------------------------------
    requester = md.employees.get(req.requester_id) if req.requester_id else None
    if requester is None:
        who = (
            f"{email.from_name} <{email.from_email}>"
            if email and email.from_name
            else (email.from_email if email else "?")
        )
        f.append(
            Finding(
                "requester_unknown",
                "blocking",
                f"The sender {who} is not a known employee, so the request has no requester. Pick one.",
                field="requester",
            )
        )
    if req.on_behalf_of_text and not is_confirmed(prov.get("requester")):
        f.append(
            Finding(
                "on_behalf_of",
                "warning",
                f'The email says it is on behalf of "{req.on_behalf_of_text}". Check the requester; '
                f"it decides who may not approve.",
                field="requester",
            )
        )

    # -- supplier ----------------------------------------------------------------
    suppliers = list(md.suppliers.values())
    sp = dict(prov.get("supplier") or {})
    if is_clerk(sp) and req.supplier_id in md.suppliers:
        pass  # the clerk decided
    else:
        m = match_supplier(req.supplier_name_doc, req.supplier_vat_doc, suppliers)
        req.supplier_id = m.supplier_id
        ev.supplier_candidates = m.candidates
        codes = {x.code for x in m.findings}
        if m.method == "vat":
            sp.update(
                status="confirmed", source="master_data", reason="VAT ID matches the master data."
            )
        elif m.method == "name_exact":
            sp.update(
                status="from_document",
                source="master_data",
                reason="Matched by name only; no VAT ID to confirm.",
            )
        elif "supplier_conflict" in codes:
            sp.update(status="conflict", reason="Name and VAT ID point to different suppliers.")
        else:
            sp.update(status="missing", reason=m.findings[0].message if m.findings else None)
        if sp.get("grounded") is False and m.method != "vat":
            sp["status"] = "unverified"
        f.extend(m.findings)
    if req.supplier_id and req.supplier_id in md.suppliers:
        f.extend(supplier_status_findings(md.suppliers[req.supplier_id]))
    prov["supplier"] = sp

    # -- cost center -------------------------------------------------------------
    cp = dict(prov.get("cost_center") or {})
    if is_clerk(cp) and req.cost_center_code in md.cost_centers:
        pass
    else:
        code, cc_findings = match_cost_center(req.cost_center_doc, md.cost_centers)
        req.cost_center_code = code
        if code:
            cp.update(
                status="unverified" if cp.get("grounded") is False else "from_document",
                source="document",
            )
        else:
            cp.update(status="missing", reason=cc_findings[0].message)
            ev.cost_center_suggestions = cost_center_suggestions(
                req.cost_center_text, requester, md.cost_centers
            )
            for fd in cc_findings:
                fd.details["suggestions"] = ev.cost_center_suggestions
        f.extend(cc_findings)
    prov["cost_center"] = cp

    # -- currency ----------------------------------------------------------------
    if not req.currency:
        hint = (
            md.suppliers[req.supplier_id].default_currency
            if req.supplier_id in md.suppliers
            else None
        )
        f.append(
            Finding(
                "currency_missing",
                "blocking",
                "No currency is stated."
                + (f" The supplier usually quotes in {hint}." if hint else ""),
                field="currency",
                details={"suggestion": hint},
            )
        )
    elif req.currency not in md.fx:
        f.append(
            Finding(
                "currency_unsupported",
                "blocking",
                f"{req.currency} has no exchange rate in the master data.",
                field="currency",
            )
        )

    # -- amounts -----------------------------------------------------------------
    rec = reconcile(
        [
            LineIn(
                position=ln.position,
                kind=ln.kind,
                description=ln.description,
                quantity=ln.quantity,
                unit_price=ln.unit_price,
                price_basis=ln.price_basis,
                stated_line_total=ln.stated_line_total,
                quantity_approximate=ln.quantity_approximate,
            )
            for ln in lines
        ],
        [
            StatedTotalIn(
                label=st.get("label", "Total"),
                amount=Decimal(str(st["amount"])),
                includes_vat=st.get("includes_vat", "unclear"),
                approximate=bool(st.get("approximate")),
                overridden=bool(st.get("overridden")),
            )
            for st in req.stated_totals
        ],
        req.vat_amount,
        req.vat_rate,
        req.currency,
    )
    f.extend(rec.findings)
    req.approval_amount = rec.approval_amount
    req.po_total = rec.po_total
    req.approval_amount_chf = None
    req.fx_rate = None
    if rec.approval_amount is not None and req.currency in md.fx:
        conv = to_chf(rec.approval_amount, req.currency, md.fx)
        if conv:
            req.approval_amount_chf, req.fx_rate = conv

    no_unit = [ln.position for ln in lines if not ln.unit and ln.kind == "item"]
    if no_unit:
        which = (
            f"Line {no_unit[0]} has"
            if len(no_unit) == 1
            else "Lines " + ", ".join(map(str, no_unit)) + " have"
        )
        f.append(
            Finding(
                "unit_missing",
                "warning",
                f"{which} no unit; the ERP needs one to book the order.",
                field="line_items.unit",
                details={"positions": no_unit},
                blocks_order=True,
            )
        )

    # -- doubt from grounding and decision checks --------------------------------
    high, low = float(get_setting(session, "check_high")), float(get_setting(session, "check_low"))

    def doubt(path: str, label: str, p: dict, routing: bool) -> None:
        if is_clerk(p) or (path == "supplier" and is_confirmed(p)):
            return
        if p.get("grounded") is False:
            f.append(
                Finding(
                    "unverified_value",
                    "blocking" if routing else "warning",
                    f"{label}: {p.get('reason') or 'could not be verified against the source'}. "
                    f"Check it against the source and confirm or correct it.",
                    field=path,
                )
            )
        prob = p.get("check")
        if prob is not None and prob < high:
            sev = "blocking" if (routing and prob < low) else "warning"
            f.append(
                Finding(
                    "check_doubt",
                    sev,  # type: ignore[arg-type]
                    f"{label}: the independent check rates this value only {prob:.0%} likely to "
                    f"match the document.",
                    field=path,
                    details={"probability": prob},
                )
            )

    for ln in lines:
        for fld, p in (ln.provenance or {}).items():
            label = f"Line {ln.position} {LINE_FIELD_LABELS.get(fld, fld)}"
            doubt(f"line.{ln.position}.{fld}", label, p, fld in ROUTING_LINE_FIELDS)
    for key, p in prov.items():
        if key.startswith("stated_totals"):
            doubt(key, "Stated total", p, True)
        elif key in HEADER_LABELS:
            if (key == "supplier" and not req.supplier_id) or (
                key == "cost_center" and not req.cost_center_code
            ):
                continue  # already reported as missing/unknown
            doubt(key, HEADER_LABELS[key], p, key in ROUTING_HEADER_FIELDS)
        elif key == "po_total":
            doubt(key, "Net total", p, True)

    # -- dates, validity, claims -------------------------------------------------
    sent = email.sent_date_local if email else None
    if req.delivery_date is None:
        if req.delivery_date_suggested:
            f.append(
                Finding(
                    "delivery_date_suggested",
                    "warning",
                    f'Requested "{req.delivery_date_text.rstrip(". ")}". Suggested {req.delivery_date_suggested:%d %b %Y} '
                    f"from the email date; confirm or change it before ordering.",
                    field="delivery_date",
                    blocks_order=True,
                )
            )
        else:
            f.append(
                Finding(
                    "delivery_date_missing",
                    "warning",
                    "No requested delivery date"
                    + (
                        f' (the email says "{req.delivery_date_text.rstrip(". ")}")'
                        if req.delivery_date_text
                        else ""
                    )
                    + ". It doesn't block approval, but the ERP needs one before ordering.",
                    field="delivery_date",
                    blocks_order=True,
                )
            )
    elif sent and req.delivery_date < sent:
        f.append(
            Finding(
                "delivery_date_past",
                "warning",
                f"The delivery date {req.delivery_date} is before the email date.",
                field="delivery_date",
            )
        )
    if req.quote_valid_until and sent and req.quote_valid_until < sent:
        f.append(
            Finding(
                "quote_expired",
                "warning",
                f"The quote expired on {req.quote_valid_until:%d %b %Y}, before the request was sent "
                f"({sent:%d %b %Y}). Prices may no longer hold.",
                field="quote_valid_until",
            )
        )
    if req.prior_approval_claim:
        f.append(
            Finding(
                "bypass_claim",
                "warning",
                f'The email claims prior approval ("{req.prior_approval_claim}"). Verbal approvals don\'t '
                f"count; the full approval chain still runs.",
                field="approval_chain",
            )
        )

    # -- approval chain preview --------------------------------------------------
    if req.approval_amount_chf is not None and req.cost_center_code and requester is not None:
        ev.plan = plan_chain(
            req.approval_amount_chf, req.cost_center_code, requester.id, md, req.manual_approvers
        )
        req.band_position = ev.plan.band.position if ev.plan.band else None
        f.extend(ev.plan.findings)
    else:
        req.band_position = None

    po = dict(prov.get("po_total") or {})
    if req.po_total is not None:
        po.setdefault("status", "computed")
        po["reason"] = f"Sum of the lines: {fmt(req.po_total, req.currency)}"
        prov["po_total"] = po

    req.provenance = prov
    req.updated_at = utcnow()
    session.add(req)
    sync_issues(session, req, f, origin="evaluate")
    return ev


def sync_issues(
    session: Session, req: Requisition, findings: list[Finding], *, origin: str
) -> None:
    """Make the stored issues of one origin match `findings`, keeping clerk acknowledgements."""
    existing = list(
        session.exec(select(Issue).where(Issue.requisition_id == req.id, Issue.origin == origin))
    )
    by_key = {(i.code, i.field): i for i in existing}
    seen: set[tuple[str, str | None]] = set()
    for fd in findings:
        if fd.key in seen:
            # Two findings for the same field and code: merge messages.
            issue = by_key[fd.key]
            if fd.message not in issue.message:
                issue.message += " " + fd.message
            continue
        seen.add(fd.key)
        issue = by_key.get(fd.key)
        if issue is None:
            issue = Issue(
                requisition_id=req.id,
                code=fd.code,
                field=fd.field,
                origin=origin,
                severity=fd.severity,
                message="",
            )
            by_key[fd.key] = issue
        if issue.message != fd.message and issue.status != "open":
            # The facts changed since it was acknowledged/resolved: ask again.
            issue.status, issue.resolved_by, issue.resolved_at, issue.resolution_note = (
                "open",
                None,
                None,
                None,
            )
        issue.message = fd.message
        issue.severity = fd.severity
        issue.details = fd.details
        issue.blocks_order = fd.blocks_order
        session.add(issue)
    for key, issue in by_key.items():
        if key not in seen and issue.status != "resolved":
            issue.status = "resolved"
            issue.resolved_by = "system"
            issue.resolved_at = utcnow()
            issue.resolution_note = "No longer applies."
            session.add(issue)


def add_findings(session: Session, req: Requisition, findings: list[Finding], origin: str) -> None:
    """Append sticky issues (ingest/order); does not touch issues of other origins."""
    for fd in findings:
        session.add(
            Issue(
                requisition_id=req.id,
                code=fd.code,
                severity=fd.severity,
                field=fd.field,
                message=fd.message,
                details=fd.details,
                blocks_order=fd.blocks_order,
                origin=origin,
            )
        )


def open_issues(session: Session, req: Requisition) -> list[Issue]:
    return list(
        session.exec(select(Issue).where(Issue.requisition_id == req.id, Issue.status == "open"))
    )


def has_open_blocking(session: Session, req: Requisition) -> bool:
    return any(i.severity == "blocking" for i in open_issues(session, req))
