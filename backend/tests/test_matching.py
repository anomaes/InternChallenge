from app.domain.matching import (
    match_cost_center,
    match_supplier,
    normalise_cc,
    supplier_status_findings,
)


def sup(md):
    return list(md.suppliers.values())


def codes(m):
    return [f.code for f in m.findings]


def test_vat_match_wins(md):
    m = match_supplier("ACME Bearing Group Ltd", "GB887766554", sup(md))
    assert (m.supplier_id, m.method, codes(m)) == ("SUP-006", "vat", [])


def test_vat_formatting_is_normalised(md):
    assert match_supplier(None, "CHE-101.234.567", sup(md)).supplier_id == "SUP-002"
    assert match_supplier(None, "che101234567mwst", sup(md)).supplier_id == "SUP-002"


def test_mueller_name_and_vat_point_to_different_suppliers(md):
    # email_11: the quote says "Mueller Industriebedarf AG" but carries Müller Industriebedarf's VAT ID.
    m = match_supplier("Mueller Industriebedarf AG", "DE445566778", sup(md))
    assert m.supplier_id is None
    assert codes(m) == ["supplier_conflict"]


def test_umlaut_transliteration_matches_the_right_mueller(md):
    m = match_supplier("Mueller Industriebedarf", "DE445566778", sup(md))
    assert m.supplier_id == "SUP-004"


def test_name_only_exact_match_warns(md):
    m = match_supplier("Office Plus Schweiz", None, sup(md))
    assert m.supplier_id == "SUP-005"
    assert [(f.code, f.severity) for f in m.findings] == [("supplier_name_only", "warning")]


def test_legal_form_is_ignored(md):
    assert match_supplier("Elektro Buehler", None, sup(md)).supplier_id == "SUP-014"
    assert match_supplier("Lombardi Componenti Srl", None, sup(md)).supplier_id == "SUP-017"


def test_acme_lookalikes_are_not_guessed(md):
    m = match_supplier("Acme", None, sup(md))
    assert m.supplier_id is None
    assert codes(m) == ["supplier_uncertain"]
    assert {c["id"] for c in m.candidates} >= {"SUP-001", "SUP-006"}


def test_unknown_supplier_blocks(md):
    m = match_supplier("Stahlhandel Wyss AG", None, sup(md))
    assert m.supplier_id is None
    assert codes(m) == ["supplier_unknown"]


def test_blocked_supplier(md):
    assert [f.code for f in supplier_status_findings(md.suppliers["SUP-018"])] == [
        "supplier_blocked"
    ]


def test_cost_center_exact_only(md):
    assert match_cost_center("CC-1002", md.cost_centers) == ("CC-1002", [])
    assert match_cost_center("cc 1002", md.cost_centers)[0] == "CC-1002"
    code, findings = match_cost_center("CC-9100", md.cost_centers)
    assert code is None and findings[0].code == "cost_center_unknown"
    assert match_cost_center(None, md.cost_centers)[1][0].code == "cost_center_missing"


def test_normalise_cc():
    assert normalise_cc("KST 2001") == "CC-2001"
    assert normalise_cc("CC-9100") == "CC-9100"
