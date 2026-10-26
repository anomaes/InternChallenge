"""Clerk actions on requisitions. Every change is validated against master data, logged
to the audit trail, and followed by a deterministic re-evaluation."""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api import schemas as S
from app.db.models import Email, Issue, LineItem, Requisition, Supplier, utcnow
from app.db.session import get_session
from app.domain.master import MasterData
from app.domain.workflow import EDITABLE, State, TransitionError
from app.privacy.redact import Redactor
from app.services.audit import log_event, transition
from app.services.bus import bus
from app.services.evaluate import evaluate, has_open_blocking, lines_of
from app.services.orders import place_order
from app.services.pipeline import reprocess, run_decision_checks
from app.services.routing import (
    restart_if_routing_changed,
    route,
    routing_snapshot,
    supersede_run,
)
from app.services.serialize import ACKABLE_BLOCKING, detail, summaries

router = APIRouter(prefix="/api", tags=["requisitions"])

CLERK = "clerk"
FIELD_PROV = {
    "requester_id": "requester",
    "supplier_id": "supplier",
    "cost_center_code": "cost_center",
    "currency": "currency",
    "delivery_date": "delivery_date",
    "gl_account": "gl_account",
    "vat_amount": "vat_amount",
}
FIELD_LABEL = {
    "title": "title",
    "requester_id": "requester",
    "supplier_id": "supplier",
    "cost_center_code": "cost center",
    "currency": "currency",
    "delivery_date": "delivery date",
    "gl_account": "GL account",
    "vat_amount": "VAT amount",
}


def _get(session: Session, req_id: int) -> Requisition:
    req = session.get(Requisition, req_id)
    if req is None:
        raise HTTPException(404, "No such requisition.")
    return req


def _editable(req: Requisition) -> None:
    if State(req.state) not in EDITABLE:
        raise HTTPException(409, f"A requisition in state {req.state} can't be edited.")


def _done(session: Session, req: Requisition) -> S.ReqDetail:
    req.updated_at = utcnow()
    session.add(req)
    session.commit()
    session.refresh(req)
    bus.publish("requisition", id=req.id, state=req.state)
    return detail(session, req)


def _clerk_prov(req: Requisition, key: str, reason: str) -> None:
    prov = dict(req.provenance)
    prov[key] = {
        **prov.get(key, {}),
        "status": "confirmed",
        "source": "clerk",
        "reason": reason,
        "grounded": True,
    }
    req.provenance = prov


@router.get("/requisitions", response_model=list[S.ReqSummary])
def list_requisitions(
    state: str | None = None, session: Session = Depends(get_session)
) -> list[S.ReqSummary]:
    q = select(Requisition).order_by(Requisition.id.desc())  # type: ignore[union-attr]
    if state:
        q = q.where(Requisition.state.in_(state.split(",")))  # type: ignore[attr-defined]
    return summaries(session, list(session.exec(q)))


@router.get("/requisitions/{req_id}", response_model=S.ReqDetail)
def get_requisition(req_id: int, session: Session = Depends(get_session)) -> S.ReqDetail:
    return detail(session, _get(session, req_id))


@router.patch("/requisitions/{req_id}", response_model=S.ReqDetail)
def patch_fields(
    req_id: int, body: S.FieldsPatch, session: Session = Depends(get_session)
) -> S.ReqDetail:
    req = _get(session, req_id)
    _editable(req)
    md = MasterData.load(session)
    before = routing_snapshot(req)
    provided = body.model_dump(exclude_unset=True, exclude={"clear"})
    for name in body.clear:
        if name in FIELD_LABEL:
            provided[name] = None
    validators = {
        "requester_id": (md.employees, "employee"),
        "supplier_id": (md.suppliers, "supplier"),
        "cost_center_code": (md.cost_centers, "cost center"),
        "currency": (md.fx, "currency with an exchange rate"),
        "gl_account": (md.gl_accounts, "GL account"),
    }
    changed: list[str] = []
    for name, value in provided.items():
        if name in validators and value is not None and value not in validators[name][0]:
            raise HTTPException(422, f"{value} is not a known {validators[name][1]}.")
        old = getattr(req, name)
        if old == value:
            continue
        setattr(req, name, value)
        changed.append(FIELD_LABEL[name])
        if name == "requester_id":
            req.requester_source = "clerk"
        if name in FIELD_PROV:
            _clerk_prov(
                req,
                FIELD_PROV[name],
                f"Set by the clerk (was {old if old is not None else 'empty'}).",
            )
        log_event(
            session,
            req,
            CLERK,
            "field_edited",
            f"{FIELD_LABEL[name].capitalize()}: {old or '—'} → {value or '—'}",
        )
    if changed:
        restart_if_routing_changed(session, req, before, CLERK, ", ".join(changed))
    return _done(session, req)


@router.put("/requisitions/{req_id}/lines", response_model=S.ReqDetail)
def put_lines(
    req_id: int, body: list[S.LineIn], session: Session = Depends(get_session)
) -> S.ReqDetail:
    req = _get(session, req_id)
    _editable(req)
    before = routing_snapshot(req)
    existing = {ln.id: ln for ln in lines_of(session, req)}
    keep: set[int] = set()
    edits: list[str] = []
    for pos, data in enumerate(body, start=1):
        if data.kind not in ("item", "freight", "surcharge", "discount"):
            raise HTTPException(422, f"Unknown line kind {data.kind}.")
        if data.quantity is not None and data.quantity <= 0 and data.kind != "discount":
            raise HTTPException(422, f"Line {pos}: quantity must be positive.")
        ln = existing.get(data.id) if data.id else None
        if ln is None:
            ln = LineItem(requisition_id=req.id, position=pos, provenance={})  # type: ignore[arg-type]
            edits.append(f"added line {pos}")
        keep.add(ln.id) if ln.id else None
        prov = dict(ln.provenance)
        basis = data.price_basis if data.price_basis not in (None, Decimal(1)) else None
        for fld, value in (
            ("kind", data.kind),
            ("description", data.description.strip()),
            ("item_code", data.item_code or None),
            ("quantity", data.quantity),
            ("unit", data.unit or None),
            ("unit_price", data.unit_price),
            ("price_basis", basis),
        ):
            if getattr(ln, fld) != value:
                if ln.id:
                    edits.append(
                        f"line {pos} {fld.replace('_', ' ')}: {getattr(ln, fld)} → {value}"
                    )
                setattr(ln, fld, value)
                prov[fld] = {"status": "confirmed", "source": "clerk", "grounded": True}
                if fld == "quantity":
                    ln.quantity_approximate = False
                if fld in ("quantity", "unit_price", "price_basis") and ln.id:
                    ln.stated_line_total = None  # it described the document's old values
        ln.position = pos
        ln.provenance = prov
        session.add(ln)
    for line_id, ln in existing.items():
        if line_id not in keep:
            edits.append(f"removed line {ln.position} ({ln.description[:30]})")
            session.delete(ln)
    session.flush()
    if edits:
        log_event(session, req, CLERK, "lines_edited", "; ".join(edits)[:900])
        restart_if_routing_changed(session, req, before, CLERK, "the line items")
    return _done(session, req)


@router.post("/requisitions/{req_id}/confirm", response_model=S.ReqDetail)
def confirm_field(
    req_id: int, body: S.ConfirmIn, session: Session = Depends(get_session)
) -> S.ReqDetail:
    """Accept a suggested value, or vouch for an unverified one after checking the source."""
    req = _get(session, req_id)
    _editable(req)
    before = routing_snapshot(req)
    fld = body.field
    if fld.startswith("line."):
        _, pos, name = fld.split(".", 2)
        ln = next((x for x in lines_of(session, req) if x.position == int(pos)), None)
        if ln is None:
            raise HTTPException(404, "No such line.")
        prov = dict(ln.provenance)
        prov[name] = {
            **prov.get(name, {}),
            "status": "confirmed",
            "source": "clerk",
            "grounded": True,
        }
        ln.provenance = prov
        if name == "quantity":
            ln.quantity_approximate = False
        session.add(ln)
        log_event(
            session, req, CLERK, "confirmed", f"Confirmed line {pos} {name.replace('_', ' ')}."
        )
    elif fld == "delivery_date":
        if req.delivery_date is None and req.delivery_date_suggested is None:
            raise HTTPException(409, "There is no suggested delivery date to confirm.")
        if req.delivery_date is None:
            req.delivery_date = req.delivery_date_suggested
        _clerk_prov(req, "delivery_date", "Confirmed by the clerk.")
        log_event(session, req, CLERK, "confirmed", f"Confirmed delivery date {req.delivery_date}.")
    elif fld == "gl_account":
        if not req.gl_account_suggested:
            raise HTTPException(409, "There is no GL suggestion to confirm.")
        req.gl_account = req.gl_account or req.gl_account_suggested
        _clerk_prov(req, "gl_account", "Suggestion confirmed by the clerk.")
        log_event(session, req, CLERK, "confirmed", f"Confirmed GL account {req.gl_account}.")
    elif fld == "supplier":
        if not req.supplier_id:
            raise HTTPException(409, "No supplier is matched yet; pick one instead.")
        _clerk_prov(req, "supplier", "Match confirmed by the clerk.")
        log_event(session, req, CLERK, "confirmed", f"Confirmed supplier {req.supplier_id}.")
    elif fld in (
        "requester",
        "cost_center",
        "currency",
        "supplier_vat",
        "vat_amount",
        "quote_valid_until",
        "po_total",
    ) or fld.startswith("stated_totals."):
        _clerk_prov(req, fld, "Checked against the source by the clerk.")
        log_event(session, req, CLERK, "confirmed", f"Confirmed {fld.replace('_', ' ')}.")
    else:
        raise HTTPException(422, f"Can't confirm {fld}.")
    restart_if_routing_changed(session, req, before, CLERK, fld.replace("_", " "))
    return _done(session, req)


@router.post("/requisitions/{req_id}/stated-totals/{index}/override", response_model=S.ReqDetail)
def override_stated_total(
    req_id: int, index: int, body: S.NoteIn, session: Session = Depends(get_session)
) -> S.ReqDetail:
    """Resolve an amount conflict by deciding the lines are right and the printed figure is wrong."""
    req = _get(session, req_id)
    _editable(req)
    totals = [dict(t) for t in req.stated_totals]
    if not 0 <= index < len(totals):
        raise HTTPException(404, "No such stated total.")
    totals[index]["overridden"] = True
    req.stated_totals = totals
    t = totals[index]
    log_event(
        session,
        req,
        CLERK,
        "amount_decided",
        f'Decided the lines are correct; ignoring the printed "{t["label"]}" of {t["amount"]}.'
        + (f" Note: {body.note}" if body.note else ""),
    )
    evaluate(session, req)
    return _done(session, req)


@router.post("/requisitions/{req_id}/issues/{issue_id}/acknowledge", response_model=S.ReqDetail)
def acknowledge_issue(
    req_id: int, issue_id: int, body: S.NoteIn, session: Session = Depends(get_session)
) -> S.ReqDetail:
    req = _get(session, req_id)
    issue = session.get(Issue, issue_id)
    if issue is None or issue.requisition_id != req.id:
        raise HTTPException(404, "No such issue.")
    if issue.severity == "blocking" and issue.code not in ACKABLE_BLOCKING:
        raise HTTPException(
            409, "This issue can't be waved through; fix the underlying value instead."
        )
    issue.status = "acknowledged"
    issue.resolved_by = CLERK
    issue.resolved_at = utcnow()
    issue.resolution_note = body.note
    session.add(issue)
    log_event(
        session,
        req,
        CLERK,
        "acknowledged",
        f"Acknowledged: {issue.message[:160]}" + (f" ({body.note})" if body.note else ""),
    )
    return _done(session, req)


@router.post("/requisitions/{req_id}/approvers", response_model=S.ReqDetail)
def assign_approver(
    req_id: int, body: S.AssignApproverIn, session: Session = Depends(get_session)
) -> S.ReqDetail:
    req = _get(session, req_id)
    _editable(req)
    md = MasterData.load(session)
    if body.employee_id not in md.employees:
        raise HTTPException(422, "Unknown employee.")
    if body.employee_id == req.requester_id:
        raise HTTPException(422, "The requester can't approve their own requisition.")
    if md.employees[body.employee_id].role == "requester_only":
        raise HTTPException(422, f"{md.name(body.employee_id)} has no approval role.")
    before = routing_snapshot(req)
    req.manual_approvers = {**req.manual_approvers, str(body.position): body.employee_id}
    log_event(
        session,
        req,
        CLERK,
        "approver_assigned",
        f"Step {body.position} assigned to {md.name(body.employee_id)}.",
    )
    restart_if_routing_changed(session, req, before, CLERK, "the approver assignment")
    return _done(session, req)


@router.post("/requisitions/{req_id}/submit", response_model=S.ReqDetail)
def submit(req_id: int, session: Session = Depends(get_session)) -> S.ReqDetail:
    """Send to approval (from Needs review), or resubmit a corrected rejected requisition."""
    req = _get(session, req_id)
    if req.state not in (State.NEEDS_REVIEW, State.REJECTED):
        raise HTTPException(
            409, "Only requisitions in review or rejected ones can be sent to approval."
        )
    evaluate(session, req)
    session.flush()
    if has_open_blocking(session, req):
        session.commit()
        raise HTTPException(409, "Resolve the blocking issues first.")
    was_rejected = req.state == State.REJECTED
    route(
        session,
        req,
        CLERK,
        reason="resubmitted after correction: chain restarts from step 1"
        if was_rejected
        else "sent to approval by the clerk",
    )
    return _done(session, req)


@router.post("/requisitions/{req_id}/reject", response_model=S.ReqDetail)
def clerk_reject(
    req_id: int, body: S.ReasonIn, session: Session = Depends(get_session)
) -> S.ReqDetail:
    req = _get(session, req_id)
    if not body.reason.strip():
        raise HTTPException(422, "A rejection needs a reason.")
    if req.state not in (State.NEEDS_REVIEW, State.PENDING_APPROVAL):
        raise HTTPException(409, "Only requisitions in review or approval can be rejected.")
    supersede_run(session, req)
    req.rejection_reason = body.reason.strip()
    req.rejected_by = None
    log_event(session, req, CLERK, "rejected", f"Rejected by purchasing: {req.rejection_reason}")
    transition(session, req, State.REJECTED, CLERK, req.rejection_reason)
    return _done(session, req)


def _resolve_link_issues(session: Session, req: Requisition, note: str) -> None:
    for issue in session.exec(
        select(Issue).where(
            Issue.requisition_id == req.id, Issue.origin == "ingest", Issue.status == "open"
        )
    ):
        if issue.field == "link":
            issue.status, issue.resolved_by, issue.resolved_at, issue.resolution_note = (
                "resolved",
                CLERK,
                utcnow(),
                note,
            )
            session.add(issue)


@router.post("/requisitions/{req_id}/duplicate", response_model=S.ReqDetail)
def duplicate_action(
    req_id: int, body: S.DuplicateActionIn, session: Session = Depends(get_session)
) -> S.ReqDetail:
    req = _get(session, req_id)
    original = session.get(Requisition, req.linked_to_id) if req.linked_to_id else None
    if body.action == "keep":
        _resolve_link_issues(session, req, "Kept as a separate requisition.")
        req.link_type = req.link_type or "related"
        log_event(
            session,
            req,
            CLERK,
            "kept_both",
            "Kept as a separate requisition"
            + (f" (linked to {original.public_id})" if original else "")
            + ".",
        )
        evaluate(session, req)
        return _done(session, req)
    if body.action == "close":
        if req.state not in (State.NEEDS_REVIEW, State.PENDING_APPROVAL):
            raise HTTPException(409, "Only requisitions in review or approval can be closed.")
        supersede_run(session, req)
        _resolve_link_issues(session, req, "Closed as a duplicate.")
        msg = (
            f"Closed as a duplicate of {original.public_id}."
            if original
            else "Closed as a duplicate."
        )
        log_event(session, req, CLERK, "closed_duplicate", msg)
        transition(session, req, State.CLOSED_DUPLICATE, CLERK, msg)
        if original:
            log_event(
                session,
                original,
                CLERK,
                "duplicate_closed",
                f"{req.public_id} was closed as a duplicate of this requisition.",
            )
        return _done(session, req)
    if body.action == "apply_correction":
        if original is None:
            raise HTTPException(409, "Link this message to the original request first.")
        if original.state in (State.ORDERED, State.CLOSED_DUPLICATE):
            raise HTTPException(
                409,
                f"{original.public_id} is already {original.state.lower()}; it can't be corrected.",
            )
        _apply_correction(session, req, original)
        return _done(session, req)
    raise HTTPException(422, "Unknown action.")


def _apply_correction(session: Session, corr: Requisition, original: Requisition) -> None:
    """Copy what the correction states onto the original; the original's chain restarts."""
    copied: list[str] = []
    for name in (
        "supplier_name_doc", "supplier_vat_doc", "supplier_address_doc", "supplier_id", "cost_center_doc",
        "cost_center_code", "cost_center_text", "currency", "delivery_date", "delivery_date_text",
        "delivery_date_suggested", "quote_reference", "quote_date", "quote_valid_until", "vat_amount", "vat_rate",
    ):  # fmt: skip
        value = getattr(corr, name)
        if value is not None and value != getattr(original, name):
            setattr(original, name, value)
            copied.append(name)
    prov = dict(original.provenance)
    for key in ("supplier", "cost_center", "currency", "delivery_date"):
        if key in corr.provenance:
            prov[key] = {**corr.provenance[key], "reason": f"From correction {corr.public_id}"}
    original.provenance = prov
    corr_lines = lines_of(session, corr)
    if corr_lines:
        for ln in lines_of(session, original):
            session.delete(ln)
        for ln in corr_lines:
            session.add(
                LineItem(
                    **ln.model_dump(exclude={"id", "requisition_id"}), requisition_id=original.id
                )
            )  # type: ignore[arg-type]
        original.stated_totals = corr.stated_totals
        copied.append("line items")
    session.flush()
    log_event(
        session,
        original,
        CLERK,
        "corrected",
        f"Corrected from {corr.public_id}: "
        + (", ".join(copied) or "nothing to copy; edit by hand"),
    )
    _resolve_link_issues(session, corr, f"Applied as a correction to {original.public_id}.")
    supersede_run(session, corr)
    corr.link_type = "correction"
    transition(
        session,
        corr,
        State.CLOSED_DUPLICATE,
        CLERK,
        f"applied as a correction to {original.public_id}",
    )
    if original.state in (
        State.PENDING_APPROVAL,
        State.APPROVED,
        State.REJECTED,
        State.NEEDS_REVIEW,
    ):
        route(
            session,
            original,
            CLERK,
            reason=f"corrected by {corr.public_id}: chain restarts from step 1",
        )
    session.add(original)
    bus.publish("requisition", id=original.id, state=original.state)


@router.post("/requisitions/{req_id}/link", response_model=S.ReqDetail)
def link_to(req_id: int, body: S.LinkIn, session: Session = Depends(get_session)) -> S.ReqDetail:
    """For a correction that doesn't say which request it corrects: the clerk picks it."""
    req = _get(session, req_id)
    target = session.exec(
        select(Requisition).where(Requisition.public_id == body.public_id.strip().upper())
    ).first()
    if target is None or target.id == req.id:
        raise HTTPException(404, "No such requisition.")
    _resolve_link_issues(session, req, f"Linked to {target.public_id} by the clerk.")
    req.linked_to_id = target.id
    req.link_type = "correction" if req.message_kind == "correction" else "duplicate"
    req.link_reason = "Linked by the clerk."
    session.add(
        Issue(
            requisition_id=req.id,  # type: ignore[arg-type]
            code="suspected_correction" if req.link_type == "correction" else "suspected_duplicate",
            severity="blocking",
            field="link",
            origin="ingest",
            message=f"Linked to {target.public_id} ({target.title or ''}). Decide: apply as correction, close as duplicate, or keep both.",
            details={"linked_to": target.public_id},
        )
    )
    log_event(session, req, CLERK, "linked", f"Linked to {target.public_id}.")
    return _done(session, req)


@router.post("/requisitions/{req_id}/order", response_model=S.ReqDetail)
def order(req_id: int, session: Session = Depends(get_session)) -> S.ReqDetail:
    req = _get(session, req_id)
    try:
        place_order(session, req, CLERK)
    except ValueError as err:
        raise HTTPException(409, str(err)) from err
    return _done(session, req)


@router.post("/requisitions/{req_id}/reprocess", response_model=S.OkOut)
def reprocess_requisition(req_id: int, session: Session = Depends(get_session)) -> S.OkOut:
    req = _get(session, req_id)
    if req.state != State.NEEDS_REVIEW:
        raise HTTPException(409, "Only requisitions in review can be re-processed.")
    try:
        transition(session, req, State.PROCESSING, CLERK, "re-run processing")
    except TransitionError as err:
        raise HTTPException(409, str(err)) from err
    reprocess(session, req, CLERK)
    return S.OkOut(message="Re-processing started.")


@router.post("/requisitions/{req_id}/rerun-checks", response_model=S.ReqDetail)
def rerun_checks(req_id: int, session: Session = Depends(get_session)) -> S.ReqDetail:
    req = _get(session, req_id)
    email = session.get(Email, req.email_id)
    assert email is not None
    run_decision_checks(session, req, Redactor().redact(email.source_text))
    evaluate(session, req)
    return _done(session, req)


@router.post("/suppliers", response_model=S.SupplierOut)
def create_supplier(
    body: S.SupplierCreateIn, session: Session = Depends(get_session)
) -> S.SupplierOut:
    """Created by the clerk from an unknown-supplier issue, never from extraction alone."""
    if not body.name.strip():
        raise HTTPException(422, "A supplier needs a name.")
    ids = [
        int(s.id.split("-")[1]) for s in session.exec(select(Supplier)) if s.id.startswith("SUP-")
    ]
    supplier = Supplier(
        id=f"SUP-{max(ids, default=0) + 1:03d}",
        name=body.name.strip(),
        vat_id=(body.vat_id or "").strip() or None,
        country=body.country,
        default_currency=body.default_currency,
        payment_terms_days=body.payment_terms_days,
        status="active",
        created_by_clerk=True,
    )
    session.add(supplier)
    session.flush()
    if body.requisition_id:
        req = _get(session, body.requisition_id)
        before = routing_snapshot(req)
        req.supplier_id = supplier.id
        _clerk_prov(req, "supplier", f"New supplier {supplier.id} created by the clerk.")
        log_event(
            session,
            req,
            CLERK,
            "supplier_created",
            f"Created supplier {supplier.name} ({supplier.id}) and assigned it.",
        )
        restart_if_routing_changed(session, req, before, CLERK, "supplier")
        _done(session, req)
    else:
        session.commit()
    return S.SupplierOut.model_validate(supplier, from_attributes=True)
