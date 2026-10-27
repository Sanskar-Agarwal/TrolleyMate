"""Chat: edit diffs (1.2.9), "why is X cheaper at Y?" (1.2.8) and household edits (1.2.13)."""

from tests.test_basket_flow import confirmed_session


def _chat(client, headers, sid, text):
    r = client.post(f"/api/sessions/{sid}/chat", json={"text": text}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["response"]


def _with_basket(client, headers, text="$80 for the week, two meals a day for myself"):
    sid = confirmed_session(client, headers, text)
    b = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=headers).json()["basket"]
    return sid, b


def test_chat_edit_reports_what_changed(client, riley):
    sid, b = _with_basket(client, riley)
    r = _chat(client, riley, sid, "add olive oil")
    assert r["kind"] == "edit" and r["edit"]["status"] == "ok"
    diff = r["edit"]["diff"]
    assert {"product": "Olive Oil 500ml", "quantity": 1} in diff["added"]
    assert diff["total_before"] == b["total"] and diff["total_after"] > diff["total_before"]
    assert "Added Olive Oil 500ml ×1" in r["reply"] and f"${b['total']:.2f} →" in r["reply"]


def test_why_is_it_cheaper_answers_from_recorded_quotes(client, riley):
    sid, b = _with_basket(client, riley)
    item = b["items"][0]["product"]["name"]
    word = item.split()[0].lower()
    r = _chat(client, riley, sid, f"why is the {word} cheaper at GreenGrocer Express?")
    assert r["kind"] == "price"
    assert r["reply"].startswith(item) and "$" in r["reply"]


def test_household_restriction_can_be_added_from_chat(client, alex):
    sid, _ = _with_basket(client, alex, "$100 for the week, two meals a day")
    r = _chat(client, alex, sid, "Jamie is now vegetarian")
    assert r["kind"] == "household" and "Jamie now avoids vegetarian" in r["reply"]
    assert "start a new shop" in r["reply"]
    jamie = next(m for m in client.get("/api/households/me", headers=alex).json()["members"] if m["name"] == "Jamie")
    assert {x["restriction"] for x in jamie["restrictions"]} == {"tree_nuts", "vegetarian"}


def test_member_can_be_added_from_chat_but_not_removed(client, alex):
    sid = client.post("/api/sessions", headers=alex).json()["session"]["id"]
    r = _chat(client, alex, sid, "add Kit, a child with a peanut allergy")
    assert "added Kit (child)" in r["reply"]
    kit = next(m for m in client.get("/api/households/me", headers=alex).json()["members"] if m["name"] == "Kit")
    assert kit["age_group"] == "child" and [x["restriction"] for x in kit["restrictions"]] == ["peanuts"]
    r = _chat(client, alex, sid, "remove Jamie's allergy for Jamie")
    assert "Household page" in r["reply"]
    assert len(client.get("/api/households/me", headers=alex).json()["members"]) == 3
