from datetime import date

from app.domain.dates import suggest_delivery_date
from app.domain.requester import resolve_requester
from app.ingest.eml import parse_eml
from tests.conftest import eml


def req_of(md, name):
    e = parse_eml(eml(name))
    return resolve_requester([m.as_dict() for m in e.thread], e.from_email, e.from_name, md)


def test_requester_rule_on_threads(md):
    assert (
        req_of(md, "email_03_thread_with_offer.eml").employee_id == "EMP-201"
    )  # supplier is external
    r45 = req_of(md, "email_45.eml")
    assert (r45.employee_id, r45.source) == ("EMP-202", "thread")  # Anna, not the forwarders
    assert req_of(md, "email_46.eml").employee_id == "EMP-501"  # Andrea proposed, Tobias confirmed
    assert req_of(md, "email_12.eml").source == "sender"


def test_thread_order_is_chronological():
    e = parse_eml(eml("email_45.eml"))
    assert [m.author_name for m in e.thread] == [
        "Jeroen Bakker",
        "Anna Widmer",
        "Lukas Frei",
        "Sophie Dubois",
    ]


def test_html_body_is_converted():
    e = parse_eml(eml("email_49.eml"))
    assert e.body_was_html
    assert "CC-4002" in e.body_text and "<" not in e.body_text


def test_pdf_text_extracted():
    e = parse_eml(eml("email_24.eml"))
    assert e.attachments[0].page_count == 1
    assert "4,830.00" in e.attachments[0].text


def test_email_01_mentions_a_pdf_but_has_none():
    e = parse_eml(eml("email_01_clean_with_pdf.eml"))
    assert e.attachments == []


def test_resend_has_same_body_different_content_hash():
    a, b = parse_eml(eml("email_01_clean_with_pdf.eml")), parse_eml(eml("email_29.eml"))
    assert a.body_text == b.body_text
    assert a.content_hash != b.content_hash


def test_relative_delivery_dates():
    ref = date(2026, 5, 4)
    assert suggest_delivery_date("Wird bis Ende Monat dringend benoetigt.", ref)[0] == date(
        2026, 5, 31
    )
    assert suggest_delivery_date("end of June at the latest", ref)[0] == date(2026, 6, 30)
    assert suggest_delivery_date("Benoetigt bis Mitte Juni", ref)[0] == date(2026, 6, 15)
    assert suggest_delivery_date("bis spaetestens Anfang Oktober", ref)[0] == date(2026, 10, 1)
    assert suggest_delivery_date("innerhalb der naechsten drei Wochen", ref)[0] == date(2026, 5, 25)
    assert suggest_delivery_date("for the line A retrofit in week 24", ref)[0] == date(2026, 6, 8)
    assert suggest_delivery_date("Lieferung bis 29.05.2026", ref)[0] == date(2026, 5, 29)
    assert suggest_delivery_date("haetten wir das bis gestern", ref) is None
