"""Who approves, in what order (brief section 4).

1. Band: the first band whose inclusive upper bound is >= the amount in CHF.
2. Roles -> people: cost center owner, department head via the cost center's
   department, company-wide roles via employees[].role (the holder without deputy_for).
3. Consecutive steps held by the same person collapse into one step.
4. A step whose person is the requester passes to the next step's person who is not
   the requester ("on behalf of"). No re-collapse afterwards (decision 2): if that
   person also holds the following step, they approve twice. If nobody is left, the
   step needs a manually assigned approver.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from app.db.models import ApprovalBand
from app.domain.issues import Finding
from app.domain.master import MasterData

ROLE_LABELS = {
    "cost_center_owner": "Cost center owner",
    "department_head": "Department head",
    "finance": "Finance",
    "cfo": "CFO",
    "ceo": "CEO",
}


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role.replace("_", " ").title())


@dataclass
class PlannedStep:
    position: int
    roles: list[str]
    holder_id: str | None  # who holds the role(s)
    approver_id: str | None  # who actually approves
    on_behalf_of_id: str | None = None
    note: str | None = None
    assigned_manually: bool = False


@dataclass
class ChainPlan:
    band: ApprovalBand | None
    steps: list[PlannedStep] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.band is not None and bool(self.steps) and all(s.approver_id for s in self.steps)


def select_band(amount_chf: Decimal, bands: list[ApprovalBand]) -> ApprovalBand | None:
    for band in sorted(bands, key=lambda b: b.position):
        if band.upper is None or amount_chf <= band.upper:
            return band
    return None


def resolve_role(role: str, cost_center_code: str, md: MasterData) -> str | None:
    cc = md.cost_centers.get(cost_center_code)
    if role == "cost_center_owner":
        return cc.owner_employee_id if cc else None
    if role == "department_head":
        dept = md.departments.get(cc.department) if cc else None
        return dept.head_employee_id if dept else None
    holders = [e for e in md.employees.values() if e.role == role]
    principals = [e for e in holders if not e.deputy_for]
    if len(principals) == 1:
        return principals[0].id
    return None  # none, or ambiguous: a human decides


def plan_chain(
    amount_chf: Decimal,
    cost_center_code: str,
    requester_id: str | None,
    md: MasterData,
    manual: dict[str, str] | None = None,
) -> ChainPlan:
    manual = manual or {}
    band = select_band(amount_chf, md.bands)
    plan = ChainPlan(band=band)
    if band is None:
        plan.findings.append(
            Finding("no_approval_band", "blocking", f"No approval band covers CHF {amount_chf}.")
        )
        return plan

    # Resolve and collapse consecutive steps held by the same person.
    steps: list[PlannedStep] = []
    for role in band.required_roles:
        holder = resolve_role(role, cost_center_code, md)
        if steps and holder is not None and steps[-1].holder_id == holder:
            steps[-1].roles.append(role)
            continue
        steps.append(
            PlannedStep(position=len(steps) + 1, roles=[role], holder_id=holder, approver_id=holder)
        )

    # Self-approval: pass the step on to the next person in the chain who is not the requester.
    for i, step in enumerate(steps):
        roles_txt = " + ".join(role_label(r) for r in step.roles)
        if step.holder_id is None:
            step.approver_id = None
            step.note = f"No one holds the role {roles_txt}."
        elif requester_id and step.holder_id == requester_id:
            substitute = next(
                (
                    s.holder_id
                    for s in steps[i + 1 :]
                    if s.holder_id and s.holder_id != requester_id
                ),
                None,
            )
            step.on_behalf_of_id = requester_id
            step.approver_id = substitute
            if substitute:
                step.note = (
                    f"On behalf of {roles_txt}: {md.name(requester_id)} is the requester and "
                    f"can't approve their own requisition."
                )
            else:
                step.note = (
                    f"{md.name(requester_id)} holds {roles_txt} but is the requester, and the chain "
                    f"offers no one else."
                )

        if step.approver_id is None:
            chosen = manual.get(str(step.position))
            if chosen and chosen in md.employees and chosen != requester_id:
                step.approver_id = chosen
                step.assigned_manually = True
                step.note = (step.note or "") + f" Assigned by the clerk: {md.name(chosen)}."
            else:
                plan.findings.append(
                    Finding(
                        "needs_manual_approver",
                        "blocking",
                        f"Step {step.position} ({roles_txt}) has no eligible approver. "
                        + (step.note or "")
                        + " Assign one by hand.",
                        field="approval_chain",
                        details={"position": step.position, "roles": step.roles},
                    )
                )
    plan.steps = steps
    return plan
