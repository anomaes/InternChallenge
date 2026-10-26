"""The approval chain, driven by the real cases from the sample emails."""

from decimal import Decimal

import pytest

from app.domain.approval import plan_chain, select_band


def chain(plan):
    return [(s.approver_id, s.roles, s.on_behalf_of_id) for s in plan.steps]


def codes(plan):
    return [f.code for f in plan.findings]


@pytest.mark.parametrize(
    ("amount", "band"),
    [
        ("0", 1),
        ("999", 1),
        ("1000", 1),
        ("1000.50", 2),  # decision 1: upper bounds inclusive, so 1,000.50 is above band 1
        ("1001", 2),
        ("10000", 2),
        ("10000.01", 3),
        ("50000", 3),
        ("250000", 4),
        ("250000.01", 5),
        ("9999999", 5),
    ],
)
def test_band_boundaries(md, amount, band):
    assert select_band(Decimal(amount), md.bands).position == band


def test_email_12_chf_999_single_owner(md):
    plan = plan_chain(Decimal("999"), "CC-3001", "EMP-311", md)
    assert chain(plan) == [("EMP-301", ["cost_center_owner"], None)]
    assert plan.complete


def test_email_46_requester_holds_collapsed_step_needs_manual_approver(md):
    # Andrea Roth owns CC-1004 and heads OPS: one collapsed step, and it is hers.
    plan = plan_chain(Decimal("2600"), "CC-1004", "EMP-501", md)
    assert len(plan.steps) == 1
    assert plan.steps[0].roles == ["cost_center_owner", "department_head"]
    assert plan.steps[0].approver_id is None
    assert "needs_manual_approver" in codes(plan)
    assert not plan.complete


def test_manual_assignment_completes_the_chain(md):
    plan = plan_chain(Decimal("2600"), "CC-1004", "EMP-501", md, {"1": "EMP-701"})
    assert plan.complete
    assert plan.steps[0].approver_id == "EMP-701"
    assert plan.steps[0].assigned_manually


def test_manual_assignment_cannot_be_the_requester(md):
    plan = plan_chain(Decimal("2600"), "CC-1004", "EMP-501", md, {"1": "EMP-501"})
    assert not plan.complete


def test_email_50_cfo_claim_does_not_shorten_the_chain(md):
    plan = plan_chain(Decimal("62000"), "CC-1004", "EMP-110", md)
    assert chain(plan) == [
        ("EMP-501", ["cost_center_owner", "department_head"], None),
        ("EMP-701", ["finance"], None),
        ("EMP-801", ["cfo"], None),
    ]


def test_email_03_owner_requester_passes_on_without_recollapse(md):
    # Lukas owns CC-2001 and is the requester: step 1 goes to Markus, who also holds step 2.
    plan = plan_chain(Decimal("16602.24"), "CC-2001", "EMP-201", md)
    assert chain(plan) == [
        ("EMP-502", ["cost_center_owner"], "EMP-201"),
        ("EMP-502", ["department_head"], None),
        ("EMP-701", ["finance"], None),
    ]
    assert plan.complete


def test_email_45_eur_41200_thread_requester(md):
    plan = plan_chain(Decimal("39552.00"), "CC-2001", "EMP-202", md)
    assert [s.approver_id for s in plan.steps] == ["EMP-201", "EMP-502", "EMP-701"]


def test_ceo_requesting_above_250k_needs_manual_approver(md):
    plan = plan_chain(Decimal("300000"), "CC-3001", "EMP-901", md)
    assert [s.holder_id for s in plan.steps] == [
        "EMP-301",
        "EMP-503",
        "EMP-701",
        "EMP-801",
        "EMP-901",
    ]
    assert plan.steps[-1].approver_id is None
    assert "needs_manual_approver" in codes(plan)


def test_finance_deputy_is_never_the_approver(md):
    plan = plan_chain(Decimal("20000"), "CC-3001", "EMP-311", md)
    assert plan.steps[-1].approver_id == "EMP-701"  # not Thomas Egger (deputy)


def test_requester_in_the_middle_passes_to_next_distinct_person(md):
    # Markus Schmid (RND head) requests on CC-2002: his step goes to Daniela, who then approves twice.
    plan = plan_chain(Decimal("20000"), "CC-2002", "EMP-502", md)
    assert chain(plan) == [
        ("EMP-202", ["cost_center_owner"], None),
        ("EMP-701", ["department_head"], "EMP-502"),
        ("EMP-701", ["finance"], None),
    ]


def test_same_person_non_consecutive_approves_each_time(md):
    # Daniela as CC owner would appear again as finance with someone in between: no collapse.
    from dataclasses import replace

    from app.db.models import CostCenter

    cc = CostCenter(
        code="CC-3001", name="Office Zurich HQ", owner_employee_id="EMP-701", department="G&A"
    )
    md2 = replace(md, cost_centers={**md.cost_centers, "CC-3001": cc})
    plan = plan_chain(Decimal("20000"), "CC-3001", "EMP-311", md2)
    assert [s.approver_id for s in plan.steps] == ["EMP-701", "EMP-503", "EMP-701"]
