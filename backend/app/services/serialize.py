"""Build API responses. Read-only: the chain preview and suggestions come from the pure
domain functions, so a GET never writes."""

from collections import Counter

from sqlmodel import Session, select

from app.api import schemas as S
from app.db.models import (
    ApprovalStep,
    Attachment,
    Email,
    Event,
    Issue,
    LineItem,
    LLMRun,
    PurchaseOrder,
    Redaction,
    Requisition,
)
from app.domain.approval import plan_chain, role_label
from app.domain.master import MasterData
from app.domain.matching import cost_center_suggestions, match_supplier
from app.domain.reconcile import LineIn, line_value
from app.domain.workflow import LABELS, State
from app.services.orders import order_blockers

# Blocking issues a clerk may wave through after looking: they describe the email, not a
# value the chain routes on. Everything else is resolved by fixing the value.
ACKABLE_BLOCKING = {
    "extraction_failed",
    "not_a_purchase_request",
    "pipeline_error",
    "unverified_value",
    "check_doubt",
    "referenced_request_not_found",
    "unlinked_correction",
    "unlinked_repeat",
}
SEVERITY_ORDER = {"blocking": 0, "warning": 1, "info": 2}


def _supplier_out(s) -> S.SupplierOut:  # noqa: ANN001
    return S.SupplierOut.model_validate(s, from_attributes=True)


def _cc_out(code: str | None, md: MasterData) -> S.CostCenterOut | None:
    cc = md.cost_centers.get(code or "")
    if cc is None:
        return None
    dept = md.departments.get(cc.department)
    return S.CostCenterOut(
        code=cc.code,
        name=cc.name,
        owner_employee_id=cc.owner_employee_id,
        owner_name=md.name(cc.owner_employee_id),
        department=cc.department,
        department_name=dept.name if dept else cc.department,
        head_employee_id=dept.head_employee_id if dept else None,
        head_name=md.name(dept.head_employee_id) if dept else None,
    )


def _step_out(step: ApprovalStep, md: MasterData) -> S.StepOut:
    return S.StepOut(
        run=step.run,
        position=step.position,
        roles=step.roles,
        role_labels=[role_label(r) for r in step.roles],
        approver_id=step.approver_id,
        approver_name=md.name(step.approver_id) if step.approver_id else None,
        on_behalf_of_id=step.on_behalf_of_id,
        on_behalf_of_name=md.name(step.on_behalf_of_id) if step.on_behalf_of_id else None,
        note=step.note,
        assigned_manually=step.assigned_manually,
        status=step.status,
        decided_at=step.decided_at,
        comment=step.comment,
    )


def _issue_out(i: Issue) -> S.IssueOut:
    return S.IssueOut(
        **i.model_dump(exclude={"requisition_id"}),
        acknowledgeable=i.severity != "blocking" or i.code in ACKABLE_BLOCKING,
    )


class Context:
    """Bulk-loaded lookups so the list endpoint doesn't do N queries per row."""

    def __init__(self, session: Session, reqs: list[Requisition]) -> None:
        ids = [r.id for r in reqs]
        self.md = MasterData.load(session)
        self.issues: dict[int, list[Issue]] = {}
        for i in session.exec(select(Issue).where(Issue.requisition_id.in_(ids))):  # type: ignore[attr-defined]
            self.issues.setdefault(i.requisition_id, []).append(i)
        self.steps: dict[int, list[ApprovalStep]] = {}
        for s in session.exec(
            select(ApprovalStep)
            .where(ApprovalStep.requisition_id.in_(ids))
            .order_by(ApprovalStep.position)
        ):  # type: ignore[attr-defined]
            self.steps.setdefault(s.requisition_id, []).append(s)
        email_ids = [r.email_id for r in reqs]
        self.emails = {e.id: e for e in session.exec(select(Email).where(Email.id.in_(email_ids)))}  # type: ignore[union-attr]
        self.pos: dict[int, str] = {}
        for po in session.exec(
            select(PurchaseOrder).where(
                PurchaseOrder.requisition_id.in_(ids), PurchaseOrder.po_number.is_not(None)
            )
        ):  # type: ignore[attr-defined,union-attr]
            self.pos[po.requisition_id] = po.po_number  # type: ignore[assignment]
        linked = {r.linked_to_id for r in reqs if r.linked_to_id}
        self.public_ids = (
            {
                r.id: r.public_id
                for r in session.exec(select(Requisition).where(Requisition.id.in_(linked)))
            }
            if linked
            else {}
        )  # type: ignore[union-attr]


def summary(req: Requisition, ctx: Context) -> S.ReqSummary:
    md = ctx.md
    issues = [i for i in ctx.issues.get(req.id, []) if i.status == "open"]  # type: ignore[arg-type]
    counts = Counter(i.severity for i in issues)
    order_count = sum(1 for i in issues if i.blocks_order)
    top = sorted(issues, key=lambda i: (SEVERITY_ORDER.get(i.severity, 3), i.id or 0))
    steps = [s for s in ctx.steps.get(req.id, []) if s.run == req.approval_run]  # type: ignore[arg-type]
    active = next((s for s in steps if s.status == "active"), None)
    supplier = md.suppliers.get(req.supplier_id or "")
    requester = md.employees.get(req.requester_id or "")
    email = ctx.emails.get(req.email_id)
    return S.ReqSummary(
        id=req.id,  # type: ignore[arg-type]
        public_id=req.public_id,
        state=req.state,
        state_label=LABELS[State(req.state)],
        stage=req.stage,
        title=req.title,
        message_kind=req.message_kind,
        received_at=req.created_at,
        sent_at=email.sent_at if email else None,
        updated_at=req.updated_at,
        requester_id=req.requester_id,
        requester_name=requester.name if requester else None,
        requester_source=req.requester_source,
        supplier_id=req.supplier_id,
        supplier_name=supplier.name if supplier else None,
        supplier_name_doc=req.supplier_name_doc,
        supplier_status=(req.provenance.get("supplier") or {}).get("status"),
        supplier_blocked=bool(supplier and supplier.status == "blocked"),
        cost_center_code=req.cost_center_code,
        currency=req.currency,
        po_total=req.po_total,
        approval_amount=req.approval_amount,
        approval_amount_chf=req.approval_amount_chf,
        band_position=req.band_position,
        current_step=(
            S.CurrentStep(
                position=active.position,
                total=len(steps),
                approver_id=active.approver_id,
                approver_name=md.name(active.approver_id),
            )
            if active and req.state == State.PENDING_APPROVAL
            else None
        ),
        issue_counts=S.IssueCounts(
            blocking=counts["blocking"],
            warning=counts["warning"],
            info=counts["info"],
            order=order_count,
        ),
        top_issue=top[0].message if top and top[0].severity != "info" else None,
        top_issue_code=top[0].code if top and top[0].severity != "info" else None,
        linked_to_id=req.linked_to_id,
        linked_to_public_id=ctx.public_ids.get(req.linked_to_id) if req.linked_to_id else None,
        link_type=req.link_type,
        delivery_date=req.delivery_date,
        redaction_count=req.redaction_count,
        po_number=ctx.pos.get(req.id),  # type: ignore[arg-type]
        source_name=email.source_name if email else "",
    )


def summaries(session: Session, reqs: list[Requisition]) -> list[S.ReqSummary]:
    ctx = Context(session, reqs)
    return [summary(r, ctx) for r in reqs]


def detail(session: Session, req: Requisition) -> S.ReqDetail:
    ctx = Context(session, [req])
    md = ctx.md
    base = summary(req, ctx)
    email = ctx.emails[req.email_id]
    lines = list(
        session.exec(
            select(LineItem).where(LineItem.requisition_id == req.id).order_by(LineItem.position)
        )
    )
    issues = sorted(
        ctx.issues.get(req.id, []),
        key=lambda i: (i.status != "open", SEVERITY_ORDER.get(i.severity, 3), i.id),
    )  # type: ignore[arg-type]
    all_steps = ctx.steps.get(req.id, [])  # type: ignore[arg-type]
    current = (
        [s for s in all_steps if s.run == req.approval_run and s.status != "superseded"]
        if req.approval_run
        else []
    )
    if req.state in (State.REJECTED,):
        current = [s for s in all_steps if s.run == req.approval_run]
    history = [s for s in all_steps if s not in current]
    requester = md.employees.get(req.requester_id or "")

    steps_out = [_step_out(s, md) for s in current]
    preview = False
    if not steps_out and req.approval_amount_chf is not None and req.cost_center_code and requester:
        plan = plan_chain(
            req.approval_amount_chf, req.cost_center_code, requester.id, md, req.manual_approvers
        )
        preview = True
        steps_out = [
            S.StepOut(
                run=0,
                position=s.position,
                roles=s.roles,
                role_labels=[role_label(r) for r in s.roles],
                holder_id=s.holder_id,
                approver_id=s.approver_id,
                approver_name=md.name(s.approver_id) if s.approver_id else None,
                on_behalf_of_id=s.on_behalf_of_id,
                on_behalf_of_name=md.name(s.on_behalf_of_id) if s.on_behalf_of_id else None,
                note=s.note,
                assigned_manually=s.assigned_manually,
                status="planned",
            )
            for s in plan.steps
        ]

    sm = match_supplier(req.supplier_name_doc, req.supplier_vat_doc, list(md.suppliers.values()))
    attachments = list(session.exec(select(Attachment).where(Attachment.email_id == email.id)))
    events = list(
        session.exec(
            select(Event)
            .where(Event.requisition_id == req.id)
            .order_by(Event.at.desc(), Event.id.desc())
        )
    )  # type: ignore[attr-defined,union-attr]
    runs = list(
        session.exec(select(LLMRun).where(LLMRun.requisition_id == req.id).order_by(LLMRun.id))
    )
    pos = list(
        session.exec(
            select(PurchaseOrder)
            .where(PurchaseOrder.requisition_id == req.id)
            .order_by(PurchaseOrder.id)
        )
    )
    redactions = list(session.exec(select(Redaction).where(Redaction.email_id == email.id)))
    linked_from = list(session.exec(select(Requisition).where(Requisition.linked_to_id == req.id)))
    gl = md.gl_accounts

    def actor_name(a: str) -> str:
        return md.name(a) if a in md.employees else a.capitalize()

    open_blocking = any(i.status == "open" and i.severity == "blocking" for i in issues)
    return S.ReqDetail(
        **base.model_dump(),
        supplier=_supplier_out(md.suppliers[req.supplier_id])
        if req.supplier_id in md.suppliers
        else None,
        supplier_vat_doc=req.supplier_vat_doc,
        supplier_address_doc=req.supplier_address_doc,
        cost_center=_cc_out(req.cost_center_code, md),
        cost_center_doc=req.cost_center_doc,
        cost_center_text=req.cost_center_text,
        delivery_date_text=req.delivery_date_text,
        delivery_date_suggested=req.delivery_date_suggested,
        gl_account=req.gl_account,
        gl_account_name=gl[req.gl_account].name if req.gl_account in gl else None,
        gl_account_suggested=req.gl_account_suggested,
        gl_account_suggested_name=gl[req.gl_account_suggested].name
        if req.gl_account_suggested in gl
        else None,
        gl_account_reason=req.gl_account_reason,
        quote_reference=req.quote_reference,
        quote_date=req.quote_date,
        quote_valid_until=req.quote_valid_until,
        vat_amount=req.vat_amount,
        vat_rate=req.vat_rate,
        fx_rate=req.fx_rate,
        stated_totals=[S.StatedTotalOut(**st) for st in req.stated_totals],
        prior_approval_claim=req.prior_approval_claim,
        referenced_requests=req.referenced_requests,
        on_behalf_of_text=req.on_behalf_of_text,
        notes=req.notes,
        link_reason=req.link_reason,
        approval_run=req.approval_run,
        rejection_reason=req.rejection_reason,
        rejected_by_name=md.name(req.rejected_by) if req.rejected_by else None,
        extraction_ok=req.extraction_ok,
        provenance={k: S.Prov(**v) for k, v in req.provenance.items()},
        lines=[
            S.LineOut(
                **ln.model_dump(exclude={"requisition_id", "provenance"}),
                line_value=line_value(
                    LineIn(
                        ln.position,
                        ln.kind,
                        ln.description,
                        ln.quantity,
                        ln.unit_price,
                        ln.price_basis,
                        ln.stated_line_total,
                    )
                ),
                provenance={k: S.Prov(**v) for k, v in ln.provenance.items()},
            )
            for ln in lines
        ],
        issues=[_issue_out(i) for i in issues],
        steps=steps_out,
        steps_are_preview=preview,
        step_history=[_step_out(s, md) for s in history],
        email=S.EmailOut(
            **email.model_dump(
                exclude={"raw", "thread", "references", "content_hash", "sent_date_local"}
            ),
            thread=[
                S.ThreadMessageOut(
                    **m,
                    is_internal=bool(
                        m.get("author_email") and m["author_email"].endswith("@customer.com")
                    ),
                    employee_id=(
                        e.id if (e := md.employee_by_email(m.get("author_email"))) else None
                    ),
                )
                for m in email.thread
            ],
            attachments=[
                S.AttachmentOut.model_validate(a, from_attributes=True) for a in attachments
            ],
        ),
        events=[
            S.EventOut(
                id=e.id,
                at=e.at,
                actor=e.actor,
                actor_name=actor_name(e.actor),
                kind=e.kind,
                message=e.message,
            )
            for e in events
        ],  # type: ignore[arg-type]
        llm_runs=[S.LLMRunOut.model_validate(r, from_attributes=True) for r in runs],
        purchase_orders=[S.PurchaseOrderOut.model_validate(p, from_attributes=True) for p in pos],
        redactions=[S.RedactionOut(kind=r.kind, placeholder=r.placeholder, original=r.original) for r in redactions],
        supplier_candidates=[S.SupplierCandidate(**c) for c in sm.candidates],
        cost_center_suggestions=[
            S.CostCenterSuggestion(**c)
            for c in cost_center_suggestions(req.cost_center_text, requester, md.cost_centers)
        ],
        order_blockers=order_blockers(session, req, md) if req.state == State.APPROVED else [],
        can_submit=req.state in (State.NEEDS_REVIEW, State.REJECTED) and not open_blocking,
        linked_from=summaries(session, linked_from),
    )
