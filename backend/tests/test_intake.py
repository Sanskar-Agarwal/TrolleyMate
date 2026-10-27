"""UC-01 — intake and constraint extraction."""

import pytest

from app.llm.tasks.extract_constraints import mock as extract


def test_extracts_the_spec_example():
    out = extract({"text": "I have $100 for this week, I am lactose intolerant, and I cook two meals a day for myself"})
    assert out["budget"] == 100
    assert out["days"] == 7
    assert out["meals_per_day"] == 2
    assert out["household_size"] == 1
    assert {"restriction": "lactose", "severity": "moderate"} in out["restrictions"]


def test_vague_protein_goal_is_asked_not_assumed():
    out = extract({"text": "$80 for the week, dinners for two, high protein"})
    assert out["nutritional_targets"] == []
    assert any(a["field"] == "nutritional_targets" for a in out["ambiguities"])


def test_nut_allergy_means_tree_nuts_and_peanuts():
    out = extract({"text": "Breakfast for two; nut allergy; $25"})
    ids = {r["restriction"] for r in out["restrictions"]}
    assert {"tree_nuts", "peanuts"} <= ids


def test_household_restrictions_are_merged_and_locked(client, alex):
    s = client.post("/api/sessions", headers=alex).json()["session"]
    r = client.post(f"/api/sessions/{s['id']}/requests", json={"text": "$90 for 5 days, dinner only"}, headers=alex)
    draft = r.json()["intake"]["draft"]
    locked = {x["restriction"] for x in draft["restrictions"] if x.get("locked")}
    assert {"lactose", "tree_nuts"} <= locked
    assert draft["household_size"] == 2  # from the profile, recorded as an assumption
    assert r.json()["intake"]["assumptions"]


def test_missing_budget_triggers_a_question_then_clarifies(client, riley):
    s = client.post("/api/sessions", headers=riley).json()["session"]
    r = client.post(f"/api/sessions/{s['id']}/requests", json={"text": "two meals a day for this week"}, headers=riley).json()
    assert [q["field"] for q in r["intake"]["questions"]] == ["budget"]
    rid = r["intake"]["request_id"]
    r = client.post(f"/api/requests/{rid}/clarify", json={"text": "60"}, headers=riley).json()
    assert r["intake"]["draft"]["budget"] == 60
    assert r["intake"]["questions"] == []
    assert r["intake"]["correction_count"] == 0  # clarifications don't count


def test_third_correction_switches_to_form(client, riley):
    s = client.post("/api/sessions", headers=riley).json()["session"]
    rid = client.post(f"/api/sessions/{s['id']}/requests", json={"text": "$50 for 3 days, dinner only"}, headers=riley).json()["intake"]["request_id"]
    for budget in (55, 60, 65):
        r = client.post(f"/api/requests/{rid}/correct", json={"patch": {"budget": budget}}, headers=riley).json()
    assert r["intake"]["mode"] == "form"
    assert r["intake"]["correction_count"] == 3


def test_cannot_remove_household_allergy(client, alex):
    s = client.post("/api/sessions", headers=alex).json()["session"]
    rid = client.post(f"/api/sessions/{s['id']}/requests", json={"text": "$90 for 5 days, dinner only"}, headers=alex).json()["intake"]["request_id"]
    r = client.post(f"/api/requests/{rid}/correct", json={"patch": {"restrictions": []}}, headers=alex).json()
    assert "tree_nuts" in {x["restriction"] for x in r["intake"]["draft"]["restrictions"]}


def test_confirm_requires_complete_constraints(client, riley):
    s = client.post("/api/sessions", headers=riley).json()["session"]
    rid = client.post(f"/api/sessions/{s['id']}/requests", json={"text": "food for the week"}, headers=riley).json()["intake"]["request_id"]
    r = client.post(f"/api/requests/{rid}/confirm", headers=riley)
    assert r.status_code == 400


def test_unanswered_optional_question_blocks_confirmation(client, riley):
    sid = client.post("/api/sessions", headers=riley).json()["session"]["id"]
    draft = client.post(f"/api/sessions/{sid}/requests", json={"text": "$80 for the week, dinners for two, high protein"}, headers=riley).json()["intake"]
    assert draft["missing_fields"] == []
    assert draft["questions"]
    rid = draft["request_id"]
    assert client.post(f"/api/requests/{rid}/confirm", headers=riley).status_code == 400
    clarified = client.post(f"/api/requests/{rid}/clarify", json={"text": "No target"}, headers=riley)
    assert clarified.json()["intake"]["questions"] == []
    assert client.post(f"/api/requests/{rid}/confirm", headers=riley).status_code == 200


@pytest.mark.parametrize("correction", [{"patch": {"budget": 90}}, {"text": "make it $90"}])
def test_unrelated_correction_keeps_unanswered_question(client, riley, correction):
    sid = client.post("/api/sessions", headers=riley).json()["session"]["id"]
    draft = client.post(f"/api/sessions/{sid}/requests", json={"text": "$80 for the week, dinners for two, high protein"}, headers=riley).json()["intake"]
    asked = {q["field"] for q in draft["questions"]}
    assert "nutritional_targets" in asked
    after = client.post(f"/api/requests/{draft['request_id']}/correct", json=correction, headers=riley).json()["intake"]
    assert after["draft"]["budget"] == 90
    assert "nutritional_targets" in {q["field"] for q in after["questions"]}
    assert client.post(f"/api/requests/{draft['request_id']}/confirm", headers=riley).status_code == 400


@pytest.mark.parametrize("patch", [
    {"budget": -10}, {"budget": "cheap"}, {"budget": True},
    {"household_size": 1.5}, {"household_size": 21}, {"days": 0},
    {"days": 32}, {"meals_per_day": 6},
])
def test_invalid_correction_does_not_change_draft(client, riley, patch):
    sid = client.post("/api/sessions", headers=riley).json()["session"]["id"]
    before = client.post(f"/api/sessions/{sid}/requests", json={"text": "$90 for 5 days, dinner only"}, headers=riley).json()["intake"]
    response = client.post(f"/api/requests/{before['request_id']}/correct", json={"patch": patch}, headers=riley)
    assert response.status_code == 400
    after = client.get(f"/api/sessions/{sid}", headers=riley).json()["intake"]
    assert after["draft"] == before["draft"]
    assert after["correction_count"] == before["correction_count"]


def test_form_and_cancel_preserve_confirmed_constraints(client, alex):
    sid = client.post("/api/sessions", headers=alex).json()["session"]["id"]
    rid = client.post(f"/api/sessions/{sid}/requests", json={"text": "$90 for 5 days, dinner only"}, headers=alex).json()["intake"]["request_id"]
    active = client.post(f"/api/requests/{rid}/confirm", headers=alex).json()["constraints"]
    next_id = client.post(f"/api/sessions/{sid}/requests", json={"text": "food for the week"}, headers=alex).json()["intake"]["request_id"]
    form = client.post(f"/api/requests/{next_id}/form", json={"budget": 60, "days": 3, "meals_per_day": 2, "household_size": 2, "restrictions": []}, headers=alex).json()["intake"]
    assert form["mode"] == "form"
    assert {"tree_nuts", "lactose"} <= {r["restriction"] for r in form["draft"]["restrictions"] if r.get("locked")}
    assert client.post(f"/api/requests/{next_id}/cancel", headers=alex).status_code == 200
    current = client.get(f"/api/sessions/{sid}", headers=alex).json()["constraints"]
    assert current == active
