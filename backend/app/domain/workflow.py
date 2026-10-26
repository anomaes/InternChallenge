"""Requisition states and the only transitions allowed between them. Enforced
server-side; every transition is written to the audit log by the service layer."""

from enum import StrEnum


class State(StrEnum):
    INBOX = "INBOX"
    PROCESSING = "PROCESSING"
    EXTRACTED = "EXTRACTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ORDERED = "ORDERED"
    REJECTED = "REJECTED"
    CLOSED_DUPLICATE = "CLOSED_DUPLICATE"


S = State
TRANSITIONS: dict[State, set[State]] = {
    S.INBOX: {S.PROCESSING},
    S.PROCESSING: {S.EXTRACTED, S.NEEDS_REVIEW},
    S.EXTRACTED: {S.NEEDS_REVIEW, S.PENDING_APPROVAL},
    # Needs review -> pending approval only once nothing blocking is left (checked by the service).
    S.NEEDS_REVIEW: {S.PENDING_APPROVAL, S.REJECTED, S.CLOSED_DUPLICATE, S.PROCESSING},
    # A routing field edited during approval sends it back for review / a fresh chain.
    S.PENDING_APPROVAL: {
        S.APPROVED,
        S.REJECTED,
        S.NEEDS_REVIEW,
        S.PENDING_APPROVAL,
        S.CLOSED_DUPLICATE,
    },
    S.APPROVED: {S.ORDERED, S.NEEDS_REVIEW, S.PENDING_APPROVAL},
    # A corrected rejected request restarts its chain from the beginning.
    S.REJECTED: {S.NEEDS_REVIEW, S.PENDING_APPROVAL},
    S.ORDERED: set(),
    S.CLOSED_DUPLICATE: set(),
}

TERMINAL = {S.ORDERED, S.CLOSED_DUPLICATE}
# States in which routing fields may still be edited by the clerk.
EDITABLE = {S.NEEDS_REVIEW, S.PENDING_APPROVAL, S.APPROVED, S.REJECTED}

LABELS = {
    S.INBOX: "Inbox",
    S.PROCESSING: "Processing",
    S.EXTRACTED: "Extracted",
    S.NEEDS_REVIEW: "Needs review",
    S.PENDING_APPROVAL: "Pending approval",
    S.APPROVED: "Approved",
    S.ORDERED: "Ordered",
    S.REJECTED: "Rejected",
    S.CLOSED_DUPLICATE: "Closed (duplicate)",
}


class TransitionError(ValueError):
    pass


def check_transition(current: str, target: str) -> None:
    cur, tgt = State(current), State(target)
    if tgt not in TRANSITIONS[cur]:
        raise TransitionError(f"Can't move a requisition from {LABELS[cur]} to {LABELS[tgt]}.")
