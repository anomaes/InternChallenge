"""Findings are issues before they are persisted: what a rule found, how bad it is, and
which field it is about. `blocking` stops routing to approval; `blocks_order` stops
only the purchase order (e.g. a missing delivery date)."""

import dataclasses
from dataclasses import dataclass
from typing import Literal

Severity = Literal["blocking", "warning", "info"]


@dataclass
class Finding:
    code: str
    severity: Severity
    message: str
    field: str | None = None
    details: dict = dataclasses.field(default_factory=dict)
    blocks_order: bool = False

    @property
    def key(self) -> tuple[str, str | None]:
        return (self.code, self.field)
