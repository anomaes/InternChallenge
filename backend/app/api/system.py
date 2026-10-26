"""Master data, workflow overview, dashboard, purchase orders, settings, the demo inbox
simulator, and the live event stream."""

import asyncio
import json
import threading
from datetime import datetime
from decimal import Decimal
from email import policy
from email.parser import BytesParser

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, delete, func, select

from app.api import schemas as S
from app.config import settings
from app.db.models import (
    ApprovalStep,
    Attachment,
    Email,
    Event,
    Issue,
    LineItem,
    LLMRun,
    Notification,
    PurchaseOrder,
    Redaction,
    Requisition,
)
from app.db.seed import seed_master_data
from app.db.session import engine, get_session
from app.domain.approval import role_label
from app.domain.master import MasterData
from app.domain.workflow import LABELS, TRANSITIONS, State
from app.erp.client import erp_health
from app.services.bus import bus
from app.services.orders import order_blockers
from app.services.pipeline import ingest_email, process_async
from app.services.serialize import _cc_out, summaries
from app.services.settings_store import all_settings, set_setting

router = APIRouter(prefix="/api", tags=["system"])


# --------------------------------------------------------------------------- master data


class BandOut(BaseModel):
    position: int
    lower: Decimal
    upper: Decimal | None
    required_roles: list[str]
    role_labels: list[str]


class DepartmentOut(BaseModel):
    code: str
    name: str
    head_employee_id: str
    head_name: str


class MasterOut(BaseModel):
    suppliers: list[S.SupplierOut]
    cost_centers: list[S.CostCenterOut]
    departments: list[DepartmentOut]
    employees: list[S.PersonOut]
    gl_accounts: list[dict[str, str]]
    approval_bands: list[BandOut]
    fx_rates: dict[str, Decimal]


@router.get("/master", response_model=MasterOut)
def master(session: Session = Depends(get_session)) -> MasterOut:
    md = MasterData.load(session)
    return MasterOut(
        suppliers=[
            S.SupplierOut.model_validate(s, from_attributes=True)
            for s in sorted(md.suppliers.values(), key=lambda s: s.id)
        ],
        cost_centers=[c for code in sorted(md.cost_centers) if (c := _cc_out(code, md))],
        departments=[
            DepartmentOut(
                code=d.code,
                name=d.name,
                head_employee_id=d.head_employee_id,
                head_name=md.name(d.head_employee_id),
            )
            for d in md.departments.values()
        ],
        employees=[
            S.PersonOut.model_validate(e, from_attributes=True)
            for e in sorted(md.employees.values(), key=lambda e: e.id)
        ],
        gl_accounts=[
            {"code": g.code, "name": g.name}
            for g in sorted(md.gl_accounts.values(), key=lambda g: g.code)
        ],
        approval_bands=[
            BandOut(
                position=b.position,
                lower=b.lower,
                upper=b.upper,
                required_roles=b.required_roles,
                role_labels=[role_label(r) for r in b.required_roles],
            )
            for b in md.bands
        ],
        fx_rates=md.fx,
    )


# --------------------------------------------------------------------------- workflow + dashboard


class StateCount(BaseModel):
    state: str
    label: str
    count: int


class WorkflowOut(BaseModel):
    states: list[StateCount]
    transitions: list[tuple[str, str]]


@router.get("/workflow", response_model=WorkflowOut)
def workflow(session: Session = Depends(get_session)) -> WorkflowOut:
    counts = dict(
        session.exec(select(Requisition.state, func.count()).group_by(Requisition.state)).all()
    )  # type: ignore[arg-type]
    return WorkflowOut(
        states=[
            StateCount(state=s.value, label=LABELS[s], count=counts.get(s.value, 0)) for s in State
        ],
        transitions=[
            (a.value, b.value)
            for a, targets in TRANSITIONS.items()
            for b in sorted(targets)
            if a != b
        ],
    )


class AttentionGroup(BaseModel):
    key: str
    title: str
    hint: str
    items: list[S.ReqSummary]


class DashboardOut(BaseModel):
    counts: dict[str, int]
    groups: list[AttentionGroup]
    recent: list[S.ReqSummary]


_GROUPS: list[tuple[str, str, str, set[str]]] = [
    (
        "supplier",
        "Supplier problems",
        "Unknown, blocked, ambiguous or conflicting suppliers",
        {
            "supplier_unknown",
            "supplier_blocked",
            "supplier_conflict",
            "supplier_ambiguous",
            "supplier_uncertain",
            "supplier_missing",
            "supplier_inactive",
        },
    ),
    (
        "amount",
        "Amounts to decide",
        "The document contradicts itself, or lines have no price",
        {
            "amount_conflict",
            "unpriced_line",
            "approximate_quantity",
            "missing_quantity",
            "no_line_items",
            "currency_missing",
            "unverified_value",
            "check_doubt",
        },
    ),
    (
        "cost_center",
        "Cost center missing or unknown",
        "Needed to find the owner and department head",
        {"cost_center_missing", "cost_center_unknown"},
    ),
    (
        "duplicate",
        "Possible duplicates and corrections",
        "Linked to an earlier request; decide what to do",
        {
            "suspected_duplicate",
            "suspected_correction",
            "unlinked_correction",
            "unlinked_repeat",
            "referenced_request_not_found",
        },
    ),
    (
        "approver",
        "Approver needed",
        "The chain offers nobody who may approve",
        {"needs_manual_approver"},
    ),
    ("other", "Other blockers", "Unknown requester, failed extraction, not a request", set()),
]


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(session: Session = Depends(get_session)) -> DashboardOut:
    reqs = list(session.exec(select(Requisition).order_by(Requisition.id.desc())))  # type: ignore[union-attr]
    sums = {s.id: s for s in summaries(session, reqs)}
    md = MasterData.load(session)
    open_issues: dict[int, list[Issue]] = {}
    for i in session.exec(select(Issue).where(Issue.status == "open")):
        open_issues.setdefault(i.requisition_id, []).append(i)

    review = [r for r in reqs if r.state == State.NEEDS_REVIEW]
    grouped: dict[str, list[S.ReqSummary]] = {k: [] for k, *_ in _GROUPS}
    for r in review:
        codes = {i.code for i in open_issues.get(r.id, []) if i.severity == "blocking"}  # type: ignore[arg-type]
        key = next((k for k, _, _, cs in _GROUPS if codes & cs), "other")
        grouped[key].append(sums[r.id])  # type: ignore[index]

    approved = [r for r in reqs if r.state == State.APPROVED]
    ready, waiting_date, failed = [], [], []
    for r in approved:
        if any(i.code == "order_failed" for i in open_issues.get(r.id, [])):  # type: ignore[arg-type]
            failed.append(sums[r.id])  # type: ignore[index]
        elif order_blockers(session, r, md):
            waiting_date.append(sums[r.id])  # type: ignore[index]
        else:
            ready.append(sums[r.id])  # type: ignore[index]

    groups = [
        AttentionGroup(key=k, title=t, hint=h, items=grouped[k])
        for k, t, h, _ in _GROUPS
        if grouped[k]
    ]
    if waiting_date:
        groups.append(
            AttentionGroup(
                key="order_data",
                title="Approved, details missing for the order",
                hint="Usually the delivery date: confirm it, then order",
                items=waiting_date,
            )
        )
    if failed:
        groups.append(
            AttentionGroup(
                key="order_failed",
                title="Order failed",
                hint="The ERP rejected the order or was unreachable",
                items=failed,
            )
        )
    if ready:
        groups.append(
            AttentionGroup(
                key="ready",
                title="Ready to order",
                hint="Fully approved; everything the ERP needs is there",
                items=ready,
            )
        )

    return DashboardOut(
        counts={
            "needs_review": len(review),
            "pending_approval": sum(1 for r in reqs if r.state == State.PENDING_APPROVAL),
            "ready_to_order": len(ready) + len(waiting_date),
            "order_failed": len(failed),
            "ordered": sum(1 for r in reqs if r.state == State.ORDERED),
            "processing": sum(
                1 for r in reqs if r.state in (State.INBOX, State.PROCESSING, State.EXTRACTED)
            ),
            "total": len(reqs),
        },
        groups=groups,
        recent=[sums[r.id] for r in reqs[:8]],  # type: ignore[index]
    )


@router.get("/purchase-orders", response_model=list[S.PurchaseOrderOut])
def purchase_orders(session: Session = Depends(get_session)) -> list[S.PurchaseOrderOut]:
    rows = session.exec(
        select(PurchaseOrder, Requisition)
        .where(PurchaseOrder.requisition_id == Requisition.id)
        .order_by(PurchaseOrder.id.desc())
    ).all()  # type: ignore[arg-type,union-attr]
    return [
        S.PurchaseOrderOut(**po.model_dump(), requisition_public_id=r.public_id) for po, r in rows
    ]


@router.get("/attachments/{attachment_id}")
def attachment(attachment_id: int, session: Session = Depends(get_session)) -> Response:
    att = session.get(Attachment, attachment_id)
    if att is None:
        raise HTTPException(404, "No such attachment.")
    return Response(
        content=att.data,
        media_type=att.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{att.filename}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


# --------------------------------------------------------------------------- settings + status


@router.get("/settings", response_model=S.SettingsOut)
def get_settings(session: Session = Depends(get_session)) -> S.SettingsOut:
    return S.SettingsOut(**all_settings(session))


@router.put("/settings", response_model=S.SettingsOut)
def put_settings(body: S.SettingsPatch, session: Session = Depends(get_session)) -> S.SettingsOut:
    data = body.model_dump(exclude_unset=True)
    if "llm_cache_mode" in data and data["llm_cache_mode"] not in ("cached", "live"):
        raise HTTPException(422, "llm_cache_mode must be cached or live.")
    for k, v in data.items():
        set_setting(session, k, v)
    session.commit()
    bus.publish("settings")
    return S.SettingsOut(**all_settings(session))


class StatusOut(BaseModel):
    erp: str
    api_key_configured: bool
    extraction_model: str
    decisions_model: str
    counts: dict[str, int]
    cached_responses: int


@router.get("/status", response_model=StatusOut)
def status(session: Session = Depends(get_session)) -> StatusOut:
    def count(model: type) -> int:
        return session.exec(select(func.count()).select_from(model)).one()

    md = MasterData.load(session)
    cache_dir = settings.llm_cache_dir
    return StatusOut(
        erp=erp_health(),
        api_key_configured=settings.api_key() is not None,
        extraction_model=settings.extraction_model,
        decisions_model=settings.decisions_model,
        counts={
            "requisitions": count(Requisition),
            "emails": count(Email),
            "suppliers": len(md.suppliers),
            "cost_centers": len(md.cost_centers),
            "employees": len(md.employees),
            "notifications": count(Notification),
            "purchase_orders": count(PurchaseOrder),
        },
        cached_responses=len(list(cache_dir.glob("*.json"))) if cache_dir.exists() else 0,
    )


class NotificationOut(BaseModel):
    id: int
    requisition_id: int | None
    recipient_id: str | None
    recipient_label: str
    subject: str
    body: str
    link: str | None
    created_at: datetime


@router.get("/outbox", response_model=list[NotificationOut])
def outbox(session: Session = Depends(get_session)) -> list[NotificationOut]:
    rows = session.exec(select(Notification).order_by(Notification.id.desc()).limit(200))  # type: ignore[union-attr]
    return [NotificationOut.model_validate(n, from_attributes=True) for n in rows]


# --------------------------------------------------------------------------- demo inbox


class SampleOut(BaseModel):
    name: str
    subject: str | None
    sender: str | None
    sent_at: datetime | None
    has_attachment: bool
    requisition_id: int | None


def _samples() -> list[tuple[str, bytes, datetime | None, str | None, str | None, bool]]:
    out = []
    for path in sorted(settings.sample_emails_dir.glob("*.eml")):
        raw = path.read_bytes()
        msg = BytesParser(policy=policy.default).parsebytes(raw, headersonly=False)
        try:
            sent = msg["Date"].datetime if msg["Date"] else None  # type: ignore[union-attr]
        except (AttributeError, TypeError, ValueError):
            sent = None
        has_att = any(part.get_filename() for part in msg.walk())
        out.append(
            (path.name, raw, sent, str(msg["Subject"] or ""), str(msg["From"] or ""), has_att)
        )
    # Chronological, the order a real mailbox would deliver them in.
    out.sort(key=lambda s: (s[2].timestamp() if s[2] else 0, s[0]))
    return out


def _delivered(session: Session) -> dict[str, int]:
    rows = session.exec(
        select(Email.source_name, Requisition.id).where(Requisition.email_id == Email.id)
    ).all()  # type: ignore[arg-type]
    return {name: rid for name, rid in rows}


@router.get("/demo/samples", response_model=list[SampleOut])
def samples(session: Session = Depends(get_session)) -> list[SampleOut]:
    delivered = _delivered(session)
    return [
        SampleOut(
            name=n,
            subject=subj,
            sender=sender,
            sent_at=sent,
            has_attachment=att,
            requisition_id=delivered.get(n),
        )
        for n, _, sent, subj, sender, att in _samples()
    ]


class DeliverIn(BaseModel):
    name: str


class DeliveredOut(BaseModel):
    requisition_id: int
    public_id: str


def _deliver(session: Session, name: str, raw: bytes) -> DeliveredOut:
    req = ingest_email(session, raw, name)
    process_async(req.id)  # type: ignore[arg-type]
    return DeliveredOut(requisition_id=req.id, public_id=req.public_id)  # type: ignore[arg-type]


@router.post("/demo/deliver", response_model=DeliveredOut)
def deliver(body: DeliverIn, session: Session = Depends(get_session)) -> DeliveredOut:
    sample = next((s for s in _samples() if s[0] == body.name), None)
    if sample is None:
        raise HTTPException(404, "No such sample email.")
    return _deliver(session, sample[0], sample[1])


@router.post("/demo/deliver-next", response_model=DeliveredOut | None)
def deliver_next(session: Session = Depends(get_session)) -> DeliveredOut | None:
    delivered = _delivered(session)
    sample = next((s for s in _samples() if s[0] not in delivered), None)
    return _deliver(session, sample[0], sample[1]) if sample else None


class DeliverAllIn(BaseModel):
    interval_s: float = 3.0


_feeder: dict[str, threading.Event | None] = {"stop": None}


@router.post("/demo/deliver-all", response_model=S.OkOut)
def deliver_all(body: DeliverAllIn, session: Session = Depends(get_session)) -> S.OkOut:
    if _feeder["stop"] is not None and not _feeder["stop"].is_set():
        raise HTTPException(409, "Already delivering.")
    delivered = _delivered(session)
    pending = [s for s in _samples() if s[0] not in delivered]
    stop = threading.Event()
    _feeder["stop"] = stop

    def run() -> None:
        for name, raw, *_ in pending:
            if stop.is_set():
                break
            with Session(engine) as s:
                if name not in _delivered(s):
                    _deliver(s, name, raw)
            stop.wait(max(0.2, body.interval_s))
        stop.set()
        bus.publish("feeder", running=False)

    threading.Thread(target=run, daemon=True, name="demo-feeder").start()
    bus.publish("feeder", running=True)
    return S.OkOut(message=f"Delivering {len(pending)} emails, one every {body.interval_s:g}s.")


@router.post("/demo/stop", response_model=S.OkOut)
def stop_delivery() -> S.OkOut:
    if _feeder["stop"] is not None:
        _feeder["stop"].set()
    return S.OkOut(message="Stopped.")


@router.get("/demo/feeder", response_model=S.OkOut)
def feeder_state() -> S.OkOut:
    running = _feeder["stop"] is not None and not _feeder["stop"].is_set()
    return S.OkOut(ok=running)


@router.post("/demo/upload", response_model=DeliveredOut)
async def upload(request: Request, session: Session = Depends(get_session)) -> DeliveredOut:
    """Raw .eml in the request body (keeps the dependency list short: no multipart parser)."""
    raw = await request.body()
    if not raw.strip():
        raise HTTPException(422, "Empty upload.")
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, "That email is larger than 20 MB.")
    name = request.headers.get("X-Filename", "uploaded.eml")[:200]
    return _deliver(session, name, raw)


@router.post("/demo/reset", response_model=S.OkOut)
def reset(session: Session = Depends(get_session)) -> S.OkOut:
    if _feeder["stop"] is not None:
        _feeder["stop"].set()
    for model in (Notification, PurchaseOrder, Event, LLMRun, ApprovalStep, Issue, LineItem):
        session.exec(delete(model))  # type: ignore[arg-type]
    session.exec(delete(Requisition))  # type: ignore[arg-type]
    for model in (Redaction, Attachment, Email):
        session.exec(delete(model))  # type: ignore[arg-type]
    session.commit()
    seed_master_data(session, force=True)
    bus.publish("reset")
    return S.OkOut(message="All requisitions removed; master data reseeded.")


# --------------------------------------------------------------------------- live updates


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    async def stream():  # noqa: ANN202
        last = bus.seq
        yield "retry: 2000\n\n"
        while not await request.is_disconnected():
            batch = await asyncio.to_thread(bus.wait, last, 15.0)
            if not batch:
                yield ": keep-alive\n\n"
                continue
            for seq, ev in batch:
                last = seq
                yield f"id: {seq}\ndata: {json.dumps(ev)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
