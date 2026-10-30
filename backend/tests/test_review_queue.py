"""KAN-28 / UC-06 extension — the authorised human review queue (State machine 9.5).

Evidence: case lifecycle, unauthorised assignment, review timeout and unresolved-case tests.
"""

from datetime import datetime, timedelta

import pytest

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.domain import EscalationCase, Product, User
from app.domain.enums import UserRole
from tests.conftest import login
from tests.test_basket_flow import confirmed_session


@pytest.fixture()
def escalated(client, alex):
    """Alex's basket with one item whose ingredient data has gone missing → withheld + case raised."""
    sid = confirmed_session(client, alex, "$120 for the week, two meals a day")
    basket = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=alex).json()["basket"]
    item = next(i for i in basket["items"] if not i["withheld"])
    with SessionLocal() as db:
        db.get(Product, item["product"]["id"]).data_complete = False
        db.commit()
    basket = client.post(f"/api/baskets/{basket['id']}/verify", headers=alex).json()["basket"]
    case = next(c for c in basket["cases"] if c["product"] == item["product"]["name"] and c["status"] != "resolved")
    return {"basket": basket, "item": item, "case_id": case["id"]}


@pytest.fixture()
def second_dietitian(client, escalated):
    """A second reviewer who joins after the case was raised, so it starts with Dr Sam Patel."""
    with SessionLocal() as db:
        db.add(User(email="lee@trolleymate.demo", display_name="Dr Lee Wong", role=UserRole.dietitian,
                    password_hash=hash_password("demo1234"), registration_no="DEMO-RD-02"))
        db.commit()
    return login(client, "lee@trolleymate.demo")


def case(client, headers, case_id):
    return client.get(f"/api/escalations/{case_id}", headers=headers).json()


def test_case_records_products_restrictions_and_uncertainty(client, sam, escalated):
    c = case(client, sam, escalated["case_id"])
    assert c["product"] == escalated["item"]["product"]["name"]
    assert {r["restriction"] for r in c["requirements"]} >= {"lactose", "tree_nuts"}
    assert c["evidence"]["confidence"] < 0.95
    assert any(f["kind"] == "missing_data" for f in c["evidence"]["findings"])
    assert c["status"] == "assigned" and c["assigned_to"] == "Dr Sam Patel"


def test_full_lifecycle_to_a_pass_releases_the_item(client, alex, sam, maya, escalated):
    cid, basket_id = escalated["case_id"], escalated["basket"]["id"]
    assert client.post(f"/api/escalations/{cid}/begin", headers=sam).json()["case"]["status"] == "under_review"
    c = client.post(f"/api/escalations/{cid}/request-info", json={"question": "Is there a full ingredient list?"}, headers=sam).json()["case"]
    assert [t["from"] for t in c["thread"]] == ["reviewer", "agent"]
    assert c["status"] == "under_review"  # the agent answered, so review continues
    c = client.post(f"/api/escalations/{cid}/resolve", json={"decision": "passed", "note": "Supplier sheet confirms no dairy or nuts."}, headers=sam).json()["case"]
    assert c["status"] == "resolved" and c["resolution"] == "passed"

    b = client.get(f"/api/baskets/{basket_id}", headers=alex).json()
    released = next(i for i in b["items"] if i["id"] == escalated["item"]["id"])
    assert not released["withheld"] and released["compliance"] == "compliant"
    trail = client.get(f"/api/audit?basket_id={basket_id}", headers=maya).json()
    assert any(r["action"] == "resolve_escalation" and r["agent"] == "Dietitian (Dr Sam Patel)" for r in trail)


def test_a_fail_excludes_the_item(client, alex, sam, escalated):
    cid, basket_id = escalated["case_id"], escalated["basket"]["id"]
    client.post(f"/api/escalations/{cid}/begin", headers=sam)
    client.post(f"/api/escalations/{cid}/resolve", json={"decision": "failed", "note": "Contains whey."}, headers=sam)
    b = client.get(f"/api/baskets/{basket_id}", headers=alex).json()
    assert escalated["item"]["id"] not in {i["id"] for i in b["items"]}
    assert any("removed after dietitian review" in n for n in b["notifications"])


def test_unresolved_case_keeps_the_item_withheld(client, alex, sam, escalated):
    basket_id = escalated["basket"]["id"]
    client.post(f"/api/escalations/{escalated['case_id']}/begin", headers=sam)  # started, not decided
    b = client.get(f"/api/baskets/{basket_id}", headers=alex).json()
    held = next(i for i in b["items"] if i["id"] == escalated["item"]["id"])
    assert held["withheld"] and b["status"] == "pending_review"
    assert b["total"] == pytest.approx(sum(i["line_total"] for i in b["items"] if not i["withheld"]), abs=0.01)
    assert client.post(f"/api/baskets/{basket_id}/accept", headers=alex).status_code == 400


def test_unauthorised_assignment_and_review_are_rejected(client, alex, sam, maya, second_dietitian, escalated):
    cid = escalated["case_id"]
    alex_id = client.get("/api/auth/me", headers=alex).json()["id"]
    lee_id = client.get("/api/auth/me", headers=second_dietitian).json()["id"]

    assert client.get("/api/escalations", headers=alex).status_code == 403  # shoppers never see the queue
    assert client.post(f"/api/escalations/{cid}/assign", json={"reviewer_id": lee_id}, headers=alex).status_code == 403
    # A dietitian can't hand a case to someone else, or take one that's already someone else's.
    assert client.post(f"/api/escalations/{cid}/assign", json={"reviewer_id": lee_id}, headers=sam).status_code == 403
    assert client.post(f"/api/escalations/{cid}/assign", json={"reviewer_id": lee_id}, headers=second_dietitian).status_code == 403
    # Even the founder can't assign a case to someone who isn't an authorised reviewer.
    r = client.post(f"/api/escalations/{cid}/assign", json={"reviewer_id": alex_id}, headers=maya)
    assert r.status_code == 400 and "not an authorised reviewer" in r.json()["detail"]
    # The assigned reviewer is the only dietitian who can act on it.
    assert client.post(f"/api/escalations/{cid}/begin", headers=second_dietitian).status_code == 400
    assert case(client, sam, cid)["assigned_to"] == "Dr Sam Patel"

    # The founder can reassign a waiting case.
    c = client.post(f"/api/escalations/{cid}/assign", json={"reviewer_id": lee_id}, headers=maya).json()["case"]
    assert c["assigned_to"] == "Dr Lee Wong"


def test_resolved_cases_cannot_be_reassigned(client, sam, maya, escalated):
    cid = escalated["case_id"]
    client.post(f"/api/escalations/{cid}/begin", headers=sam)
    client.post(f"/api/escalations/{cid}/resolve", json={"decision": "passed", "note": ""}, headers=sam)
    sam_id = client.get("/api/auth/me", headers=sam).json()["id"]
    assert client.post(f"/api/escalations/{cid}/assign", json={"reviewer_id": sam_id}, headers=maya).status_code == 400


def _expire(case_id: int) -> None:
    with SessionLocal() as db:
        db.get(EscalationCase, case_id).assigned_at = datetime.now() - timedelta(hours=3)
        db.commit()


def test_expired_assignment_is_requeued_to_another_reviewer(client, sam, second_dietitian, escalated):
    cid = escalated["case_id"]
    _expire(cid)
    client.get("/api/escalations", headers=second_dietitian)  # reading the queue runs the SLA sweep
    c = case(client, sam, cid)
    assert c["status"] == "assigned" and c["assigned_to"] == "Dr Lee Wong"


def test_expired_assignment_stays_queued_when_nobody_else_is_free(client, sam, maya, escalated):
    cid = escalated["case_id"]
    _expire(cid)
    client.get("/api/escalations", headers=maya)
    c = case(client, maya, cid)
    assert c["status"] == "open" and c["assigned_to"] is None  # waits for the founder or a new reviewer
    trail = client.get(f"/api/audit?basket_id={escalated['basket']['id']}", headers=maya).json()
    assert any(r["action"] == "release_reviewer" for r in trail)


def test_review_actions_require_an_open_review(client, sam, escalated):
    cid = escalated["case_id"]
    # Can't decide or ask questions before starting the review.
    assert client.post(f"/api/escalations/{cid}/resolve", json={"decision": "passed", "note": ""}, headers=sam).status_code == 400
    assert client.post(f"/api/escalations/{cid}/request-info", json={"question": "?"}, headers=sam).status_code == 400
    client.post(f"/api/escalations/{cid}/begin", headers=sam)
    assert client.post(f"/api/escalations/{cid}/resolve", json={"decision": "escalated", "note": ""}, headers=sam).status_code == 400


def test_changed_product_cannot_use_previous_human_approval(client, alex, sam, escalated):
    cid, bid = escalated["case_id"], escalated["basket"]["id"]
    client.post(f"/api/escalations/{cid}/begin", headers=sam)
    assert client.post(f"/api/escalations/{cid}/resolve", json={"decision": "passed"}, headers=sam).status_code == 200
    with SessionLocal() as db:
        p = db.get(Product, escalated["item"]["product"]["id"])
        p.tags = list(p.tags) + ["tree_nuts"]
        db.commit()
    response = client.post(f"/api/baskets/{bid}/verify", headers=alex)
    assert response.status_code == 200, response.text
    item = next(i for i in response.json()["basket"]["items"] if i["id"] == escalated["item"]["id"])
    assert item["compliance"] == "violation"
    assert client.post(f"/api/baskets/{bid}/accept", headers=alex).status_code == 400


def test_changed_evidence_requires_review_restart(client, alex, sam, escalated):
    cid, bid = escalated["case_id"], escalated["basket"]["id"]
    client.post(f"/api/escalations/{cid}/begin", headers=sam)
    with SessionLocal() as db:
        p = db.get(Product, escalated["item"]["product"]["id"])
        p.name += " revised label"
        db.commit()
    result = client.post(f"/api/escalations/{cid}/resolve", json={"decision": "passed"}, headers=sam)
    assert result.status_code == 400 and "evidence has changed" in result.text
    client.post(f"/api/baskets/{bid}/verify", headers=alex)
    refreshed = case(client, sam, cid)
    assert refreshed["status"] == "assigned"
    assert "Evidence changed" in refreshed["thread"][-1]["text"]
    client.post(f"/api/escalations/{cid}/begin", headers=sam)
    assert client.post(f"/api/escalations/{cid}/resolve", json={"decision": "passed"}, headers=sam).status_code == 200
