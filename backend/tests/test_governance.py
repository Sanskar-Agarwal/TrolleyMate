"""KAN-27 / UC-07 — explanations grounded in recorded evidence, and independent audit review.

Evidence: linked explanation/audit examples, missing-evidence and permission tests.
"""

from sqlalchemy import delete

from app.core.db import SessionLocal
from app.domain import AuditRecord, ComplianceVerdict
from tests.test_basket_flow import confirmed_session


def build(client, headers, text="$80 for the week, two meals a day for myself", goal="balanced"):
    sid = confirmed_session(client, headers, text)
    r = client.post(f"/api/sessions/{sid}/basket", json={"goal": goal}, headers=headers).json()
    assert r["status"] == "ok", r
    return r["basket"]


def test_basket_explanation_cites_constraints_prices_tools_and_verdict(client, riley):
    b = build(client, riley)
    e = client.get(f"/api/baskets/{b['id']}/explain", headers=riley).json()
    assert e["available"]
    ev = e["evidence"]
    assert ev["missing"] == []
    assert ev["constraints"]["budget"] == 80 and ev["constraints"]["days"] == 7
    quoted = {p["item"] for p in ev["prices"]}
    assert quoted == {i["product"]["name"] for i in b["items"]}  # every line's price is on record
    assert ev["verdict"]["status"] in ("passed", "escalated")
    assert ev["tools"]["solver"] is not None
    actions = {r["action"] for r in ev["audit_trail"]}
    assert {"verify_basket", "optimise_basket"} <= actions
    assert "safety check" in e["text"]  # the verdict made it into the wording


def test_item_explanation_cites_its_price_quote_and_safety_finding(client, riley):
    b = build(client, riley)
    item = b["items"][0]
    e = client.get(f"/api/baskets/{b['id']}/items/{item['id']}/explain", headers=riley).json()
    assert e["available"]
    assert e["evidence"]["price"]["price"] == item["pack_price"]
    assert e["evidence"]["price"]["retailer"] == item["retailer"]["name"]
    assert e["evidence"]["compliance"]["status"] == item["compliance"]


def test_missing_evidence_is_named_not_invented(client, riley):
    b = build(client, riley)
    with SessionLocal() as db:
        db.execute(delete(ComplianceVerdict).where(ComplianceVerdict.basket_id == b["id"]))
        db.commit()
    e = client.get(f"/api/baskets/{b['id']}/explain", headers=riley).json()
    assert e["available"]
    assert e["evidence"]["missing"] == ["verdict"]
    assert "No record of the safety verdict" in e["text"]
    assert "safety check was" not in e["text"]


def test_no_audit_trail_means_no_explanation(client, riley):
    b = build(client, riley)
    with SessionLocal() as db:
        db.execute(delete(AuditRecord).where(AuditRecord.basket_id == b["id"]))
        db.commit()
    e = client.get(f"/api/baskets/{b['id']}/explain", headers=riley).json()
    assert e["available"] is False
    assert e["text"] == "Reasoning unavailable for this recommendation."
    assert "audit_trail" in e["evidence"]["missing"]


def test_explanations_are_private_to_the_shopper_and_founder(client, alex, riley, sam, maya):
    b = build(client, riley)
    assert client.get(f"/api/baskets/{b['id']}/explain").status_code == 401
    assert client.get(f"/api/baskets/{b['id']}/explain", headers=alex).status_code == 404
    assert client.get(f"/api/baskets/{b['id']}/explain", headers=sam).status_code == 404
    assert client.get(f"/api/baskets/{b['id']}/explain", headers=maya).status_code == 200


def test_audit_log_permissions(client, alex, riley, sam, maya):
    b = build(client, riley)
    founder_view = client.get(f"/api/audit?basket_id={b['id']}", headers=maya).json()
    assert founder_view and all("payload" in r for r in founder_view)

    own = client.get(f"/api/audit?basket_id={b['id']}", headers=riley).json()
    assert own and all("payload" not in r for r in own)  # no raw prompts for shoppers
    assert client.get(f"/api/audit?basket_id={b['id']}", headers=alex).json() == []  # not Alex's session
    assert client.get("/api/audit", headers=sam).json() == []  # reviewers have no shopping sessions

    assert client.get("/api/audit/stats", headers=riley).status_code == 403
    assert client.get("/api/audit/stats", headers=sam).status_code == 403
    stats = client.get("/api/audit/stats", headers=maya).json()
    assert stats["per_agent"]["AI Nutrition & Compliance"] > 0


def test_oversight_is_independent_of_shopper_decisions(client, riley, maya):
    b = build(client, riley)
    before = client.get(f"/api/baskets/{b['id']}", headers=riley).json()
    client.get(f"/api/baskets/{b['id']}/explain", headers=riley)
    after = client.get(f"/api/baskets/{b['id']}", headers=riley).json()
    # Explaining reads the record; it never changes the recommendation.
    assert (after["total"], after["status"], [i["id"] for i in after["items"]]) == (
        before["total"], before["status"], [i["id"] for i in before["items"]]
    )
    # The audit log has no write path for anyone, founder included.
    for method in ("post", "put", "delete"):
        assert getattr(client, method)("/api/audit", headers=maya).status_code == 405
    # Every recorded decision names the agent and the model (or "deterministic") behind it.
    for r in client.get(f"/api/audit?basket_id={b['id']}", headers=maya).json():
        assert r["agent"] and r["model_version"]
