"""KAN-5 — the complete shopper journey on the release candidate, following docs/DEMO_SCRIPT.md.

One shopper goes profile → request → clarification → correction → confirmation → basket →
human review → explanation → edit → substitution → comparison → buy timing → acceptance →
meal plan, then a second infeasible shop is negotiated, and the founder audits it all.
Each step names the Stage 1 requirement (1.2.x) it evidences; see docs/JOURNEY_VERIFICATION.md.
"""

from tests.test_basket_flow import _force_escalation_scenario

DEMO_REQUEST = "I have $100 for this week, two meals a day for us two. High protein please."


def test_complete_shopper_journey(client, alex, sam, maya):
    # 1 — profile drives the shop (1.2.13): both members' mandatory restrictions.
    household = client.get("/api/households/me", headers=alex).json()
    assert {r["restriction"] for r in household["mandatory_restrictions"]} == {"lactose", "tree_nuts"}

    # 2 — perception (1.2.1): extract constraints, merge the household, ask about "high protein".
    sid = client.post("/api/sessions", headers=alex).json()["session"]["id"]
    intake = client.post(f"/api/sessions/{sid}/requests", json={"text": DEMO_REQUEST}, headers=alex).json()["intake"]
    rid = intake["request_id"]
    assert intake["draft"]["budget"] == 100 and intake["draft"]["household_size"] == 2
    assert all(r.get("locked") for r in intake["draft"]["restrictions"])
    assert "nutritional_targets" in {q["field"] for q in intake["questions"]}

    # 3 — clarification is not a correction; a correction is counted; confirm activates (1.2.1).
    intake = client.post(f"/api/requests/{rid}/clarify", json={"text": "120g"}, headers=alex).json()["intake"]
    assert intake["correction_count"] == 0 and intake["questions"] == []
    intake = client.post(f"/api/requests/{rid}/correct", json={"patch": {"budget": 90}}, headers=alex).json()["intake"]
    assert intake["correction_count"] == 1 and intake["draft"]["budget"] == 90
    assert client.post(f"/api/requests/{rid}/confirm", headers=alex).status_code == 200

    # 4 — basket within hard constraints (1.2.2, 1.2.7, 1.2.10): priced at all four stores, allergens out.
    built = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=alex).json()
    assert built["status"] == "ok"
    basket = built["basket"]
    assert basket["total"] <= 90
    agents = {t["agent"] for t in built["trace"]}
    assert {"personal_shopper", "market_analyst", "nutrition_compliance", "technical_manager"} <= agents
    assert any("4 retailers" in t["decision"] for t in built["trace"] if t["action"] == "price_candidates")
    names = {i["product"]["name"] for i in basket["items"]}
    assert not names & {"Full Cream Milk 2L", "Almond Milk 1L", "Greek Yoghurt 1kg"}
    assert {"Full Cream Milk 2L", "Almond Milk 1L"} <= {e["product"] for e in basket["excluded"]}

    # 5 — uncertain item is withheld and escalated, not shown as safe (1.2.10, 1.2.15).
    if not any(i["withheld"] for i in basket["items"]):
        _force_escalation_scenario(basket["id"])
    basket = client.get(f"/api/baskets/{basket['id']}", headers=alex).json()
    held = [i for i in basket["items"] if i["withheld"]]
    assert held and basket["status"] == "pending_review"
    assert client.post(f"/api/baskets/{basket['id']}/accept", headers=alex).status_code == 400

    # 6 — explanations grounded in recorded facts (1.2.14).
    explained = client.get(f"/api/baskets/{basket['id']}/explain", headers=alex).json()
    assert explained["available"] and explained["facts"]["total"] == basket["total"]
    first = basket["items"][0]
    assert client.get(f"/api/baskets/{basket['id']}/items/{first['id']}/explain", headers=alex).json()["available"]

    # 7 — the dietitian reviews and releases (1.2.15); shoppers can't open the queue.
    assert client.get("/api/escalations", headers=alex).status_code == 403
    for case in client.get("/api/escalations", headers=sam).json()["cases"]:
        if case["basket_id"] != basket["id"] or case["status"] == "resolved":
            continue
        assert client.post(f"/api/escalations/{case['id']}/begin", headers=sam).status_code == 200
        asked = client.post(f"/api/escalations/{case['id']}/request-info", json={"question": "Any milk solids?"}, headers=sam).json()
        assert asked["case"]["thread"][-1]["from"] == "agent"
        resolved = client.post(f"/api/escalations/{case['id']}/resolve", json={"decision": "passed", "note": "Spec sheet checked."}, headers=sam)
        assert resolved.status_code == 200

    # 8 — the decision is applied: nothing withheld, notices and explanation agree.
    basket = client.get(f"/api/baskets/{basket['id']}", headers=alex).json()
    assert basket["status"] == "verified" and not any(i["withheld"] for i in basket["items"])
    assert not any(" is held " in n for n in basket["notifications"])
    assert client.get(f"/api/baskets/{basket['id']}/explain", headers=alex).json()["facts"]["withheld"] == []

    # 9 — conversational edit re-optimises with mandatory rules intact (1.2.9).
    protein = next(i for i in basket["items"] if i["product"]["category"] == "protein"
                   and i["product"]["tags"] and "chicken" not in i["product"]["tags"])
    edited = client.post(f"/api/baskets/{basket['id']}/edit",
                         json={"text": f"Replace the {protein['product']['tags'][0]} with chicken"}, headers=alex).json()
    assert edited["status"] == "ok", edited.get("message")
    basket = edited["basket"]
    assert protein["product"]["name"] not in {i["product"]["name"] for i in basket["items"]}
    assert basket["total"] <= 90

    # 10 — substitution with a stated trade-off, applied only on acceptance (1.2.5).
    item = next(i for i in basket["items"] if i["product"]["category"] == "protein")
    sub = client.post(f"/api/baskets/{basket['id']}/items/{item['id']}/substitute", json={}, headers=alex).json()["substitution"]
    if sub["status"] == "pending":
        assert sub["trade_off"]
        client.post(f"/api/substitutions/{sub['id']}/accept", headers=alex)
        basket = client.get(f"/api/baskets/{basket['id']}", headers=alex).json()
        assert sub["replacement"]["name"] in {i["product"]["name"] for i in basket["items"]}

    # 11 — comparison across four stores with the cheapest source per item (1.2.8); buy timing (1.2.6).
    cmp = client.get(f"/api/baskets/{basket['id']}/comparison", headers=alex).json()
    assert len(cmp["retailers"]) == 4 and cmp["complete"]
    split = next(o for o in cmp["options"] if o["is_split"])
    assert round(sum(s["subtotal"] for s in cmp["split_plan"]), 2) == split["total"]
    assert all(split["total"] <= o["total"] for o in cmp["options"] if o["complete"])
    timing = client.get(f"/api/baskets/{basket['id']}/buy-timing", headers=alex).json()["advice"]
    assert {a["action"] for a in timing} <= {"wait", "buy_now", "none", "skip"}

    # 12 — accept, then plan meals only from the basket (1.2.3).
    accepted = client.post(f"/api/baskets/{basket['id']}/accept", headers=alex)
    assert accepted.status_code == 200, accepted.text
    plan = client.post(f"/api/baskets/{basket['id']}/meal-plan", headers=alex).json()["meal_plan"]
    bought = {i["product"]["name"] for i in basket["items"]}
    assert plan["planned"] > 0
    assert all(set(m.get("uses", [])) <= bought for d in plan["days"] for m in d["meals"])  # gaps are reported, not filled

    # 13 — an infeasible shop is negotiated, never by relaxing a restriction (1.2.4).
    sid2 = client.post("/api/sessions", headers=alex).json()["session"]["id"]
    rid2 = client.post(f"/api/sessions/{sid2}/requests", json={"text": "$30 for the week, three meals a day for two of us"},
                       headers=alex).json()["intake"]["request_id"]
    assert client.post(f"/api/requests/{rid2}/confirm", headers=alex).status_code == 200
    r = client.post(f"/api/sessions/{sid2}/basket", json={"goal": "balanced"}, headers=alex).json()
    assert r["status"] == "infeasible"
    option = next(o for o in r["negotiation"]["options"] if o["id"] == "increase_budget")
    r = client.post(f"/api/sessions/{sid2}/negotiate", json={"option_id": option["id"], "budget": option["budget"]}, headers=alex).json()
    assert r["status"] == "ok" and r["basket"]["total"] <= option["budget"] + 0.01

    # 14 — independent oversight: the founder sees every agent's decisions with model attribution.
    audit = client.get(f"/api/audit?session_id={sid}", headers=maya).json()
    assert {"AI Personal Shopper", "AI Market Analyst", "AI Nutrition & Compliance", "AI Technical Manager"} <= {a["agent"] for a in audit}
    assert any(a["agent"].startswith("Dietitian") for a in client.get("/api/audit", headers=maya).json())
    assert all("model_version" in a for a in audit)
