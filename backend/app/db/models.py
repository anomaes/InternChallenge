"""Database tables.

Master data (suppliers ... fx_rates) is seeded from master_data.json and is the only
place the application reads reference data from at request time.

Money is stored as TEXT through `DecimalText`: SQLite has no decimal type, and a
float column would turn CHF 1,000.50 into 1000.4999999.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Column, LargeBinary, String, TypeDecorator
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class DecimalText(TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        return None if value is None else str(Decimal(value))

    def process_result_value(self, value: Any, dialect: Any) -> Decimal | None:
        return None if value is None else Decimal(value)


def money(**kw: Any) -> Any:
    return Field(default=None, sa_column=Column(DecimalText(), **kw))


def json_col(default_factory: Any = dict) -> Any:
    return Field(default_factory=default_factory, sa_column=Column(JSON, nullable=False))


# --------------------------------------------------------------------------- master data


class Supplier(SQLModel, table=True):
    __tablename__ = "suppliers"
    id: str = Field(primary_key=True)
    name: str
    vat_id: str | None = None
    country: str | None = None
    default_currency: str | None = None
    payment_terms_days: int | None = None
    preferred: bool = False
    status: str = "active"
    # Set when a clerk created the record from an unknown-supplier issue.
    created_by_clerk: bool = False


class Department(SQLModel, table=True):
    __tablename__ = "departments"
    code: str = Field(primary_key=True)
    name: str
    head_employee_id: str


class CostCenter(SQLModel, table=True):
    __tablename__ = "cost_centers"
    code: str = Field(primary_key=True)
    name: str
    owner_employee_id: str
    department: str


class Employee(SQLModel, table=True):
    __tablename__ = "employees"
    id: str = Field(primary_key=True)
    name: str
    email: str = Field(index=True)
    role: str
    deputy_for: str | None = None
    default_cost_center: str | None = None


class GLAccount(SQLModel, table=True):
    __tablename__ = "gl_accounts"
    code: str = Field(primary_key=True)
    name: str


class ApprovalBand(SQLModel, table=True):
    __tablename__ = "approval_bands"
    position: int = Field(primary_key=True)
    lower: Decimal = money(nullable=False)
    upper: Decimal | None = money()  # inclusive; None = no upper bound
    required_roles: list[str] = json_col(list)


class FxRate(SQLModel, table=True):
    __tablename__ = "fx_rates"
    currency: str = Field(primary_key=True)
    rate_to_chf: Decimal = money(nullable=False)


# --------------------------------------------------------------------------- requisitions


class Email(SQLModel, table=True):
    __tablename__ = "emails"
    id: int | None = Field(default=None, primary_key=True)
    source_name: str  # file name of the sample, or the uploaded name
    message_id: str | None = Field(default=None, index=True)
    in_reply_to: str | None = None
    references: list[str] = json_col(list)
    from_name: str | None = None
    from_email: str | None = None
    to: str | None = None
    subject: str | None = None
    sent_at: datetime | None = None  # aware, UTC
    sent_date_local: date | None = None  # calendar date in the sender's timezone
    received_at: datetime = Field(default_factory=utcnow)
    body_text: str = ""
    body_was_html: bool = False
    thread: list[dict] = json_col(list)  # chronological, earliest first
    content_hash: str = Field(index=True)  # body + attachments, for resend detection
    raw: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    # The labelled text the model sees (unredacted copy, kept locally for the source view).
    source_text: str = ""


class Attachment(SQLModel, table=True):
    __tablename__ = "attachments"
    id: int | None = Field(default=None, primary_key=True)
    email_id: int = Field(foreign_key="emails.id", index=True)
    filename: str
    content_type: str
    size: int
    sha256: str
    page_count: int | None = None
    text: str = ""
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))


class Requisition(SQLModel, table=True):
    __tablename__ = "requisitions"
    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(default="", index=True)
    email_id: int = Field(foreign_key="emails.id")
    state: str = Field(default="INBOX", index=True)
    stage: str | None = None  # sub-stage while PROCESSING
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    title: str | None = None
    message_kind: str | None = None

    requester_id: str | None = None
    requester_source: str | None = None  # sender | thread | clerk
    on_behalf_of_text: str | None = None

    supplier_id: str | None = None
    supplier_name_doc: str | None = None
    supplier_vat_doc: str | None = None
    supplier_address_doc: str | None = None

    cost_center_code: str | None = None
    cost_center_doc: str | None = None  # code as written in the document
    cost_center_text: str | None = None  # free-text hint ("London office")

    currency: str | None = None
    delivery_date: date | None = None
    delivery_date_text: str | None = None
    delivery_date_suggested: date | None = None
    gl_account: str | None = None
    gl_account_suggested: str | None = None
    gl_account_reason: str | None = None

    quote_reference: str | None = None
    quote_date: date | None = None
    quote_valid_until: date | None = None

    # Amounts in the requisition currency. approval_amount = lines + freight, excl. VAT,
    # discounts not subtracted. po_total = net after discount, excl. VAT.
    approval_amount: Decimal | None = money()
    approval_amount_chf: Decimal | None = money()
    fx_rate: Decimal | None = money()
    po_total: Decimal | None = money()
    vat_amount: Decimal | None = money()
    vat_rate: Decimal | None = money()
    stated_totals: list[dict] = json_col(list)
    band_position: int | None = None

    prior_approval_claim: str | None = None
    referenced_requests: list[str] = json_col(list)
    notes: list[str] = json_col(list)

    linked_to_id: int | None = Field(default=None, foreign_key="requisitions.id")
    link_type: str | None = None  # duplicate | correction | repeat | related
    link_reason: str | None = None

    approval_run: int = 0
    manual_approvers: dict[str, str] = json_col(dict)  # step position -> employee id
    rejection_reason: str | None = None
    rejected_by: str | None = None

    provenance: dict[str, dict] = json_col(dict)  # field -> {status, source, reason, ...}
    redaction_count: int = 0
    extraction_ok: bool | None = None
    idempotency_key: str | None = None


class LineItem(SQLModel, table=True):
    __tablename__ = "line_items"
    id: int | None = Field(default=None, primary_key=True)
    requisition_id: int = Field(foreign_key="requisitions.id", index=True)
    position: int
    kind: str = "item"  # item | freight | discount | surcharge
    description: str = ""
    item_code: str | None = None
    quantity: Decimal | None = money()
    quantity_approximate: bool = False
    unit: str | None = None
    unit_price: Decimal | None = money()
    price_basis: Decimal | None = money()  # unit price is per this many units (default 1)
    stated_line_total: Decimal | None = money()
    source_quote: str | None = None
    provenance: dict[str, dict] = json_col(dict)


class Issue(SQLModel, table=True):
    __tablename__ = "issues"
    id: int | None = Field(default=None, primary_key=True)
    requisition_id: int = Field(foreign_key="requisitions.id", index=True)
    code: str
    severity: str  # blocking | warning | info
    blocks_order: bool = False
    field: str | None = None
    message: str
    details: dict = json_col(dict)
    origin: str = "evaluate"  # evaluate (recomputed on every change) | ingest (sticky)
    status: str = "open"  # open | acknowledged | resolved
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    resolution_note: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ApprovalStep(SQLModel, table=True):
    __tablename__ = "approval_steps"
    id: int | None = Field(default=None, primary_key=True)
    requisition_id: int = Field(foreign_key="requisitions.id", index=True)
    run: int
    position: int
    roles: list[str] = json_col(list)
    approver_id: str | None = None
    on_behalf_of_id: str | None = None  # the role holder who could not approve
    note: str | None = None
    assigned_manually: bool = False
    status: str = "waiting"  # waiting | active | approved | rejected | superseded
    decided_at: datetime | None = None
    comment: str | None = None


class LLMRun(SQLModel, table=True):
    """One extraction or decision-check call (or cache hit)."""

    __tablename__ = "llm_runs"
    id: int | None = Field(default=None, primary_key=True)
    requisition_id: int = Field(foreign_key="requisitions.id", index=True)
    kind: str  # extract | check
    model: str
    prompt_version: str
    attempt: int = 1
    cached: bool = False
    ok: bool = False
    error: str | None = None
    validation: dict = json_col(dict)
    raw_output: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Redaction(SQLModel, table=True):
    __tablename__ = "redactions"
    id: int | None = Field(default=None, primary_key=True)
    email_id: int = Field(foreign_key="emails.id", index=True)
    kind: str
    placeholder: str
    original: str  # local only, never sent to the AI


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"
    id: int | None = Field(default=None, primary_key=True)
    requisition_id: int | None = Field(default=None, foreign_key="requisitions.id")
    recipient_id: str | None = None
    recipient_label: str
    subject: str
    body: str
    link: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Event(SQLModel, table=True):
    __tablename__ = "events"
    id: int | None = Field(default=None, primary_key=True)
    requisition_id: int | None = Field(default=None, foreign_key="requisitions.id", index=True)
    at: datetime = Field(default_factory=utcnow)
    actor: str  # system | clerk | EMP-xxx
    kind: str
    message: str
    data: dict = json_col(dict)


class PurchaseOrder(SQLModel, table=True):
    __tablename__ = "purchase_orders"
    id: int | None = Field(default=None, primary_key=True)
    requisition_id: int = Field(foreign_key="requisitions.id", index=True)
    po_number: str | None = None
    http_status: int | None = None
    request: dict = json_col(dict)
    response: dict = json_col(dict)
    warnings: list[str] = json_col(list)
    created_at: datetime = Field(default_factory=utcnow)


class AppSetting(SQLModel, table=True):
    __tablename__ = "settings"
    key: str = Field(primary_key=True)
    value: Any = Field(sa_column=Column(JSON))
