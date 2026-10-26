"""The requester is the original internal author of the request (decision 4): the
earliest message in the thread written by a known employee. Forwarders are not the
requester, and external senders (suppliers) never are.

  email_03: the offer is from the supplier; Lukas Frei forwarded it -> Lukas Frei
  email_45: supplier -> Anna -> Lukas -> Sophie                      -> Anna Widmer
  email_46: Andrea proposed, Tobias said "ja bitte so bestellen"     -> Andrea Roth

This drives the self-approval rule, so a requester taken from the thread is always
shown as such and the clerk can change it.
"""

from dataclasses import dataclass, field

from app.domain.issues import Finding
from app.domain.master import MasterData


@dataclass
class RequesterResult:
    employee_id: str | None
    source: str | None  # sender | thread
    findings: list[Finding] = field(default_factory=list)


def resolve_requester(
    thread: list[dict], sender_email: str | None, sender_name: str | None, md: MasterData
) -> RequesterResult:
    sender = md.employee_by_email(sender_email)
    for msg in thread:  # chronological, earliest first
        emp = md.employee_by_email(msg.get("author_email"))
        if emp is None and not msg.get("author_email"):
            emp = md.employee_by_name(msg.get("author_name"))
        if emp is None:
            continue
        if sender is not None and emp.id == sender.id:
            return RequesterResult(emp.id, "sender")
        forwarded_by = sender.name if sender else (sender_name or sender_email or "the sender")
        return RequesterResult(
            emp.id,
            "thread",
            [
                Finding(
                    "requester_from_thread",
                    "info",
                    f"Requester is {emp.name}, who started the request in the thread; "
                    f"{forwarded_by} sent it on. Change it if that's wrong; it decides who "
                    f"may not approve.",
                    field="requester",
                )
            ],
        )

    who = f"{sender_name} <{sender_email}>" if sender_name else (sender_email or "unknown")
    return RequesterResult(
        None,
        None,
        [
            Finding(
                "requester_unknown",
                "blocking",
                f"The sender {who} is not a known employee, so the request has no requester.",
                field="requester",
            )
        ],
    )
