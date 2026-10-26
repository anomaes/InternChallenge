"""Audit log and the simulated notification outbox."""

from typing import Any

from sqlmodel import Session

from app.config import settings
from app.db.models import Event, Notification, Requisition, utcnow
from app.domain.workflow import LABELS, State, check_transition
from app.services.bus import bus


def log_event(
    session: Session,
    req: Requisition | None,
    actor: str,
    kind: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    session.add(
        Event(
            requisition_id=req.id if req else None,
            actor=actor,
            kind=kind,
            message=message,
            data=data or {},
        )
    )


def transition(
    session: Session, req: Requisition, target: State, actor: str, reason: str | None = None
) -> None:
    """The only way a requisition changes state."""
    if req.state == target and target != State.PENDING_APPROVAL:
        return
    check_transition(req.state, target)
    old = req.state
    req.state = target
    req.updated_at = utcnow()
    session.add(req)
    msg = f"{LABELS[State(old)]} → {LABELS[target]}" + (f": {reason}" if reason else "")
    log_event(session, req, actor, "state_changed", msg, {"from": old, "to": target.value})
    bus.publish("requisition", id=req.id, state=target.value)


def approver_link(employee_id: str, req: Requisition) -> str:
    return f"{settings.frontend_base_url}/approver/{employee_id}/r/{req.id}"


def notify(
    session: Session,
    req: Requisition | None,
    *,
    recipient_id: str | None,
    recipient_label: str,
    subject: str,
    body: str,
    link: str | None = None,
) -> None:
    """Writes to the outbox only. Delivery by email is future work."""
    session.add(
        Notification(
            requisition_id=req.id if req else None,
            recipient_id=recipient_id,
            recipient_label=recipient_label,
            subject=subject,
            body=body,
            link=link,
        )
    )
    bus.publish("notification", requisition_id=req.id if req else None)
