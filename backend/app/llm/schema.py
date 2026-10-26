"""The extraction output schema, enforced by the API (structured outputs, strict JSON
schema) and again by Pydantic. Every field is required-but-nullable: the model must
say null explicitly rather than leave something out, and the prompt says "null if
not stated, never infer".

The model reports what the document SAYS. It never computes totals, picks approvers,
or decides anything; that is deterministic code in app/domain.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LineKind = Literal["item", "freight", "surcharge", "discount"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedLine(_Strict):
    kind: LineKind = Field(description="item, freight (shipping/packing), surcharge, or discount")
    description: str
    item_code: str | None = Field(description="Article/item code exactly as written, or null")
    quantity: float | None
    quantity_is_approximate: bool = Field(
        description='True if the quantity is hedged ("roughly ten", "ca. 50", "around")'
    )
    unit: str | None = Field(description='Unit as written, e.g. "pcs", "Stk", "m", "kg", "h"')
    unit_price: float | None = Field(
        description="Price per price_basis units, as written; null if not stated"
    )
    price_basis: float | None = Field(
        description='Units the unit price refers to when not 1, e.g. 100 for "21.00 / 100"; else null'
    )
    stated_line_total: float | None = Field(description="Line total exactly as printed, or null")
    source_quote: str | None = Field(description="The line copied verbatim from the source")


class StatedTotal(_Strict):
    label: str = Field(
        description='The label as printed, e.g. "Subtotal", "Total inkl. MwSt", "Total"'
    )
    amount: float
    includes_vat: Literal["yes", "no", "unclear"]
    is_approximate: bool
    source: Literal["email", "attachment"]
    source_quote: str = Field(description="Verbatim text containing the amount")


class Extraction(_Strict):
    message_kind: Literal["new_request", "correction", "repeat", "not_a_purchase_request"]
    summary: str = Field(description="What is being bought, max 8 words, in English")

    supplier_name: str | None = Field(
        description="The vendor to order from, as written; never the customer"
    )
    supplier_name_quote: str | None
    supplier_vat_id: str | None = Field(description="Supplier VAT/UID/EIN exactly as written")
    supplier_address: str | None

    currency: str | None = Field(description="ISO 4217 code of the prices, e.g. CHF, EUR, USD, GBP")
    line_items: list[ExtractedLine]
    stated_totals: list[StatedTotal] = Field(
        description="Every total/subtotal figure printed anywhere (email and attachments)"
    )
    vat_amount: float | None
    vat_rate_percent: float | None

    cost_center_code: str | None = Field(
        description='Cost center code exactly as written, e.g. "CC-1002"'
    )
    cost_center_text: str | None = Field(
        description='Free-text cost center hint when no code is given, e.g. "London office"'
    )
    cost_center_quote: str | None

    delivery_date_text: str | None = Field(description="The requested delivery wording, verbatim")
    delivery_date_iso: str | None = Field(
        description="YYYY-MM-DD only if an absolute calendar date is written; null for relative phrases"
    )

    quote_reference: str | None
    quote_date_iso: str | None
    quote_valid_until_iso: str | None = Field(
        description="Quote validity end date if written as a date; null otherwise"
    )

    referenced_requests: list[str] = Field(
        description="Earlier request IDs mentioned, e.g. PR-2026-0412"
    )
    on_behalf_of: str | None = Field(
        description="Person the sender says they are ordering for, if stated"
    )
    claims_prior_approval: bool
    prior_approval_quote: str | None

    gl_account_suggestion: str | None = Field(description="One code from the GL list, or null")
    gl_account_reason: str | None

    notes_for_clerk: list[str] = Field(
        description="Short facts a purchasing clerk should know (conditions, caveats). Max 4."
    )
