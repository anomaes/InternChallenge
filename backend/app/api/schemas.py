"""Response and request models. They define the OpenAPI schema the frontend's TypeScript
types are generated from (frontend/src/api/schema.d.ts). Decimals travel as strings."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class Prov(BaseModel):
    status: str | None = (
        None  # confirmed | from_document | suggested | unverified | missing | conflict | computed
    )
    source: str | None = None
    reason: str | None = None
    evidence: str | None = None
    check: float | None = None
    grounded: bool | None = None


class PersonOut(BaseModel):
    id: str
    name: str
    email: str
    role: str
    deputy_for: str | None = None
    default_cost_center: str | None = None


class SupplierOut(BaseModel):
    id: str
    name: str
    vat_id: str | None
    country: str | None
    default_currency: str | None
    payment_terms_days: int | None
    preferred: bool
    status: str
    created_by_clerk: bool


class CostCenterOut(BaseModel):
    code: str
    name: str
    owner_employee_id: str
    owner_name: str
    department: str
    department_name: str
    head_employee_id: str | None
    head_name: str | None


class LineOut(BaseModel):
    id: int
    position: int
    kind: str
    description: str
    item_code: str | None
    quantity: Decimal | None
    quantity_approximate: bool
    unit: str | None
    unit_price: Decimal | None
    price_basis: Decimal | None
    stated_line_total: Decimal | None
    line_value: Decimal | None
    source_quote: str | None
    provenance: dict[str, Prov]


class IssueOut(BaseModel):
    id: int
    code: str
    severity: str
    blocks_order: bool
    field: str | None
    message: str
    details: dict[str, Any]
    origin: str
    status: str
    resolved_by: str | None
    resolved_at: datetime | None
    resolution_note: str | None
    created_at: datetime
    acknowledgeable: bool


class StepOut(BaseModel):
    run: int
    position: int
    roles: list[str]
    role_labels: list[str]
    holder_id: str | None = None
    approver_id: str | None
    approver_name: str | None
    on_behalf_of_id: str | None
    on_behalf_of_name: str | None
    note: str | None
    assigned_manually: bool
    status: str
    decided_at: datetime | None = None
    comment: str | None = None


class EventOut(BaseModel):
    id: int
    at: datetime
    actor: str
    actor_name: str
    kind: str
    message: str


class LLMRunOut(BaseModel):
    id: int
    kind: str
    model: str
    prompt_version: str
    attempt: int
    cached: bool
    ok: bool
    error: str | None
    validation: dict[str, Any]
    raw_output: str | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    created_at: datetime


class PurchaseOrderOut(BaseModel):
    id: int
    requisition_id: int
    requisition_public_id: str | None = None
    po_number: str | None
    http_status: int | None
    request: dict[str, Any]
    response: dict[str, Any]
    warnings: list[str]
    created_at: datetime


class AttachmentOut(BaseModel):
    id: int
    filename: str
    content_type: str
    size: int
    page_count: int | None
    text: str


class ThreadMessageOut(BaseModel):
    author_name: str | None
    author_email: str | None
    sent_at: str | None
    subject: str | None
    text: str
    position: int
    is_internal: bool
    employee_id: str | None


class EmailOut(BaseModel):
    id: int
    source_name: str
    message_id: str | None
    in_reply_to: str | None
    from_name: str | None
    from_email: str | None
    to: str | None
    subject: str | None
    sent_at: datetime | None
    received_at: datetime
    body_text: str
    body_was_html: bool
    thread: list[ThreadMessageOut]
    source_text: str
    attachments: list[AttachmentOut]


class RedactionOut(BaseModel):
    kind: str
    placeholder: str
    original: str  # already visible in source_text; lets the UI point at it


class StatedTotalOut(BaseModel):
    label: str
    amount: Decimal
    includes_vat: str
    approximate: bool
    source: str | None = None
    evidence: str | None = None
    overridden: bool = False


class CurrentStep(BaseModel):
    position: int
    total: int
    approver_id: str | None
    approver_name: str | None


class IssueCounts(BaseModel):
    blocking: int = 0
    warning: int = 0
    info: int = 0
    order: int = 0


class ReqSummary(BaseModel):
    id: int
    public_id: str
    state: str
    state_label: str
    stage: str | None
    title: str | None
    message_kind: str | None
    received_at: datetime
    sent_at: datetime | None
    updated_at: datetime
    requester_id: str | None
    requester_name: str | None
    requester_source: str | None
    supplier_id: str | None
    supplier_name: str | None
    supplier_name_doc: str | None
    supplier_status: str | None  # provenance status of the match
    supplier_blocked: bool
    cost_center_code: str | None
    currency: str | None
    po_total: Decimal | None
    approval_amount: Decimal | None
    approval_amount_chf: Decimal | None
    band_position: int | None
    current_step: CurrentStep | None
    issue_counts: IssueCounts
    top_issue: str | None
    top_issue_code: str | None
    linked_to_id: int | None
    linked_to_public_id: str | None
    link_type: str | None
    delivery_date: date | None
    redaction_count: int
    po_number: str | None
    source_name: str


class SupplierCandidate(BaseModel):
    id: str
    name: str
    score: int
    via: str | None = None


class CostCenterSuggestion(BaseModel):
    code: str
    name: str
    reason: str


class ReqDetail(ReqSummary):
    supplier: SupplierOut | None
    supplier_vat_doc: str | None
    supplier_address_doc: str | None
    cost_center: CostCenterOut | None
    cost_center_doc: str | None
    cost_center_text: str | None
    delivery_date_text: str | None
    delivery_date_suggested: date | None
    gl_account: str | None
    gl_account_name: str | None
    gl_account_suggested: str | None
    gl_account_suggested_name: str | None
    gl_account_reason: str | None
    quote_reference: str | None
    quote_date: date | None
    quote_valid_until: date | None
    vat_amount: Decimal | None
    vat_rate: Decimal | None
    fx_rate: Decimal | None
    stated_totals: list[StatedTotalOut]
    prior_approval_claim: str | None
    referenced_requests: list[str]
    on_behalf_of_text: str | None
    notes: list[str]
    link_reason: str | None
    approval_run: int
    rejection_reason: str | None
    rejected_by_name: str | None
    extraction_ok: bool | None
    provenance: dict[str, Prov]
    lines: list[LineOut]
    issues: list[IssueOut]
    steps: list[StepOut]  # current run, or the planned chain when no run is active
    steps_are_preview: bool
    step_history: list[StepOut]
    email: EmailOut
    events: list[EventOut]
    llm_runs: list[LLMRunOut]
    purchase_orders: list[PurchaseOrderOut]
    redactions: list[RedactionOut]
    supplier_candidates: list[SupplierCandidate]
    cost_center_suggestions: list[CostCenterSuggestion]
    order_blockers: list[str]
    can_submit: bool
    linked_from: list[ReqSummary]


# --------------------------------------------------------------------------- requests


class FieldsPatch(BaseModel):
    title: str | None = None
    requester_id: str | None = None
    supplier_id: str | None = None
    cost_center_code: str | None = None
    currency: str | None = None
    delivery_date: date | None = None
    gl_account: str | None = None
    vat_amount: Decimal | None = None
    clear: list[str] = Field(default_factory=list, description="Fields to set to null")


class LineIn(BaseModel):
    id: int | None = None
    kind: str = "item"
    description: str
    item_code: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    price_basis: Decimal | None = None


class ConfirmIn(BaseModel):
    field: str


class NoteIn(BaseModel):
    note: str | None = None


class ReasonIn(BaseModel):
    reason: str


class AssignApproverIn(BaseModel):
    position: int
    employee_id: str


class DuplicateActionIn(BaseModel):
    action: str  # close | keep | apply_correction
    note: str | None = None


class LinkIn(BaseModel):
    public_id: str


class DecisionIn(BaseModel):
    approver_id: str
    comment: str | None = None


class SupplierCreateIn(BaseModel):
    name: str
    vat_id: str | None = None
    country: str | None = None
    default_currency: str | None = None
    payment_terms_days: int | None = 30
    requisition_id: int | None = None


class SettingsOut(BaseModel):
    decision_checks_enabled: bool
    check_high: float
    check_low: float
    llm_cache_mode: str


class SettingsPatch(BaseModel):
    decision_checks_enabled: bool | None = None
    check_high: float | None = None
    check_low: float | None = None
    llm_cache_mode: str | None = None


class OkOut(BaseModel):
    ok: bool = True
    message: str | None = None
