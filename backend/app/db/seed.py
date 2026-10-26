"""Load master_data.json into the database. Run once at startup and on reset; the
application never reads the JSON file at request time."""

import json
from decimal import Decimal
from pathlib import Path

from sqlmodel import Session, delete, select

from app.config import settings
from app.db.models import (
    ApprovalBand,
    CostCenter,
    Department,
    Employee,
    FxRate,
    GLAccount,
    Supplier,
)

MASTER_TABLES = (Supplier, CostCenter, Department, Employee, GLAccount, ApprovalBand, FxRate)


def seed_master_data(session: Session, path: Path | None = None, *, force: bool = False) -> bool:
    """Insert master data. Without `force`, does nothing if suppliers already exist."""
    if not force and session.exec(select(Supplier).limit(1)).first():
        return False
    data = json.loads((path or settings.master_data_path).read_text(encoding="utf-8"))
    for table in MASTER_TABLES:
        session.exec(delete(table))

    for s in data["suppliers"]:
        session.add(Supplier(**s))
    for d in data["departments"]:
        session.add(Department(**d))
    for c in data["cost_centers"]:
        session.add(CostCenter(**c))
    for e in data["employees"]:
        session.add(Employee(**e))
    for g in data["gl_accounts"]:
        session.add(GLAccount(**g))
    for i, band in enumerate(data["approval_limits_chf"], start=1):
        session.add(
            ApprovalBand(
                position=i,
                lower=Decimal(str(band["from"])),
                upper=None if band["to"] is None else Decimal(str(band["to"])),
                required_roles=band["required_roles"],
            )
        )
    for cur, rate in data["_meta"]["fx_rates_to_chf"].items():
        session.add(FxRate(currency=cur, rate_to_chf=Decimal(str(rate))))
    session.commit()
    return True
