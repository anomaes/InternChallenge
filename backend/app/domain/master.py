"""An in-memory snapshot of master data, loaded from the database once per evaluation.

The domain rules take this instead of a session, so they are pure functions that the
tests can drive with hand-built data.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from sqlmodel import Session, select

from app.db.models import (
    ApprovalBand,
    CostCenter,
    Department,
    Employee,
    FxRate,
    GLAccount,
    Supplier,
)


@dataclass
class MasterData:
    suppliers: dict[str, Supplier] = field(default_factory=dict)
    cost_centers: dict[str, CostCenter] = field(default_factory=dict)
    departments: dict[str, Department] = field(default_factory=dict)
    employees: dict[str, Employee] = field(default_factory=dict)
    gl_accounts: dict[str, GLAccount] = field(default_factory=dict)
    bands: list[ApprovalBand] = field(default_factory=list)
    fx: dict[str, Decimal] = field(default_factory=dict)

    @classmethod
    def load(cls, session: Session) -> "MasterData":
        return cls(
            suppliers={s.id: s for s in session.exec(select(Supplier))},
            cost_centers={c.code: c for c in session.exec(select(CostCenter))},
            departments={d.code: d for d in session.exec(select(Department))},
            employees={e.id: e for e in session.exec(select(Employee))},
            gl_accounts={g.code: g for g in session.exec(select(GLAccount))},
            bands=sorted(session.exec(select(ApprovalBand)), key=lambda b: b.position),
            fx={f.currency: f.rate_to_chf for f in session.exec(select(FxRate))},
        )

    def employee_by_email(self, email: str | None) -> Employee | None:
        if not email:
            return None
        email = email.strip().lower()
        return next((e for e in self.employees.values() if e.email.lower() == email), None)

    def employee_by_name(self, name: str | None) -> Employee | None:
        """Unique, exact (case-insensitive) full-name match only."""
        if not name:
            return None
        n = " ".join(name.split()).casefold()
        hits = [e for e in self.employees.values() if e.name.casefold() == n]
        return hits[0] if len(hits) == 1 else None

    def name(self, employee_id: str | None) -> str:
        if employee_id and employee_id in self.employees:
            return self.employees[employee_id].name
        return employee_id or "—"
