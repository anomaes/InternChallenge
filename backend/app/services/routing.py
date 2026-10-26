"""Routing and approvals: turn an evaluated requisition into a persisted approval run,
and walk that run one approver at a time."""

from sqlmodel import Session, select

from app.db.models import ApprovalStep, Requisition, utcnow
from app.domain.approval import role_label
from app.domain.master import MasterData
from app.domain.reconcile import fmt
from app.domain.workflow import State
from app.services.audit import approver_link, log_event, notify, transition
from app.services.bus import bus
from app.services.evaluate import evaluate, has_open_blocking

# Fields whose change invalidates a running or finished approval chain.
ROUTING_SNAPSHOT_FIELDS = (
    "approval_amount_chf",
    "supplier_id",
    "cost_center_code",
    "requester_id",
    "currency",
)


class ActionError(ValueError):
    """A request the rules don't allow; the message is shown to the user."""


def routing_snapshot(req: Requisition) -> dict:
    return {f: getattr(req, f) for f in ROUTING_SNAPSHOT_FIELDS} | {
        "manual": dict(req.manual_approvers)
    }


def current_steps(session: Session, req: Requisition) -> list[ApprovalStep]:
    return list(
        session.exec(
            select(ApprovalStep)
            .where(ApprovalStep.requisition_id == req.id, ApprovalStep.run == req.approval_run)
            .order_by(ApprovalStep.position)
        )
    )


def supersede_run(session: Session, req: Requisition) -> None:
    for step in current_steps(session, req):
        if step.status in ("waiting", "active"):
            step.status = "superseded"
            session.add(step)


def route(
    session: Session,
    req: Requisition,
    actor: str,
    md: MasterData | None = None,
    reason: str | None = None,
) -> None:
    """Needs review if anything blocking is open; otherwise start a fresh approval run."""
    md = md or MasterData.load(session)
    ev = evaluate(session, req, md)
    session.flush()
    if has_open_blocking(session, req) or ev.plan is None or not ev.plan.complete:
        if req.state != State.NEEDS_REVIEW:
            supersede_run(session, req)
            transition(session, req, State.NEEDS_REVIEW, actor, reason or "needs a human decision")
        return
    start_approval(session, req, ev.plan, actor, md, reason)


def start_approval(
    session: Session, req: Requisition, plan, actor: str, md: MasterData, reason: str | None
) -> None:  # noqa: ANN001
    supersede_run(session, req)
    req.approval_run += 1
    req.rejection_reason = None
    req.rejected_by = None
    for step in plan.steps:
        session.add(
            ApprovalStep(
                requisition_id=req.id,
                run=req.approval_run,
                position=step.position,
                roles=step.roles,
                approver_id=step.approver_id,
                on_behalf_of_id=step.on_behalf_of_id,
                note=step.note,
                assigned_manually=step.assigned_manually,
                status="active" if step.position == 1 else "waiting",
            )
        )
    band = plan.band
    log_event(
        session,
        req,
        actor,
        "chain_started",
        f"Approval run {req.approval_run}: band {band.position} (CHF {fmt(req.approval_amount_chf)}), "
        + " → ".join(md.name(s.approver_id) for s in plan.steps),
    )
    transition(
        session, req, State.PENDING_APPROVAL, actor, reason or "clean: sent to the first approver"
    )
    _notify_step(
        session, req, plan.steps[0].approver_id, 1, len(plan.steps), plan.steps[0].roles, md
    )


def _notify_step(
    session: Session,
    req: Requisition,
    approver_id: str | None,
    pos: int,
    total: int,
    roles: list[str],
    md: MasterData,
) -> None:
    if not approver_id:
        return
    roles_txt = " + ".join(role_label(r) for r in roles)
    notify(
        session,
        req,
        recipient_id=approver_id,
        recipient_label=md.name(approver_id),
        subject=f"Approval needed: {req.public_id} {req.title or ''}".strip(),
        body=(
            f"{req.public_id} needs your approval as {roles_txt} (step {pos} of {total}). "
            f"Amount: {req.currency} {fmt(req.po_total)} (CHF {fmt(req.approval_amount_chf)} for approval)."
        ),
        link=approver_link(approver_id, req),
    )


def decide(
    session: Session, req: Requisition, approver_id: str, approve: bool, comment: str | None
) -> None:
    md = MasterData.load(session)
    if req.state != State.PENDING_APPROVAL:
        raise ActionError("This requisition is not waiting for approval.")
    steps = current_steps(session, req)
    active = next((s for s in steps if s.status == "active"), None)
    if active is None:
        raise ActionError("No step is waiting for a decision.")
    if approver_id == req.requester_id:
        raise ActionError("A requester can never approve or reject their own requisition.")
    if active.approver_id != approver_id:
        mine = next(
            (s for s in steps if s.approver_id == approver_id and s.status == "waiting"), None
        )
        if mine:
            raise ActionError(
                f"Not your turn yet: step {active.position} ({md.name(active.approver_id)}) decides first."
            )
        raise ActionError("You are not the approver of the current step.")
    if not approve and not (comment or "").strip():
        raise ActionError("A rejection needs a reason.")

    active.status = "approved" if approve else "rejected"
    active.decided_at = utcnow()
    active.comment = (comment or "").strip() or None
    session.add(active)
    name = md.name(approver_id)
    roles_txt = " + ".join(role_label(r) for r in active.roles)

    if not approve:
        for s in steps:
            if s.status == "waiting":
                s.status = "superseded"
                session.add(s)
        req.rejection_reason = active.comment
        req.rejected_by = approver_id
        log_event(
            session,
            req,
            approver_id,
            "rejected",
            f"Rejected by {name} ({roles_txt}): {active.comment}",
        )
        transition(session, req, State.REJECTED, approver_id, f"rejected by {name}")
        if req.requester_id:
            notify(
                session,
                req,
                recipient_id=req.requester_id,
                recipient_label=md.name(req.requester_id),
                subject=f"Rejected: {req.public_id} {req.title or ''}".strip(),
                body=f"{name} rejected your request: {active.comment}",
            )
        return

    log_event(
        session,
        req,
        approver_id,
        "approved",
        f"Step {active.position} approved by {name} ({roles_txt})",
    )
    nxt = next((s for s in steps if s.status == "waiting"), None)
    if nxt is not None:
        nxt.status = "active"
        session.add(nxt)
        _notify_step(session, req, nxt.approver_id, nxt.position, len(steps), nxt.roles, md)
        bus.publish("requisition", id=req.id, state=req.state)
        return
    transition(session, req, State.APPROVED, approver_id, "every step approved")
    notify(
        session,
        req,
        recipient_id=None,
        recipient_label="Purchasing",
        subject=f"Approved: {req.public_id} {req.title or ''}".strip(),
        body=f"{req.public_id} is fully approved and can be ordered.",
    )


def restart_if_routing_changed(
    session: Session, req: Requisition, before: dict, actor: str, what: str
) -> None:
    """Editing amount, supplier, cost center or requester during/after approval restarts the chain.

    Evaluates first: a line edit changes the routing amount only once it is recomputed.
    """
    evaluate(session, req)
    session.flush()
    if routing_snapshot(req) == before:
        return
    if req.state in (State.PENDING_APPROVAL, State.APPROVED):
        log_event(
            session,
            req,
            actor,
            "chain_restarted",
            f"Approval chain restarted because {what} changed.",
        )
        route(session, req, actor, reason=f"{what} changed")
