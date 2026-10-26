"""Purchase orders (brief section 8): only from APPROVED, only once the ERP's required
fields are present, idempotent, and a 422 or an outage never loses the requisition."""

from decimal import Decimal

from sqlmodel import Session, select

from app.db.models import Issue, PurchaseOrder, Requisition, utcnow
from app.domain.master import MasterData
from app.domain.reconcile import fmt
from app.domain.workflow import State
from app.erp.client import post_purchase_order
from app.services.audit import log_event, notify, transition
from app.services.evaluate import is_clerk, lines_of


def order_blockers(session: Session, req: Requisition, md: MasterData | None = None) -> list[str]:
    md = md or MasterData.load(session)
    problems: list[str] = []
    if req.state != State.APPROVED:
        problems.append("The requisition is not fully approved.")
    if req.supplier_id not in md.suppliers:
        problems.append("No supplier.")
    elif md.suppliers[req.supplier_id].status != "active":
        problems.append(
            f"Supplier {md.suppliers[req.supplier_id].name} is {md.suppliers[req.supplier_id].status}."
        )
    if not req.currency:
        problems.append("No currency.")
    if req.delivery_date is None:
        problems.append("No confirmed delivery date (the ERP requires one).")
    if req.po_total is None:
        problems.append("The total can't be computed.")
    lines = lines_of(session, req)
    if not lines:
        problems.append("No line items.")
    for ln in lines:
        if ln.quantity is None or ln.unit_price is None or not ln.unit or not ln.description:
            problems.append(
                f"Line {ln.position} needs a description, quantity, unit and unit price."
            )
    return problems


def build_payload(session: Session, req: Requisition) -> dict:
    lines = []
    for ln in lines_of(session, req):
        basis = ln.price_basis or Decimal(1)
        unit_price = ln.unit_price / basis  # type: ignore[operator]
        if ln.kind == "discount":
            unit_price = -abs(unit_price)
        item = {
            "item_name": ln.description,
            "quantity": float(ln.quantity),  # type: ignore[arg-type]
            "unit_price": float(round(unit_price, 6)),
            "unit": ln.unit,
        }
        if ln.item_code:
            item["item_code"] = ln.item_code
        lines.append(item)
    payload = {
        "supplier_id": req.supplier_id,
        "currency": req.currency,
        "total": float(req.po_total),  # type: ignore[arg-type]
        "requested_delivery_date": req.delivery_date.isoformat() if req.delivery_date else None,
        "cost_centre": req.cost_center_code,
        "requisition_reference": req.public_id,
        "line_items": lines,
    }
    # A GL account goes to the ERP only once a human confirmed it; a suggestion stays a suggestion.
    if req.gl_account and is_clerk(req.provenance.get("gl_account")):
        payload["gl_account"] = req.gl_account
    if req.vat_amount is not None:
        payload["tax_amount"] = float(req.vat_amount)
    return payload


def _clear_order_issues(session: Session, req: Requisition, note: str) -> None:
    for issue in session.exec(
        select(Issue).where(
            Issue.requisition_id == req.id, Issue.origin == "order", Issue.status == "open"
        )
    ):
        issue.status, issue.resolved_by, issue.resolved_at, issue.resolution_note = (
            "resolved",
            "system",
            utcnow(),
            note,
        )
        session.add(issue)


def place_order(session: Session, req: Requisition, actor: str) -> PurchaseOrder | None:
    md = MasterData.load(session)
    blockers = order_blockers(session, req, md)
    if blockers:
        raise ValueError(" ".join(blockers))
    payload = build_payload(session, req)
    res = post_purchase_order(payload, req.idempotency_key or req.public_id)
    po = PurchaseOrder(
        requisition_id=req.id, http_status=res.status, request=payload, response=res.body
    )

    if res.status in (200, 201):
        po.po_number = res.body.get("po_number")
        po.warnings = res.body.get("warnings") or []
        session.add(po)
        _clear_order_issues(session, req, f"Ordered as {po.po_number}.")
        log_event(
            session,
            req,
            actor,
            "ordered",
            f"Booked in the ERP as {po.po_number} ({req.currency} {fmt(req.po_total)})"
            + (f" with {len(po.warnings)} warning(s)" if po.warnings else ""),
            {"warnings": po.warnings},
        )
        transition(session, req, State.ORDERED, actor, f"PO {po.po_number}")
        if req.requester_id:
            notify(
                session,
                req,
                recipient_id=req.requester_id,
                recipient_label=md.name(req.requester_id),
                subject=f"Ordered: {req.public_id} {req.title or ''}".strip(),
                body=f"Your request was ordered from {md.suppliers[req.supplier_id].name} as {po.po_number}.",  # type: ignore[index]
            )
        return po

    session.add(po)
    _clear_order_issues(session, req, "Superseded by a newer attempt.")
    if res.status is None:
        message = f"{res.error}. Nothing was booked; try again once the ERP is up."
    else:
        problems = res.body.get("problems") or [res.body.get("error", f"HTTP {res.status}")]
        message = f"The ERP rejected the order (HTTP {res.status}): " + "; ".join(problems)
    session.add(
        Issue(
            requisition_id=req.id,
            code="order_failed",
            severity="warning",
            blocks_order=True,
            field="order",
            message=message,
            origin="order",
        )
    )
    log_event(session, req, actor, "order_failed", message)
    return po


def try_auto_order(session: Session, req: Requisition) -> None:
    """After the last approval: order straight away if everything the ERP needs is there."""
    if not order_blockers(session, req):
        place_order(session, req, "system")
