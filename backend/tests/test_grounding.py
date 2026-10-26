from decimal import Decimal as D

from app.llm.schema import ExtractedLine, Extraction, StatedTotal
from app.llm.validate import drop_invalid, ground, numbers_in, semantic_errors

SOURCE = """### EMAIL BODY
4 Stk Stahlplatte, je CHF 480.00
Total CHF 3'200.00. Kostenstelle CC-1004. Lieferung bis 29.05.2026.
SwissElectro AG, UID: CHE-101.234.567 MWST
Kunststoffclip KC-8   15000   Stk   21.00 / 100   3,150.00
roughly ten sensors
"""


def extraction(**over) -> Extraction:
    base = dict(
        message_kind="new_request",
        summary="Steel",
        supplier_name="SwissElectro AG",
        supplier_name_quote=None,
        supplier_vat_id="CHE-101.234.567 MWST",
        supplier_address=None,
        currency="CHF",
        line_items=[
            ExtractedLine(
                kind="item",
                description="Stahlplatte",
                item_code=None,
                quantity=4,
                quantity_is_approximate=False,
                unit="Stk",
                unit_price=480.0,
                price_basis=None,
                stated_line_total=None,
                source_quote="4 Stk Stahlplatte, je CHF 480.00",
            )
        ],
        stated_totals=[
            StatedTotal(
                label="Total",
                amount=3200,
                includes_vat="unclear",
                is_approximate=False,
                source="email",
                source_quote="Total CHF 3'200.00",
            )
        ],
        vat_amount=None,
        vat_rate_percent=None,
        cost_center_code="CC-1004",
        cost_center_text=None,
        cost_center_quote="Kostenstelle CC-1004",
        delivery_date_text="Lieferung bis 29.05.2026",
        delivery_date_iso="2026-05-29",
        quote_reference=None,
        quote_date_iso=None,
        quote_valid_until_iso=None,
        referenced_requests=[],
        on_behalf_of=None,
        claims_prior_approval=False,
        prior_approval_quote=None,
        gl_account_suggestion="5400",
        gl_account_reason=None,
        notes_for_clerk=[],
    )
    base.update(over)
    return Extraction(**base)


def test_number_formats():
    nums = numbers_in("1'250.00 1.250,00 1,250.00 0.21 20,000 8.1% ten")
    assert {D("1250"), D("0.21"), D("20000"), D("8.1"), D("10")} <= nums


def test_clean_extraction_is_grounded():
    assert ground(extraction(), SOURCE) == {}


def test_invented_values_are_flagged():
    x = extraction(
        cost_center_code="CC-2001", delivery_date_iso="2026-05-30", supplier_vat_id="DE999"
    )
    x.line_items[0].unit_price = 490.0
    bad = ground(x, SOURCE)
    assert set(bad) == {"cost_center", "delivery_date", "supplier_vat", "line.1.unit_price"}


def test_semantic_errors_and_drop():
    x = extraction(currency="francs", gl_account_suggestion="9999", delivery_date_iso="2026-02-31")
    x.line_items[0].quantity = -4
    errs = semantic_errors(x, {"5400"})
    assert len(errs) == 4
    cleaned, dropped = drop_invalid(x, {"5400"})
    assert cleaned.currency is None and cleaned.gl_account_suggestion is None
    assert cleaned.delivery_date_iso is None and cleaned.line_items[0].quantity is None
    assert set(dropped) == {
        "currency",
        "gl_account_suggestion",
        "delivery_date_iso",
        "line_items[1].quantity",
    }
