"""The approver's view: a queue per person on a fixed path (/approver/EMP-701), and the
decision itself. No real auth (out of scope): the approver ID in the path stands in for
the logged-in user, and the server still enforces turn order and self-approval."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api import schemas as S
from app.db.models import ApprovalStep, Requisition
from app.db.session import get_session
from app.domain.approval import role_label
from app.domain.master import MasterData
from app.domain.workflow import State
from app.services.bus import bus
from app.services.orders import try_auto_order
from app.services.routing import ActionError, decide
from app.services.serialize import detail, summaries

router = APIRouter(prefix="/api", tags=["approvers"])


class ApproverOut(BaseModel):
    id: str
    name: str
    role: str
    role_label: str
    pending: int


class QueueItem(BaseModel):
    requisition: S.ReqSummary
    position: int
    total: int
    roles: list[str]
    on_behalf_of_name: str | None
    status: str


class QueueOut(BaseModel):
    approver: S.PersonOut
    pending: list[QueueItem]
    upcoming: list[QueueItem]
    decided: list[QueueItem]


@router.get("/approvers", response_model=list[ApproverOut])
def list_approvers(session: Session = Depends(get_session)) -> list[ApproverOut]:
    md = MasterData.load(session)
    active = session.exec(
        select(ApprovalStep, Requisition).where(
            ApprovalStep.requisition_id == Requisition.id,
            ApprovalStep.status == "active",
            ApprovalStep.run == Requisition.approval_run,
        )  # type: ignore[arg-type]
    ).all()
    counts: dict[str, int] = {}
    for step, _ in active:
        if step.approver_id:
            counts[step.approver_id] = counts.get(step.approver_id, 0) + 1
    order = {"cfo": 0, "ceo": 1, "finance": 2, "department_head": 3, "cost_center_owner": 4}
    approvers = [e for e in md.employees.values() if e.role != "requester_only"]
    approvers.sort(key=lambda e: (-counts.get(e.id, 0), order.get(e.role, 9), e.name))
    return [
        ApproverOut(
            id=e.id,
            name=e.name,
            role=e.role,
            role_label=role_label(e.role),
            pending=counts.get(e.id, 0),
        )
        for e in approvers
    ]


@router.get("/approvers/{employee_id}/queue", response_model=QueueOut)
def queue(employee_id: str, session: Session = Depends(get_session)) -> QueueOut:
    md = MasterData.load(session)
    emp = md.employees.get(employee_id)
    if emp is None:
        raise HTTPException(404, "Unknown employee.")
    rows = session.exec(
        select(ApprovalStep, Requisition)
        .where(
            ApprovalStep.requisition_id == Requisition.id,
            ApprovalStep.approver_id == employee_id,
            ApprovalStep.run == Requisition.approval_run,
        )  # type: ignore[arg-type]
        .order_by(Requisition.id.desc())  # type: ignore[union-attr]
    ).all()
    reqs = list({r.id: r for _, r in rows}.values())
    by_id = {s.id: s for s in summaries(session, reqs)}
    totals: dict[int, int] = {}
    for step in session.exec(
        select(ApprovalStep).where(ApprovalStep.requisition_id.in_([r.id for r in reqs]))
    ):  # type: ignore[attr-defined]
        r = next(x for x in reqs if x.id == step.requisition_id)
        if step.run == r.approval_run and step.status != "superseded":
            totals[r.id] = totals.get(r.id, 0) + 1  # type: ignore[index]

    out = QueueOut(
        approver=S.PersonOut.model_validate(emp, from_attributes=True),
        pending=[],
        upcoming=[],
        decided=[],
    )
    for step, r in rows:
        if step.status == "superseded":
            continue
        item = QueueItem(
            requisition=by_id[r.id],
            position=step.position,
            total=totals.get(r.id, 0),  # type: ignore[arg-type]
            roles=[role_label(x) for x in step.roles],
            on_behalf_of_name=md.name(step.on_behalf_of_id) if step.on_behalf_of_id else None,
            status=step.status,
        )
        if step.status == "active" and r.state == State.PENDING_APPROVAL:
            out.pending.append(item)
        elif step.status == "waiting" and r.state == State.PENDING_APPROVAL:
            out.upcoming.append(item)
        elif step.status in ("approved", "rejected"):
            out.decided.append(item)
    return out


def _decide(req_id: int, body: S.DecisionIn, approve: bool, session: Session) -> S.ReqDetail:
    req = session.get(Requisition, req_id)
    if req is None:
        raise HTTPException(404, "No such requisition.")
    try:
        decide(session, req, body.approver_id, approve, body.comment)
    except ActionError as err:
        raise HTTPException(409, str(err)) from err
    session.commit()
    if req.state == State.APPROVED:
        try_auto_order(session, req)
        session.commit()
    session.refresh(req)
    bus.publish("requisition", id=req.id, state=req.state)
    return detail(session, req)


@router.post("/requisitions/{req_id}/approve", response_model=S.ReqDetail)
def approve(
    req_id: int, body: S.DecisionIn, session: Session = Depends(get_session)
) -> S.ReqDetail:
    return _decide(req_id, body, True, session)


@router.post("/requisitions/{req_id}/decline", response_model=S.ReqDetail)
def decline(
    req_id: int, body: S.DecisionIn, session: Session = Depends(get_session)
) -> S.ReqDetail:
    return _decide(req_id, body, False, session)
