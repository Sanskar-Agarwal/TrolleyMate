"""UC-02..UC-09 end to end through the API, plus the dietitian review path."""

import pytest


def confirmed_session(client, headers, text):
    s = client.post("/api/sessions", headers=headers).json()["session"]
    rid = client.post(f"/api/sessions/{s['id']}/requests", json={"text": text}, headers=headers).json()["intake"]["request_id"]
    r = client.post(f"/api/requests/{rid}/confirm", headers=headers)
    assert r.status_code == 200, r.text
    return s["id"]


@pytest.mark.parametrize("goal", ["lowest_cost", "best_nutrition", "least_waste", "fastest_cook", "balanced"])
def test_every_goal_builds_a_basket_within_budget(client, riley, goal):
    sid = confirmed_session(client, riley, "$70 for the week, two meals a day for myself")
    r = client.post(f"/api/sessions/{sid}/basket", json={"goal": goal}, headers=riley).json()
    assert r["status"] == "ok"
    b = r["basket"]
    assert b["total"] <= 70
    assert b["items"]
    assert b["nutrition"]["adequate"]
    assert any(t["agent"] == "nutrition_compliance" for t in r["trace"])


def test_allergens_never_enter_the_basket(client, alex):
    sid = confirmed_session(client, alex, "$120 for the week, two meals a day")
    b = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=alex).json()["basket"]
    names = {i["product"]["name"] for i in b["items"]}
    for unsafe in ("Almond Milk 1L", "Basil Pesto 190g", "Full Cream Milk 2L", "Honey Muesli Bars 6pk"):
        assert unsafe not in names
    excluded = {e["product"] for e in b["excluded"]}
    assert "Full Cream Milk 2L" in excluded  # lactose


def test_infeasible_budget_offers_tradeoffs_then_rebuilds(client, riley):
    sid = confirmed_session(client, riley, "$8 for the week, three meals a day for myself")
    r = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=riley).json()
    assert r["status"] == "infeasible"
    options = r["negotiation"]["options"]
    budget_opt = next(o for o in options if o["id"] == "increase_budget")
    r = client.post(f"/api/sessions/{sid}/negotiate", json={"option_id": "increase_budget", "budget": budget_opt["budget"]}, headers=riley).json()
    assert r["status"] == "ok"
    assert r["basket"]["total"] <= budget_opt["budget"] + 0.01


def test_uncertain_item_is_withheld_and_dietitian_can_release_it(client, alex, sam):
    sid = confirmed_session(client, alex, "$100 for the week, two meals a day")
    b = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=alex).json()["basket"]
    withheld = [i for i in b["items"] if i["withheld"]]
    if not withheld:
        pytest.skip("Solver did not pick an uncertain product this run")
    assert b["status"] == "pending_review"
    queue = client.get("/api/escalations", headers=sam).json()["cases"]
    case = next(c for c in queue if c["basket_id"] == b["id"])
    cid = case["id"]
    assert client.post(f"/api/escalations/{cid}/begin", headers=sam).status_code == 200
    r = client.post(f"/api/escalations/{cid}/request-info", json={"question": "Do we have the ingredient list?"}, headers=sam).json()
    assert r["case"]["thread"][-1]["from"] == "agent"
    r = client.post(f"/api/escalations/{cid}/resolve", json={"decision": "passed", "note": "Manufacturer confirmed nut and dairy free."}, headers=sam)
    assert r.status_code == 200
    b2 = client.get(f"/api/baskets/{b['id']}", headers=alex).json()
    assert not any(i["withheld"] for i in b2["items"])
    assert b2["status"] == "verified"


def test_shopper_cannot_open_review_queue(client, alex):
    assert client.get("/api/escalations", headers=alex).status_code == 403


def test_substitution_edit_mealplan_compare_timing(client, riley):
    sid = confirmed_session(client, riley, "$80 for the week, two meals a day for myself")
    b = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=riley).json()["basket"]

    item = b["items"][0]
    r = client.post(f"/api/baskets/{b['id']}/items/{item['id']}/substitute", json={"reason": "user_requested"}, headers=riley).json()
    sub = r["substitution"]
    assert sub["status"] in ("pending", "discarded")
    if sub["status"] == "pending":
        assert sub["trade_off"]
        r = client.post(f"/api/substitutions/{sub['id']}/reject", headers=riley).json()
        assert r["substitution"]["status"] == "rejected"

    plan = client.post(f"/api/baskets/{b['id']}/meal-plan", headers=riley).json()["meal_plan"]
    assert plan["planned"] > 0 and plan["days"]

    cmp = client.get(f"/api/baskets/{b['id']}/comparison", headers=riley).json()
    assert len(cmp["options"]) == 4 and cmp["insight"]

    timing = client.get(f"/api/baskets/{b['id']}/buy-timing", headers=riley).json()["advice"]
    assert len(timing) == len([i for i in b["items"] if not i["withheld"]])

    r = client.post(f"/api/baskets/{b['id']}/edit", json={"text": "add some chicken"}, headers=riley).json()
    assert r["status"] in ("ok", "conflict")
    if r["status"] == "ok":
        assert any("chicken" in i["product"]["name"].lower() for i in r["basket"]["items"])


def test_chat_routes_to_the_right_workflow(client, riley):
    s = client.post("/api/sessions", headers=riley).json()["session"]
    r = client.post(f"/api/sessions/{s['id']}/chat", json={"text": "$60 for 5 days, dinner only"}, headers=riley).json()
    assert r["response"]["kind"] == "intake"
    assert any(t["action"] == "route_message" for t in r["trace"])


def test_explanations_and_audit(client, riley, maya):
    sid = confirmed_session(client, riley, "$70 for the week, two meals a day for myself")
    b = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=riley).json()["basket"]
    exp = client.get(f"/api/baskets/{b['id']}/explain", headers=riley).json()
    assert exp["available"] and exp["text"]
    item_exp = client.get(f"/api/baskets/{b['id']}/items/{b['items'][0]['id']}/explain", headers=riley).json()
    assert item_exp["available"]
    full = client.get(f"/api/audit?basket_id={b['id']}", headers=maya).json()
    assert full and "payload" in full[0]
    shopper_view = client.get(f"/api/audit?basket_id={b['id']}", headers=riley).json()
    assert shopper_view and "payload" not in shopper_view[0]
