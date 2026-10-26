"""Amounts (brief 4.6, 5): compute every figure from the lines and cross-check every
figure the document states. A requisition never routes on a number the document
itself contradicts.

- line value       = quantity x unit_price / price_basis
- approval amount  = items + freight/surcharges, excl. VAT, discounts NOT subtracted
                     (decision 3: a discount never lowers the approval band)
- PO total         = all lines incl. discounts, excl. VAT
"""

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.domain.issues import Finding

CENT = Decimal("0.01")
_VAT_LABEL = re.compile(
    r"\b(vat|mwst|ust|mehrwertsteuer|umsatzsteuer|tva|iva|tax)\b", re.IGNORECASE
)
_TOTAL_LABEL = re.compile(r"(total|summe|gesamt|betrag)", re.IGNORECASE)
LINE_TOLERANCE = Decimal("0.015")
TOTAL_TOLERANCE = Decimal("0.02")


def q2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def fmt(value: Decimal | None, currency: str | None = None) -> str:
    if value is None:
        return "—"
    s = f"{q2(value):,.2f}"
    return f"{currency} {s}" if currency else s


@dataclass
class LineIn:
    position: int
    kind: str  # item | freight | surcharge | discount
    description: str
    quantity: Decimal | None
    unit_price: Decimal | None
    price_basis: Decimal | None = None
    stated_line_total: Decimal | None = None
    quantity_approximate: bool = False


@dataclass
class StatedTotalIn:
    label: str
    amount: Decimal
    includes_vat: str = "unclear"  # yes | no | unclear
    approximate: bool = False
    overridden: bool = False  # the clerk decided the lines are right


@dataclass
class ReconcileResult:
    line_values: dict[int, Decimal | None] = field(default_factory=dict)
    approval_amount: Decimal | None = None
    po_total: Decimal | None = None
    findings: list[Finding] = field(default_factory=list)


def line_value(line: LineIn) -> Decimal | None:
    if line.unit_price is None:
        if line.stated_line_total is not None and line.quantity is None:
            return line.stated_line_total
        return None
    qty = line.quantity if line.quantity is not None else None
    if qty is None:
        return None
    basis = line.price_basis or Decimal(1)
    value = q2(qty * line.unit_price / basis)
    if line.kind == "discount":
        value = -abs(value)
    return value


def reconcile(
    lines: list[LineIn],
    stated_totals: list[StatedTotalIn],
    vat_amount: Decimal | None,
    vat_rate: Decimal | None,
    currency: str | None,
) -> ReconcileResult:
    res = ReconcileResult()
    f = res.findings

    if not [ln for ln in lines if ln.kind != "discount"]:
        f.append(
            Finding(
                "no_line_items",
                "blocking",
                "No line items could be established from the email or its attachments.",
                field="line_items",
            )
        )

    for ln in lines:
        where = f"line.{ln.position}"
        label = (
            f"Line {ln.position} ({ln.description[:40]})"
            if ln.description
            else f"Line {ln.position}"
        )
        if ln.quantity is None and ln.kind == "item":
            f.append(
                Finding(
                    "missing_quantity",
                    "blocking",
                    f"{label} has no quantity.",
                    field=f"{where}.quantity",
                )
            )
        elif ln.quantity is not None and ln.quantity <= 0 and ln.kind != "discount":
            f.append(
                Finding(
                    "invalid_quantity",
                    "blocking",
                    f"{label} has quantity {ln.quantity}.",
                    field=f"{where}.quantity",
                )
            )
        if ln.quantity_approximate:
            f.append(
                Finding(
                    "approximate_quantity",
                    "blocking",
                    f"{label}: the quantity is only approximate in the email. Confirm the exact quantity.",
                    field=f"{where}.quantity",
                )
            )
        if ln.unit_price is None and line_value(ln) is None:
            f.append(
                Finding(
                    "unpriced_line",
                    "blocking",
                    f"{label} has no price, so the requisition can't be totalled or routed.",
                    field=f"{where}.unit_price",
                )
            )

        value = line_value(ln)
        res.line_values[ln.position] = value
        if value is not None and ln.stated_line_total is not None and ln.unit_price is not None:
            stated = ln.stated_line_total if ln.kind != "discount" else -abs(ln.stated_line_total)
            if abs(stated - value) > LINE_TOLERANCE:
                f.append(
                    Finding(
                        "amount_conflict",
                        "blocking",
                        f"{label}: the stated line total {fmt(stated, currency)} doesn't equal "
                        f"quantity x unit price = {fmt(value, currency)}.",
                        field=f"{where}.stated_line_total",
                        details={"stated": str(stated), "computed": str(value)},
                    )
                )

    values = list(res.line_values.values())
    if lines and all(v is not None for v in values):
        all_sum = sum((v for v in values if v is not None), Decimal(0))
        gross_lines = sum(
            (
                v
                for ln, v in zip(lines, values, strict=True)
                if ln.kind != "discount" and v is not None
            ),
            Decimal(0),
        )
        res.approval_amount = q2(gross_lines)
        res.po_total = q2(all_sum)

        vat = vat_amount or Decimal(0)
        for i, st in enumerate(stated_totals):
            if st.overridden:
                continue
            if _VAT_LABEL.search(st.label) and not _TOTAL_LABEL.search(st.label):
                continue  # a VAT line, checked against the VAT rate below, not a total
            nets = {res.po_total, res.approval_amount}
            grosses = {n + vat for n in nets}
            candidates = {"no": nets, "yes": grosses}.get(st.includes_vat, nets | grosses)
            ok = any(abs(st.amount - c) <= TOTAL_TOLERANCE for c in candidates)
            if st.approximate:
                if not ok:
                    f.append(
                        Finding(
                            "approximate_total",
                            "info",
                            f'The email gives only an approximate total ("{st.label}": ~{fmt(st.amount, currency)}).',
                            field="stated_totals",
                        )
                    )
                continue
            if not ok:
                computed = min(candidates, key=lambda c: abs(st.amount - c))
                f.append(
                    Finding(
                        "amount_conflict",
                        "blocking",
                        f'The document states "{st.label}" as {fmt(st.amount, currency)}, but the '
                        f"lines add up to {fmt(computed, currency)}. The document contradicts itself, "
                        f"so it can't be routed until a human decides which figure is right.",
                        field=f"stated_totals.{i}",
                        details={
                            "index": i,
                            "stated": str(st.amount),
                            "computed": str(computed),
                            "label": st.label,
                        },
                    )
                )

        if vat_amount is not None and vat_rate is not None and vat_rate > 0:
            expected = q2(res.po_total * vat_rate / 100)
            if abs(expected - vat_amount) > Decimal("0.05"):
                f.append(
                    Finding(
                        "vat_mismatch",
                        "warning",
                        f"VAT of {fmt(vat_amount, currency)} doesn't match {vat_rate}% of the net "
                        f"{fmt(res.po_total, currency)} ({fmt(expected, currency)}). VAT doesn't "
                        f"affect routing.",
                        field="vat_amount",
                    )
                )
    return res


def to_chf(
    amount: Decimal, currency: str, fx: dict[str, Decimal]
) -> tuple[Decimal, Decimal] | None:
    rate = fx.get(currency)
    if rate is None:
        return None
    return q2(amount * rate), rate
