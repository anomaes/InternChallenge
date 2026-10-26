from decimal import Decimal as D

from app.domain.reconcile import LineIn, StatedTotalIn, reconcile


def line(pos, qty, price, kind="item", basis=None, stated=None, approx=False):
    return LineIn(
        pos,
        kind,
        f"line {pos}",
        D(qty) if qty is not None else None,
        D(price) if price is not None else None,
        D(basis) if basis else None,
        D(stated) if stated is not None else None,
        approx,
    )


def codes(res):
    return sorted(f.code for f in res.findings)


def test_kabelwerk_subtotal_contradicts_total_blocks():
    res = reconcile(
        [line(1, 600, "2.30", stated="1380"), line(2, 200, "15.00", stated="3000")],
        [StatedTotalIn("Subtotal", D("4380"), "no"), StatedTotalIn("Total", D("4830"), "unclear")],
        None,
        None,
        "EUR",
    )
    assert res.approval_amount == D("4380.00")
    assert codes(res) == ["amount_conflict"]
    assert "4,830.00" in res.findings[0].message


def test_overridden_total_no_longer_conflicts():
    res = reconcile(
        [line(1, 600, "2.30"), line(2, 200, "15.00")],
        [StatedTotalIn("Total", D("4830"), "unclear", overridden=True)],
        None,
        None,
        "EUR",
    )
    assert codes(res) == []


def test_price_per_100():
    res = reconcile(
        [line(1, 15000, "21.00", basis="100", stated="3150")],
        [StatedTotalIn("Total", D("3150"), "no")],
        None,
        None,
        "EUR",
    )
    assert res.approval_amount == D("3150.00")
    assert codes(res) == []


def test_discount_not_subtracted_for_approval_but_for_po():
    res = reconcile(
        [
            line(1, 4000, "1.20"),
            line(2, 2000, "0.85"),
            line(3, 1, "-900", kind="discount", stated="-900"),
        ],
        [StatedTotalIn("Zwischensumme", D("5600"), "no")],
        D("0"),
        D("0"),
        "EUR",
    )
    assert res.approval_amount == D("6500.00")  # decision 3
    assert res.po_total == D("5600.00")
    assert codes(res) == []


def test_freight_counts_for_approval():
    res = reconcile(
        [line(1, 25000, "0.28"), line(2, 30000, "0.07"), line(3, 1, "640", kind="freight")],
        [StatedTotalIn("Total", D("9740"), "unclear")],
        D("0"),
        D("0"),
        "USD",
    )
    assert res.approval_amount == D("9740.00")


def test_gross_total_with_vat_is_consistent_and_vat_excluded():
    res = reconcile(
        [line(1, 1, "7450"), line(2, 2, "1125")],
        [
            StatedTotalIn("Zwischensumme", D("9700"), "no"),
            StatedTotalIn("Total inkl. MwSt", D("10485.70"), "yes"),
        ],
        D("785.70"),
        D("8.1"),
        "CHF",
    )
    assert res.approval_amount == D("9700.00")
    assert codes(res) == []


def test_unpriced_line_blocks_and_no_amount():
    res = reconcile([line(1, 2, "2400"), line(2, 1, None)], [], None, None, "CHF")
    assert "unpriced_line" in codes(res)
    assert res.approval_amount is None


def test_line_total_mismatch():
    res = reconcile([line(1, 4, "100", stated="500")], [], None, None, "CHF")
    assert codes(res) == ["amount_conflict"]


def test_approximate_quantity_blocks():
    res = reconcile([line(1, 10, "500", approx=True)], [], None, None, "EUR")
    assert "approximate_quantity" in codes(res)


def test_no_lines():
    res = reconcile([], [], None, None, None)
    assert codes(res) == ["no_line_items"]


def test_vat_mismatch_warns():
    res = reconcile([line(1, 1, "100")], [], D("20"), D("8.1"), "CHF")
    assert [f.severity for f in res.findings] == ["warning"]
