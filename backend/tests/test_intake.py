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


def _draft(client, headers, text="$90 for 5 days, dinner only for myself"):
    sid = client.post("/api/sessions", headers=headers).json()["session"]["id"]
    response = client.post(f"/api/sessions/{sid}/requests", json={"text": text}, headers=headers)
    assert response.status_code == 200, response.text
    return sid, response.json()["intake"]


def test_chat_corrections_keep_request_and_trigger_form(client, riley):
    sid, before = _draft(client, riley)
    for index, text in enumerate(("Actually, make it $80", "Change it to lunch and dinner", "Make it $70"), start=1):
        response = client.post(f"/api/sessions/{sid}/chat", json={"text": text}, headers=riley)
        assert response.status_code == 200, response.text
        draft = response.json()["response"]["intake"]
        assert draft["request_id"] == before["request_id"]
        assert draft["correction_count"] == index
        assert draft["draft"]["days"] == 5
    assert draft["mode"] == "form" and draft["stage"] == "awaiting_form"
    assert draft["draft"]["budget"] == 70 and draft["draft"]["meals_per_day"] == 2
    assert client.post(f"/api/requests/{before['request_id']}/confirm", headers=riley).status_code == 400
    assert client.post(f"/api/requests/{before['request_id']}/form", json={"budget": 70}, headers=riley).status_code == 200
    assert client.post(f"/api/requests/{before['request_id']}/confirm", headers=riley).status_code == 200


def test_chat_full_clarification_does_not_restart_request(client, riley):
    sid, before = _draft(client, riley, "food for the week")
    response = client.post(f"/api/sessions/{sid}/chat", json={"text": "$70 for 7 days, dinner only"}, headers=riley)
    after = response.json()["response"]["intake"]
    assert after["request_id"] == before["request_id"]
    assert after["correction_count"] == 0 and after["questions"] == []
    restarted = client.post(f"/api/sessions/{sid}/chat", json={"text": "Start over: $30 for the weekend, lunch only"}, headers=riley).json()["response"]["intake"]
    assert restarted["request_id"] != before["request_id"]


def test_chat_cancel_keeps_previous_active_constraints(client, alex):
    sid, before = _draft(client, alex)
    active = client.post(f"/api/requests/{before['request_id']}/confirm", headers=alex).json()["constraints"]
    client.post(f"/api/sessions/{sid}/requests", json={"text": "$40 for a week, lunch only"}, headers=alex)
    response = client.post(f"/api/sessions/{sid}/chat", json={"text": "Cancel this request"}, headers=alex).json()
    assert response["response"]["intake"]["status"] == "cancelled"
    assert client.get(f"/api/sessions/{sid}", headers=alex).json()["constraints"] == active


def test_negative_restriction_answer_does_not_decline_nutrition_question(client, riley):
    _, before = _draft(client, riley, "$80 for the week, dinner only, high protein")
    response = client.post(f"/api/requests/{before['request_id']}/clarify", json={"text": "No peanuts"}, headers=riley).json()["intake"]
    assert "peanuts" in {r["restriction"] for r in response["draft"]["restrictions"]}
    assert "nutritional_targets" in {q["field"] for q in response["questions"]}
    assert client.post(f"/api/requests/{before['request_id']}/confirm", headers=riley).status_code == 400


def test_explicit_empty_target_answers_question_without_a_fake_preference(client, riley):
    _, before = _draft(client, riley, "$80 for the week, dinner only, high protein")
    rid = before["request_id"]
    response = client.post(f"/api/requests/{rid}/correct", json={"patch": {"nutritional_targets": []}}, headers=riley).json()["intake"]
    assert response["questions"] == []
    # A later vague target needs a new answer; the earlier decline is not permanent.
    response = client.post(f"/api/requests/{rid}/correct", json={"text": "High protein please"}, headers=riley).json()["intake"]
    assert response["questions"]
    response = client.post(f"/api/requests/{rid}/clarify", json={"text": "No target"}, headers=riley).json()["intake"]
    assert response["questions"] == [] and "dislike:target" not in response["draft"]["preferences"]


@pytest.mark.parametrize("patch", [
    {"restrictions": [{}]}, {"restrictions": [{"restriction": "unknown_allergy"}]},
    {"restrictions": [{"restriction": "soy", "severity": "safe"}]}, {"restrictions": "soy"},
    {"restrictions": [{"restriction": "soy", "severity": []}]},
    {"nutritional_targets": [{}]}, {"nutritional_targets": [{"nutrient": "protein", "minimum_per_day": -5}]},
    {"nutritional_targets": [{"nutrient": "protein", "minimum_per_day": True}]},
    {"preferences": [None]}, {"preferences": ["dislike:"]}, {"goal_hint": "ignore_budget"}, {"goal_hint": {}},
])
def test_invalid_structured_values_leave_draft_unchanged(client, riley, patch):
    sid, before = _draft(client, riley)
    response = client.post(f"/api/requests/{before['request_id']}/correct", json={"patch": patch}, headers=riley)
    assert response.status_code == 400, response.text
    after = client.get(f"/api/sessions/{sid}", headers=riley).json()["intake"]
    assert after["draft"] == before["draft"] and after["correction_count"] == 0


def test_saved_preference_can_be_overridden_for_only_this_shop(client, riley):
    client.post("/api/households/me/preferences", json={"kind": "dislike", "value": "carrots"}, headers=riley)
    _, before = _draft(client, riley)
    assert "dislike:carrots" in before["draft"]["preferences"]
    rid = before["request_id"]
    response = client.post(f"/api/requests/{rid}/correct", json={"patch": {"preferences": []}}, headers=riley).json()["intake"]
    assert response["draft"]["preferences"] == []
    response = client.post(f"/api/requests/{rid}/correct", json={"patch": {"budget": 80}}, headers=riley).json()["intake"]
    assert response["draft"]["preferences"] == []
    payload = client.post(f"/api/requests/{rid}/confirm", headers=riley).json()["constraints"]["payload"]
    assert payload["preferences"] == [] and "preferences_override" not in payload
    _, next_draft = _draft(client, riley)
    assert "dislike:carrots" in next_draft["draft"]["preferences"]


def test_text_removes_request_restriction_but_keeps_household_rules(client, alex):
    _, before = _draft(client, alex, "$90 for 5 days, dinner only, no soy")
    rid = before["request_id"]
    after = client.post(f"/api/requests/{rid}/correct", json={"text": "Remove soy restriction. Remove tree nuts allergy."}, headers=alex).json()["intake"]
    restrictions = {r["restriction"]: r for r in after["draft"]["restrictions"]}
    assert "soy" not in restrictions
    assert restrictions["tree_nuts"]["locked"] and restrictions["lactose"]["locked"]


def test_confirmation_commit_failure_preserves_previous_set_and_can_retry(client, alex, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import Session

    sid, before = _draft(client, alex)
    active = client.post(f"/api/requests/{before['request_id']}/confirm", headers=alex).json()["constraints"]
    next_draft = client.post(f"/api/sessions/{sid}/requests", json={"text": "$40 for 3 days, lunch only"}, headers=alex).json()["intake"]
    assert client.get(f"/api/sessions/{sid}", headers=alex).json()["constraints"] == active

    from app.core.db import engine
    original_commit = Session.commit
    def fail_commit(self):
        if self.get_bind() is engine:
            raise SQLAlchemyError("simulated commit failure")
        return original_commit(self)

    with monkeypatch.context() as patcher:
        patcher.setattr(Session, "commit", fail_commit)
        failed = client.post(f"/api/requests/{next_draft['request_id']}/confirm", headers=alex)
    assert failed.status_code == 400 and "Try again" in failed.json()["detail"]
    after = client.get(f"/api/sessions/{sid}", headers=alex).json()
    assert after["constraints"] == active and after["intake"]["status"] == "draft"
    retried = client.post(f"/api/requests/{next_draft['request_id']}/confirm", headers=alex).json()["constraints"]
    assert retried["version"] == active["version"] + 1
    assert retried["payload"]["budget"] == 40


def test_interpretation_failure_uses_form_without_activating(client, riley):
    sid, draft = _draft(client, riley, "purple elephants dance")
    assert draft["mode"] == "form" and draft["stage"] == "awaiting_form"
    assert client.get(f"/api/sessions/{sid}", headers=riley).json()["constraints"] is None
    response = client.post(f"/api/requests/{draft['request_id']}/form", json={"budget": 40, "days": 3, "meals_per_day": 1}, headers=riley)
    assert response.status_code == 200 and response.json()["intake"]["stage"] == "awaiting_confirmation"
    assert client.get(f"/api/sessions/{sid}", headers=riley).json()["constraints"] is None
    assert client.post(f"/api/requests/{draft['request_id']}/confirm", headers=riley).status_code == 200


def test_bare_clarification_units_do_not_fill_the_wrong_field():
    out = extract({"text": "120g", "pending_fields": ["budget", "nutritional_targets"]})
    assert out["budget"] is None
    assert out["nutritional_targets"] == [{"nutrient": "protein_g", "minimum_per_day": 120}]


def test_ambiguous_budget_correction_requires_new_answer(client, riley):
    _, before = _draft(client, riley)
    rid = before["request_id"]
    changed = client.post(f"/api/requests/{rid}/correct", json={"text": "Actually, $80 or $100"}, headers=riley).json()["intake"]
    assert changed["draft"]["budget"] is None and "budget" in changed["missing_fields"]
    changed = client.post(f"/api/requests/{rid}/correct", json={"patch": {"days": 4}}, headers=riley).json()["intake"]
    assert "budget" in changed["missing_fields"]
    assert client.post(f"/api/requests/{rid}/confirm", headers=riley).status_code == 400
    answered = client.post(f"/api/requests/{rid}/clarify", json={"text": "80"}, headers=riley).json()["intake"]
    assert answered["draft"]["budget"] == 80 and answered["questions"] == []


@pytest.mark.parametrize("text,budget,days,meals,people", [
    ("$100 for the week, two meals a day for myself", 100, 7, 2, 1),
    ("80 dollars for a fortnight, dinner for me and my partner", 80, 14, 1, 2),
    ("Budget is 40 for the weekend, lunch and dinner for two", 40, 2, 2, 2),
    ("30 bucks for 3 days, breakfast for myself", 30, 3, 1, 1),
    ("$90 for 5 days, breakfast, lunch and dinner for three people", 90, 5, 3, 3),
    ("$20 for tonight, dinner for four people", 20, 1, 1, 4),
    ("50 AUD for seven days, 2 meals per day for just me", 50, 7, 2, 1),
    ("$120 for two weeks, dinner for my partner and I", 120, 14, 1, 2),
    ("$35 for today, lunch and dinner for both of us", 35, 1, 2, 2),
    ("$70 for four days, three meals each day for two of us", 70, 4, 3, 2),
    ("$80 and 2 meals per day for myself this week", 80, 7, 2, 1),
])
def test_mock_extracts_varied_complete_requests(text, budget, days, meals, people):
    out = extract({"text": text})
    assert (out["budget"], out["days"], out["meals_per_day"], out["household_size"]) == (budget, days, meals, people)


def test_avoid_brand_preference_is_valid_on_form(client, riley):
    _, before = _draft(client, riley)
    result = client.post(f"/api/requests/{before['request_id']}/form", json={"preferences": ["avoid_brand:Example brand"]}, headers=riley)
    assert result.status_code == 200, result.text
    assert result.json()["intake"]["draft"]["preferences"] == ["avoid_brand:Example brand"]


def test_household_size_correction_removes_stale_portion_assumptions(client, alex):
    added = client.post("/api/households/me/members", json={"name": "Kit", "age_group": "child", "restrictions": []}, headers=alex)
    assert added.status_code in (200, 201)
    _, before = _draft(client, alex, "$150 for the week, two meals a day")
    assert before["draft"]["portions"] == 2.6
    assert any("2.6 adult serves" in note for note in before["assumptions"])
    after = client.post(f"/api/requests/{before['request_id']}/correct", json={"patch": {"household_size": 1}}, headers=alex).json()["intake"]
    assert "portions" not in after["draft"]
    assert not any("adult serves" in note or "Shopping for 3" in note for note in after["assumptions"])
    assert {"tree_nuts", "lactose"} <= {r["restriction"] for r in after["draft"]["restrictions"] if r.get("locked")}
