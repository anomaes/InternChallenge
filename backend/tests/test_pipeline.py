"""End to end: real emails, real (cached) model output, the real pipeline and API."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db.models import Issue, Requisition
from app.db.session import engine
from app.llm.provider import ExtractionCall, ExtractionError
from app.llm.schema import Extraction
from app.main import app
from app.services.pipeline import ingest_email, process
from tests.conftest import eml


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        c.post("/api/demo/reset")
        yield c


def deliver(name: str, extractor=None) -> int:
    with Session(engine) as s:
        rid = ingest_email(s, eml(name), name).id
    process(rid, extractor=extractor)
    return rid


def get(client, rid):
    return client.get(f"/api/requisitions/{rid}").json()


def open_codes(d, severity="blocking"):
    return {i["code"] for i in d["issues"] if i["status"] == "open" and i["severity"] == severity}


def test_clean_case_goes_straight_to_the_first_approver(client):
    rid = deliver("email_12.eml")
    d = get(client, rid)
    assert d["state"] == "PENDING_APPROVAL"
    assert d["approval_amount_chf"] == "999.00"
    assert [s["approver_id"] for s in d["steps"]] == ["EMP-301"]
    out = client.get("/api/outbox").json()
    assert any(n["recipient_id"] == "EMP-301" and n["requisition_id"] == rid for n in out)


def test_approval_guards_order_and_erp_down(client):
    rid = deliver("email_14.eml")  # CHF 1,001: Petra -> Andrea
    d = get(client, rid)
    assert [s["approver_id"] for s in d["steps"]] == ["EMP-102", "EMP-501"]
    r = client.post(f"/api/requisitions/{rid}/approve", json={"approver_id": "EMP-501"})
    assert r.status_code == 409 and "Not your turn" in r.json()["detail"]
    r = client.post(f"/api/requisitions/{rid}/approve", json={"approver_id": "EMP-111"})
    assert r.status_code == 409  # Miriam is the requester
    assert (
        client.post(f"/api/requisitions/{rid}/approve", json={"approver_id": "EMP-102"}).status_code
        == 200
    )
    d = client.post(f"/api/requisitions/{rid}/approve", json={"approver_id": "EMP-501"}).json()
    # Approved, but the delivery date is only a suggestion: no automatic order.
    assert d["state"] == "APPROVED"
    assert any("delivery date" in b for b in d["order_blockers"])
    d = client.post(f"/api/requisitions/{rid}/confirm", json={"field": "delivery_date"}).json()
    assert d["delivery_date"] == "2026-05-31" and d["state"] == "APPROVED"
    d = client.post(f"/api/requisitions/{rid}/order").json()
    # The test ERP URL points nowhere: the order fails visibly and the requisition stays approved.
    assert d["state"] == "APPROVED"
    assert "order_failed" in {i["code"] for i in d["issues"] if i["status"] == "open"}


def test_rejection_keeps_reason_and_resubmission_restarts_from_step_one(client):
    rid = deliver("email_21.eml")  # Hans requests on his own CC: Andrea approves twice
    d = get(client, rid)
    assert [(s["approver_id"], s["on_behalf_of_id"]) for s in d["steps"]] == [
        ("EMP-501", "EMP-101"),
        ("EMP-501", None),
    ]
    client.post(f"/api/requisitions/{rid}/approve", json={"approver_id": "EMP-501"})
    r = client.post(f"/api/requisitions/{rid}/decline", json={"approver_id": "EMP-501"})
    assert r.status_code == 409  # a reason is required
    d = client.post(
        f"/api/requisitions/{rid}/decline",
        json={"approver_id": "EMP-501", "comment": "Wrong cost center"},
    ).json()
    assert d["state"] == "REJECTED" and d["rejection_reason"] == "Wrong cost center"
    d = client.patch(f"/api/requisitions/{rid}", json={"cost_center_code": "CC-1002"}).json()
    d = client.post(f"/api/requisitions/{rid}/submit").json()
    assert d["state"] == "PENDING_APPROVAL" and d["approval_run"] == 2
    assert [s["approver_id"] for s in d["steps"]] == ["EMP-102", "EMP-501"]
    assert d["steps"][0]["status"] == "active"


def test_editing_a_routing_field_during_approval_restarts_the_chain(client):
    rid = deliver("email_33.eml")  # Tobias, CC-1001, CHF 1,800: Hans -> Andrea
    client.post(f"/api/requisitions/{rid}/approve", json={"approver_id": "EMP-101"})
    d = client.patch(f"/api/requisitions/{rid}", json={"cost_center_code": "CC-2001"}).json()
    assert d["state"] == "PENDING_APPROVAL" and d["approval_run"] == 2
    assert [(s["approver_id"], s["status"]) for s in d["steps"]] == [
        ("EMP-201", "active"),
        ("EMP-502", "waiting"),
    ]
    assert any(e["kind"] == "chain_restarted" for e in d["events"])


def test_price_edit_contradicting_the_document_goes_back_to_review(client):
    rid = deliver("email_22.eml")  # EUR 4,800 stated in the email
    lines = get(client, rid)["lines"]
    body = [
        {**ln, "unit_price": "1500.00" if ln["position"] == 1 else ln["unit_price"]} for ln in lines
    ]
    d = client.put(f"/api/requisitions/{rid}/lines", json=body).json()
    assert d["state"] == "NEEDS_REVIEW" and "amount_conflict" in open_codes(d)
    assert d["lines"][0]["stated_line_total"] is None  # described the old price


def test_self_approval_needs_a_manual_approver(client):
    rid = deliver("email_46.eml")
    d = get(client, rid)
    assert d["state"] == "NEEDS_REVIEW" and d["requester_id"] == "EMP-501"
    assert "needs_manual_approver" in open_codes(d)
    assert (
        client.post(
            f"/api/requisitions/{rid}/approvers", json={"position": 1, "employee_id": "EMP-501"}
        ).status_code
        == 422
    )
    client.post(
        f"/api/requisitions/{rid}/approvers", json={"position": 1, "employee_id": "EMP-701"}
    )
    d = client.post(f"/api/requisitions/{rid}/submit").json()
    assert d["state"] == "PENDING_APPROVAL" and d["steps"][0]["approver_id"] == "EMP-701"


def test_contradicting_document_never_routes_until_a_human_decides(client):
    rid = deliver("email_24.eml")
    d = get(client, rid)
    assert d["state"] == "NEEDS_REVIEW" and "amount_conflict" in open_codes(d)
    assert client.post(f"/api/requisitions/{rid}/submit").status_code == 409
    idx = next(i for i, t in enumerate(d["stated_totals"]) if t["amount"] == "4830.0")
    d = client.post(
        f"/api/requisitions/{rid}/stated-totals/{idx}/override", json={"note": "Lines checked"}
    ).json()
    assert "amount_conflict" not in open_codes(d)
    d = client.post(f"/api/requisitions/{rid}/submit").json()
    assert d["state"] == "PENDING_APPROVAL" and d["approval_amount_chf"] == "4204.80"


def test_blocked_supplier_cannot_be_waved_through(client):
    rid = deliver("email_09.eml")
    d = get(client, rid)
    issue = next(i for i in d["issues"] if i["code"] == "supplier_blocked")
    assert not issue["acknowledgeable"]
    assert (
        client.post(
            f"/api/requisitions/{rid}/issues/{issue['id']}/acknowledge", json={}
        ).status_code
        == 409
    )
    assert client.post(f"/api/requisitions/{rid}/submit").status_code == 409


def test_resend_is_linked_and_applied_as_correction(client):
    first = deliver("email_01_clean_with_pdf.eml")
    second = deliver("email_29.eml")
    d = get(client, second)
    assert d["linked_to_id"] == first and "suspected_duplicate" in open_codes(d)
    d = client.post(
        f"/api/requisitions/{second}/duplicate", json={"action": "apply_correction"}
    ).json()
    assert d["state"] == "CLOSED_DUPLICATE"
    orig = get(client, first)
    assert orig["state"] == "PENDING_APPROVAL" and orig["po_total"] == "1751.40"
    # The resend's email and PDF are now part of the original's source.
    [m] = orig["merged_emails"]
    assert m["requisition_id"] == second and m["link_type"] == "correction"
    assert [a["filename"] for a in m["email"]["attachments"]] == ["quote_acme_bearings.pdf"]
    assert "attachment_missing" not in open_codes(orig, "warning")


def test_closed_duplicate_is_not_part_of_the_original(client):
    client.post("/api/demo/reset")
    first = deliver("email_01_clean_with_pdf.eml")
    second = deliver("email_29.eml")
    client.post(f"/api/requisitions/{second}/duplicate", json={"action": "close"})
    orig = get(client, first)
    assert orig["merged_emails"] == [] and "attachment_missing" in open_codes(orig, "warning")


def test_clerk_merges_a_requisition_into_another(client):
    client.post("/api/demo/reset")
    first = deliver("email_01_clean_with_pdf.eml")
    second = deliver("email_29.eml")
    target = get(client, first)["public_id"]
    d = client.post(f"/api/requisitions/{second}/merge", json={"public_id": target}).json()
    assert d["state"] == "CLOSED_DUPLICATE" and d["link_type"] == "merged"
    assert "suspected_duplicate" not in open_codes(d)
    orig = get(client, first)
    assert orig["po_total"] == "1751.40" and orig["state"] == "PENDING_APPROVAL"
    assert [m["requisition_id"] for m in orig["merged_emails"]] == [second]
    assert any(e["kind"] == "merged" for e in orig["events"])
    # Closed now, so it can't be merged again; and nothing merges into itself.
    again = client.post(f"/api/requisitions/{second}/merge", json={"public_id": target})
    assert again.status_code == 409
    itself = client.post(f"/api/requisitions/{first}/merge", json={"public_id": target})
    assert itself.status_code == 404


def test_unknown_supplier_created_by_clerk(client):
    rid = deliver("email_08.eml")
    assert "supplier_unknown" in open_codes(get(client, rid))
    client.post(
        "/api/suppliers",
        json={
            "name": "Stahlhandel Wyss AG",
            "country": "CH",
            "default_currency": "CHF",
            "requisition_id": rid,
        },
    )
    d = get(client, rid)
    assert d["supplier"]["created_by_clerk"] and d["state"] == "NEEDS_REVIEW"
    assert "supplier_unknown" not in open_codes(d)


class Broken:
    model, prompt_version = "fake", "fake"

    def extract(self, source, feedback=None):
        raise ExtractionError("API down")


class Garbage:
    """Returns semantically invalid output twice: invalid values are dropped, never used."""

    model, prompt_version = "fake", "fake"

    def __init__(self):
        self.calls = 0

    def extract(self, source, feedback=None):
        self.calls += 1
        x = Extraction.model_validate_json(open_cached("email_12.eml"))
        x.currency, x.gl_account_suggestion, x.cost_center_code = "francs", "9999", "CC-3001"
        x.line_items[0].quantity = -3
        return ExtractionCall(x, x.model_dump_json(), "fake", "fake", 1, 1, 1, False)


def open_cached(name):
    from app.ingest.eml import parse_eml
    from app.ingest.source import build_source
    from app.llm.openai_extractor import OpenAIExtractor
    from app.privacy.redact import Redactor

    ex = OpenAIExtractor([], use_cache=True)
    with Session(engine) as s:
        from app.domain.master import MasterData

        md = MasterData.load(s)
    ex = OpenAIExtractor(sorted((g.code, g.name) for g in md.gl_accounts.values()), use_cache=True)
    return ex.extract(Redactor().redact(build_source(parse_eml(eml(name))))).raw


def test_extraction_failure_keeps_the_email_and_asks_the_clerk(client):
    rid = deliver("email_13.eml", extractor=Broken())
    d = get(client, rid)
    assert d["state"] == "NEEDS_REVIEW" and d["extraction_ok"] is False
    assert "extraction_failed" in open_codes(d)
    assert len([r for r in d["llm_runs"] if r["error"]]) == 2  # one retry


def test_garbage_output_is_retried_then_dropped(client):
    g = Garbage()
    rid = deliver("email_12.eml", extractor=g)
    d = get(client, rid)
    assert g.calls == 2
    assert d["currency"] is None and d["gl_account_suggested"] is None
    assert d["lines"][0]["quantity"] is None
    assert d["state"] == "NEEDS_REVIEW"
    assert {"currency_missing", "missing_quantity"} <= open_codes(d)


def test_requisitions_are_never_lost(client):
    with Session(engine) as s:
        assert all(r.public_id for r in s.exec(select(Requisition)))
        assert s.exec(select(Issue).where(Issue.code == "pipeline_error")).first() is None
