"""UC-01 — intake and constraint extraction."""

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
