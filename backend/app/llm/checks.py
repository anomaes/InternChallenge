"""Second opinion on the extraction with the OpenAI Decisions API (switchable, off by
default).

The substring grounding check catches *invented* values, but not *misattributed* ones
(the subtotal read as the total, a unit price from the wrong line). Each routing-relevant
value becomes a predicate ("The document states a unit price of 15.00 EUR per m for
'Cable carrier CK-40'") answered with a calibrated probability by a model that doesn't
generate text. All questions go in one call.
"""

import time
from dataclasses import dataclass
from decimal import Decimal

import openai

from app.config import settings
from app.llm.cache import cache_get, cache_key, cache_put

CHECK_VERSION = "checks_v2"

# Fields whose low probability blocks routing (the rest only warn).
ROUTING_FIELDS = {"supplier", "cost_center", "currency", "po_total"}


@dataclass
class Question:
    field: str  # provenance key, e.g. "supplier", "line.2.unit_price"
    text: str


@dataclass
class CheckResult:
    probabilities: dict[str, float | None]  # None = refused
    model: str
    cached: bool
    latency_ms: int | None
    input_tokens: int | None


def _qty(value: Decimal) -> str:
    d = Decimal(value)
    return f"{d:,.0f}" if d == d.to_integral_value() else f"{d.normalize():,f}"


def _money(value: Decimal) -> str:
    return f"{Decimal(value):,.2f}"


def build_questions(req: dict, lines: list[dict]) -> list[Question]:
    """`req`/`lines` are plain dicts of the requisition's current values.

    Phrasing matters. Tuning on the sample emails showed that separate quantity and
    price predicates ("a unit price of 18,700 EUR each") gave confident false negatives
    on lump-sum lines and long tables, while one predicate per line stating quantity
    and price together scored 1.00 on every correct line and 0.00 on planted errors.
    """
    qs: list[Question] = []
    cur = req.get("currency") or ""
    if req.get("supplier_name_doc"):
        qs.append(
            Question(
                "supplier",
                f"The document names '{req['supplier_name_doc']}' as the supplier the goods would be bought from.",
            )
        )
    if req.get("supplier_vat_doc"):
        qs.append(
            Question(
                "supplier_vat",
                f"The document gives '{req['supplier_vat_doc']}' as the supplier's VAT/UID number.",
            )
        )
    for ln in lines:
        if ln.get("quantity") is None or ln.get("unit_price") is None:
            continue
        desc = (ln.get("description") or "")[:80]
        unit = f" {ln['unit']}" if ln.get("unit") else ""
        basis = ln.get("price_basis")
        per = f" per {_qty(basis)}" if basis and basis != 1 else ""
        qs.append(
            Question(
                f"line.{ln['position']}.line",
                f"The document lists '{desc}' with quantity {_qty(ln['quantity'])}{unit} at a unit price of {_money(ln['unit_price'])} {cur}{per}.",
            )
        )
    if req.get("po_total") is not None:
        before_vat = " before VAT" if req.get("vat_amount") else ""
        qs.append(
            Question(
                "po_total",
                f"According to the document, the requested items cost {_money(req['po_total'])} {cur} in total{before_vat}.",
            )
        )
    if cur:
        qs.append(Question("currency", f"The prices in the document are in {cur}."))
    if req.get("cost_center_doc"):
        qs.append(
            Question(
                "cost_center",
                f"The requester says the purchase should be charged to cost center {req['cost_center_doc']}.",
            )
        )
    if req.get("delivery_date_doc"):
        qs.append(
            Question(
                "delivery_date", f"The requester asks for delivery by {req['delivery_date_doc']}."
            )
        )
    return qs[:400]


def run_checks(source: str, questions: list[Question], *, use_cache: bool = True) -> CheckResult:
    model = settings.decisions_model
    payload = [{"type": "predicate", "name": q.field, "instructions": q.text} for q in questions]
    key = cache_key(
        "check", model, CHECK_VERSION, source, *(q.field + "|" + q.text for q in questions)
    )
    if use_cache and (hit := cache_get(key)):
        return CheckResult(
            hit["probabilities"], hit["model"], True, hit.get("latency_ms"), hit.get("input_tokens")
        )

    api_key = settings.api_key()
    if not api_key:
        raise RuntimeError("No OPENAI_API_KEY configured.")
    client = openai.OpenAI(api_key=api_key, timeout=60, max_retries=2)
    started = time.monotonic()
    resp = client.decisions.create(model=model, input=source, questions=payload)  # type: ignore[arg-type]
    latency = int((time.monotonic() - started) * 1000)

    probs: dict[str, float | None] = {}
    for q, ans in zip(questions, resp.answers, strict=False):
        probs[q.field] = getattr(ans, "probability", None) if ans.type == "predicate" else None
    result = CheckResult(
        probs, resp.model, False, latency, resp.usage.input_tokens if resp.usage else None
    )
    cache_put(
        key,
        {
            "probabilities": probs,
            "model": resp.model,
            "latency_ms": latency,
            "input_tokens": result.input_tokens,
        },
    )
    return result
