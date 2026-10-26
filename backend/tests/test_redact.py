from app.privacy.redact import Redactor, ahv_ok, iban_ok, luhn_ok


def test_validators():
    assert luhn_ok("4111111111111111")
    assert not luhn_ok("4111111111111112")
    assert iban_ok("CH93 0076 2011 6238 5295 7")
    assert not iban_ok("CH93 0076 2011 6238 5295 8")
    assert ahv_ok("756.9217.0769.85")
    assert not ahv_ok("756.9217.0769.84")


def test_redacts_and_keeps_mapping_consistent():
    r = Redactor()
    text = (
        "Card 4111 1111 1111 1111, again 4111111111111111. IBAN CH93 0076 2011 6238 5295 7. "
        "AHV 756.9217.0769.85. Passwort: hunter2 and key sk-abcdefghijklmnopqrstuvwxyz123456"
    )
    out = r.redact(text)
    assert (
        "4111" not in out and "CH93" not in out and "756.9217" not in out and "hunter2" not in out
    )
    assert out.count("[CARD_1]") == 2
    assert "[IBAN_1]" in out and "[AHV_1]" in out and "[SECRET_1]" in out and "[SECRET_2]" in out
    assert {k for k, _, _ in r.items()} == {"CARD", "IBAN", "AHV", "SECRET"}


def test_no_false_positives_on_business_identifiers():
    text = (
        "UID: CHE-101.234.567 MWST, VAT: NL004567891B01, JP-9010001234567, US-EIN-841234567, "
        "IT01234567890, Quote no.: Q-2026-04812, Total: 1,751.40 EUR, 20,000 pcs, Tel +41 44 123 45 67"
    )
    r = Redactor()
    assert r.redact(text) == text
