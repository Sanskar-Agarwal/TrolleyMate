"""KAN-22: taste & preference memory (1.2.12) — preferences are stored, shown, changed and forgotten;
they apply to later sessions with mandatory restrictions first; only the owner can reach them, and
forgetting one deletes it."""

import re

import pytest
from sqlalchemy import select

from app.agents.context import AgentContext
from app.core.db import SessionLocal
from app.domain import AuditRecord, Basket, Household, Preference, Product, User
from app.llm import get_llm
from app.services.catalogue import disliked_by, optimisable_products

PREFS = "/api/households/me/preferences"
WEEK = "$70 for the week, two meals a day for myself"
ALEX_WEEK = "$120 for the week, two meals a day"


def remember(client, headers, kind: str, value: str):
    return client.post(PREFS, json={"kind": kind, "value": value}, headers=headers)


def change(client, headers, pref_id: int, kind: str, value: str):
    return client.put(f"{PREFS}/{pref_id}", json={"kind": kind, "value": value}, headers=headers)


def forget(client, headers, pref_id: int):
    return client.delete(f"{PREFS}/{pref_id}", headers=headers)


def shown(client, headers) -> dict[str, dict]:
    """The stored preferences as the shopper sees them, keyed "kind:value"."""
    r = client.get(PREFS, headers=headers)
    assert r.status_code == 200, r.text
    return {f"{p['kind']}:{p['value']}": p for p in r.json()}


def confirmed(client, headers, text: str = WEEK) -> tuple[int, list[str]]:
    """A new shopping session with its request confirmed: its id and the preferences its constraints carry."""
    sid = client.post("/api/sessions", headers=headers).json()["session"]["id"]
    rid = client.post(f"/api/sessions/{sid}/requests", json={"text": text}, headers=headers).json()["intake"]["request_id"]
    r = client.post(f"/api/requests/{rid}/confirm", headers=headers)
    assert r.status_code == 200, r.text
    return sid, r.json()["constraints"]["payload"]["preferences"]


def build(client, headers, sid: int, goal: str = "lowest_cost") -> dict:
    r = client.post(f"/api/sessions/{sid}/basket", json={"goal": goal}, headers=headers).json()
    assert r["status"] == "ok", r
    return r["basket"]


def basket(client, headers, sid: int, goal: str = "lowest_cost") -> set[str]:
    return {i["product"]["name"] for i in build(client, headers, sid, goal)["items"]}


def later_session(client, headers, text: str = WEEK, goal: str = "lowest_cost") -> tuple[int, list[str], set[str]]:
    """A new shopping session: its id, the preferences its confirmed constraints carry, and the basket."""
    sid, carried = confirmed(client, headers, text)
    return sid, carried, basket(client, headers, sid, goal)


def rows(email: str) -> list[Preference]:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        return list(db.scalars(select(Preference).join(Household).where(Household.shopper_id == user.id)))


# --- Stored, shown, changed and forgotten ----------------------------------------------


def test_a_preference_is_stored_and_shown_with_what_it_does(client, riley):
    r = remember(client, riley, "dislike", "  Carrots ")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["household"]["preferences"][0]["id"] is not None  # the new row is flushed before it's returned
    (pref,) = body["preferences"]
    assert pref["value"] == "carrots" and pref["label"] == "Dislike" and pref["effect"] == "avoid"
    assert pref["status"] == "applied" and pref["matches"] == ["Carrots 1kg"] and pref["created_at"]
    assert shown(client, riley) == {"dislike:carrots": pref}
    assert [(p.kind, p.value) for p in rows("riley@trolleymate.demo")] == [("dislike", "carrots")]


@pytest.mark.parametrize("value", ["   ", "\t\n"])
def test_a_blank_preference_is_refused(client, riley, value):
    assert remember(client, riley, "dislike", value).status_code == 422
    assert rows("riley@trolleymate.demo") == []


def test_a_preference_can_be_changed(client, riley):
    pref_id = remember(client, riley, "dislike", "carrots").json()["preferences"][0]["id"]

    r = change(client, riley, pref_id, "dislike", " Onions\t")
    assert r.status_code == 200, r.text
    (pref,) = r.json()["preferences"]
    assert (pref["id"], pref["value"], pref["status"]) == (pref_id, "onions", "applied")
    assert pref["matches"] == ["Brown Onions 1kg"] and pref["updated_at"]

    pref = change(client, riley, pref_id, "brand", "barilla").json()["preferences"][0]
    assert (pref["kind"], pref["effect"], pref["status"], pref["matches"]) == ("brand", "favour", "applied", ["Penne 500g"])
    assert list(shown(client, riley)) == ["brand:barilla"]


def test_changing_a_learned_preference_makes_it_the_shoppers_own(client, riley):
    pref_id = remember(client, riley, "dislike", "carrots").json()["preferences"][0]["id"]
    with SessionLocal() as db:
        db.get(Preference, pref_id).source = "learned"
        db.commit()
    assert change(client, riley, pref_id, "dislike", "carrot").json()["preferences"][0]["source"] == "user"


def test_a_preference_cannot_duplicate_or_contradict_another(client, riley):
    carrots = remember(client, riley, "dislike", "carrots").json()["preferences"][0]["id"]
    onions = remember(client, riley, "dislike", "onions").json()["preferences"][-1]["id"]

    assert remember(client, riley, "dislike", "Carrots").status_code == 200  # saying it again is harmless
    contradiction = remember(client, riley, "like", "carrots")
    assert contradiction.status_code == 409 and "dislike: carrots" in contradiction.json()["detail"]
    assert change(client, riley, onions, "dislike", "carrots").status_code == 409
    assert change(client, riley, onions, "like", "carrots").status_code == 409
    assert change(client, riley, carrots, "like", "carrots").status_code == 200  # changing its own mind is fine
    assert sorted(shown(client, riley)) == ["dislike:onions", "like:carrots"]


def test_a_preference_can_be_forgotten(client, riley):
    pref_id = remember(client, riley, "dislike", "carrots").json()["preferences"][0]["id"]
    r = forget(client, riley, pref_id)
    assert r.status_code == 200, r.text
    assert r.json()["preferences"] == [] and r.json()["household"]["preferences"] == []
    assert shown(client, riley) == {}
    with SessionLocal() as db:
        assert db.get(Preference, pref_id) is None  # deleted, not just unlinked
    assert forget(client, riley, pref_id).status_code == 404


def test_a_preference_of_an_unknown_kind_is_still_listed_and_can_be_forgotten(client, riley):
    with SessionLocal() as db:
        household = db.scalar(select(Household).join(User).where(User.email == "riley@trolleymate.demo"))
        household.preferences.append(Preference(kind="avoid_store", value="corner shop"))
        db.commit()
    (pref,) = shown(client, riley).values()
    assert (pref["label"], pref["effect"], pref["status"]) == ("Avoid store", "unknown", "no_match")
    assert forget(client, riley, pref["id"]).status_code == 200


# --- Applied in later sessions, mandatory restrictions first -------------------------------


def only_word(name: str) -> str | None:
    """A word of a product's name that a dislike would match on that product alone."""
    with SessionLocal() as db:
        catalogue = optimisable_products(db)
        for word in re.findall(r"[a-z]{3,}", name.lower()):
            if [p.name for p in catalogue if disliked_by(p, [f"dislike:{word}"])] == [name]:
                return word
    return None


def test_saved_preferences_apply_to_later_sessions(client, riley):
    _, carried, before = later_session(client, riley)
    # Which products the cheapest week holds depends on the day's specials (seeded by weekday),
    # so dislike two products from the basket this run actually got.
    picks = [(name, word) for name in sorted(before) if (word := only_word(name))]
    assert carried == [] and len(picks) >= 2, before
    (first, first_word), (second, second_word) = picks[:2]

    pref_id = remember(client, riley, "dislike", first_word).json()["preferences"][0]["id"]
    _, carried, after = later_session(client, riley)
    assert carried == [f"dislike:{first_word}"] and first not in after

    change(client, riley, pref_id, "dislike", second_word)
    _, carried, after = later_session(client, riley)
    assert carried == [f"dislike:{second_word}"] and second not in after

    forget(client, riley, pref_id)
    _, carried, after = later_session(client, riley)
    assert carried == [] and after == before


def test_a_change_does_not_rewrite_a_session_already_confirmed(client, riley):
    pref_id = remember(client, riley, "dislike", "carrot").json()["preferences"][0]["id"]
    sid, carried, _ = later_session(client, riley)
    forget(client, riley, pref_id)

    constraints = client.get("/api/sessions/current", headers=riley).json()["constraints"]
    assert constraints["payload"]["preferences"] == carried == ["dislike:carrot"]
    assert "Carrots 1kg" not in basket(client, riley, sid)  # rebuilt from the confirmed constraints


def test_mandatory_restrictions_come_before_a_like(client, alex):
    pref = remember(client, alex, "like", "almond milk").json()["preferences"][-1]
    assert pref["status"] == "overridden" and pref["matches"] == []
    assert pref["blocked"] == [{"product": "Almond Milk 1L", "reason": "Tree nuts (Jamie)"}]

    milk = remember(client, alex, "like", "milk").json()["preferences"][-1]
    blocked = {b["product"]: b["reason"] for b in milk["blocked"]}
    assert milk["status"] == "applied" and "Lactose Free Milk 2L" in milk["matches"]
    assert blocked["Full Cream Milk 2L"] == "Lactose (Alex)" and not set(blocked) & set(milk["matches"])

    sid, carried, items = later_session(client, alex, ALEX_WEEK)
    assert "like:almond milk" in carried and "Almond Milk 1L" not in items
    excluded = client.get("/api/sessions/current", headers=alex).json()["basket"]["excluded"]
    assert "Almond Milk 1L" in {e["product"] for e in excluded}


def test_a_like_wins_a_close_call_in_later_baskets(client, alex):
    _, _, before = later_session(client, alex, ALEX_WEEK, "balanced")
    assert "Firm Tofu 450g" not in before

    pref_id = remember(client, alex, "like", "firm tofu").json()["preferences"][-1]["id"]
    sid, carried = confirmed(client, alex, ALEX_WEEK)
    b = build(client, alex, sid, "balanced")
    tofu = next(i for i in b["items"] if i["product"]["name"] == "Firm Tofu 450g")
    assert "like:firm tofu" in carried and tofu["rationale"].endswith("; you like firm tofu")
    assert b["total"] <= b["budget"]
    with SessionLocal() as db:
        assert db.get(Basket, b["id"]).notes["facts"]["favoured_by_preferences"] == ["you like firm tofu"]

    forget(client, alex, pref_id)
    assert later_session(client, alex, ALEX_WEEK, "balanced")[2] == before


def test_a_like_never_pulls_in_an_unsafe_product(client, alex):
    with SessionLocal() as db:
        household = db.scalar(select(Household).join(User).where(User.email == "alex@trolleymate.demo"))
        agent = AgentContext(db=db, llm=get_llm()).compliance
        milks = [p for p in optimisable_products(db) if p.substitution_group == "milk"]
        screening = agent.screen(milks, agent.restrictions_for(household, None), household_id=household.id)
        favoured = {db.get(Product, pid).name for pid in agent.favoured_products(milks, screening, ["like:milk"])}
    # Not full-cream or light milk (Alex's lactose), almond (Jamie's tree nuts) or oat (safety unconfirmed).
    assert favoured == {"Lactose Free Milk 2L", "Soy Milk 1L"}

    remember(client, alex, "like", "almond milk")
    remember(client, alex, "like", "oat milk")
    _, _, items = later_session(client, alex, ALEX_WEEK, "balanced")
    assert not {"Almond Milk 1L", "Oat Milk 1L"} & items


def test_a_dislike_beats_a_like(client, alex):
    remember(client, alex, "like", "firm tofu")
    remember(client, alex, "dislike", "tofu")
    assert "Firm Tofu 450g" not in later_session(client, alex, ALEX_WEEK, "balanced")[2]


def test_a_like_does_not_override_the_shoppers_goal(client, riley):
    _, _, before = later_session(client, riley)
    remember(client, riley, "like", "salmon")
    # Salmon costs far more per serving than the cheapest protein, so a lowest-cost week stays the same.
    assert later_session(client, riley)[2] == before


def test_a_dislike_never_stands_in_for_an_allergy(client, riley, alex):
    pref = remember(client, riley, "dislike", "Peanuts").json()["preferences"][0]
    assert "Peanuts looks like an allergy" in pref["hint"] and "restrictions" in pref["hint"]
    assert client.get("/api/households/me", headers=riley).json()["mandatory_restrictions"] == []  # still only a preference
    assert remember(client, riley, "like", "fish").json()["preferences"][-1]["hint"] is None  # a like is no allergy
    assert remember(client, alex, "dislike", "nuts").json()["preferences"][-1]["hint"] is None  # already a restriction


# --- Owner-only access and deletion -------------------------------------------------------


def test_preferences_need_sign_in(client):
    assert client.get(PREFS).status_code == 401
    assert client.post(PREFS, json={"kind": "dislike", "value": "carrots"}).status_code == 401
    assert client.put(f"{PREFS}/1", json={"kind": "dislike", "value": "carrots"}).status_code == 401
    assert client.delete(f"{PREFS}/1").status_code == 401


def test_only_the_owner_can_see_change_or_forget_a_preference(client, alex, riley):
    mushroom = shown(client, alex)["dislike:mushroom"]["id"]
    assert shown(client, riley) == {}
    assert change(client, riley, mushroom, "like", "mushroom").status_code == 404
    assert forget(client, riley, mushroom).status_code == 404
    assert [(p.id, p.kind, p.value) for p in rows("alex@trolleymate.demo")] == [(mushroom, "dislike", "mushroom")]


@pytest.mark.parametrize("staff", ["sam", "maya"])
def test_staff_accounts_reach_no_ones_preferences(client, alex, staff, request):
    headers = request.getfixturevalue(staff)
    mushroom = shown(client, alex)["dislike:mushroom"]["id"]
    assert client.get(PREFS, headers=headers).status_code == 404
    assert remember(client, headers, "dislike", "carrots").status_code == 404
    assert change(client, headers, mushroom, "like", "mushroom").status_code == 404
    assert forget(client, headers, mushroom).status_code == 404
    assert [(p.kind, p.value) for p in rows("alex@trolleymate.demo")] == [("dislike", "mushroom")]


def test_forgetting_a_preference_leaves_no_stored_copy(client, riley):
    pref_id = remember(client, riley, "dislike", "anchovies").json()["preferences"][0]["id"]
    change(client, riley, pref_id, "dislike", "sardines")
    forget(client, riley, pref_id)

    assert rows("riley@trolleymate.demo") == []
    with SessionLocal() as db:
        log = list(db.scalars(select(AuditRecord).where(AuditRecord.action == "update_preferences")))
        everything = " ".join(f"{a.decision} {a.rationale} {a.payload}" for a in db.scalars(select(AuditRecord)))
    assert [a.decision for a in log] == [
        f"Remembered a dislike preference (#{pref_id})",
        f"Changed preference #{pref_id} (now a dislike)",
        f"Forgot a dislike preference (#{pref_id})",
    ]
    assert "anchovies" not in everything and "sardines" not in everything
    _, carried, _ = later_session(client, riley)
    assert carried == []


def _decline_first_swap(client, headers, text="$80 for the week, two meals a day for myself"):
    sid = client.post("/api/sessions", headers=headers).json()["session"]["id"]
    rid = client.post(f"/api/sessions/{sid}/requests", json={"text": text}, headers=headers).json()["intake"]["request_id"]
    client.post(f"/api/requests/{rid}/confirm", headers=headers)
    b = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=headers).json()["basket"]
    for item in b["items"]:
        sub = client.post(f"/api/baskets/{b['id']}/items/{item['id']}/substitute", json={}, headers=headers).json()["substitution"]
        if sub["status"] == "pending":
            client.post(f"/api/substitutions/{sub['id']}/reject", headers=headers)
            return item["product"]["name"], sub["replacement"]["name"]
    raise AssertionError("no swap offered")


def test_declining_the_same_swap_twice_is_learned_as_a_dislike(client, riley):
    original, replacement = _decline_first_swap(client, riley)
    assert not [p for p in client.get("/api/households/me", headers=riley).json()["preferences"] if p["source"] == "learned"]
    again = _decline_first_swap(client, riley)
    assert again == (original, replacement)
    learned = [p for p in client.get("/api/households/me", headers=riley).json()["preferences"] if p["source"] == "learned"]
    assert [(p["kind"], p["value"]) for p in learned] == [("dislike", replacement.lower())]


def test_a_like_is_never_overridden_by_learning(client, riley):
    original, replacement = _decline_first_swap(client, riley)
    remember(client, riley, "like", replacement.lower())
    _decline_first_swap(client, riley)
    prefs = client.get("/api/households/me", headers=riley).json()["preferences"]
    assert not [p for p in prefs if p["source"] == "learned"]


def test_intake_audit_does_not_copy_private_preference_values(client, riley, maya):
    pref_id = remember(client, riley, "dislike", "anchovies").json()["preferences"][0]["id"]
    sid, _ = confirmed(client, riley)
    forget(client, riley, pref_id)
    with SessionLocal() as db:
        logs = list(db.scalars(select(AuditRecord).where(AuditRecord.session_id == sid)))
        assert logs
        assert "anchovies" not in str([a.payload for a in logs])
    response = client.get(f"/api/audit?session_id={sid}", headers=maya)
    assert "anchovies" not in response.text


def test_chat_routing_does_not_copy_private_intake_text(client, riley, maya):
    sid = client.post("/api/sessions", headers=riley).json()["session"]["id"]
    response = client.post(f"/api/sessions/{sid}/chat", headers=riley, json={
        "text": "$80 for 3 days, two meals a day for myself. I dislike anchovies."})
    assert response.status_code == 200
    logs = client.get(f"/api/audit?session_id={sid}", headers=maya).json()
    private_logs = [a for a in logs if a["action"] in {"route_message", "extract_constraints"}]
    assert {a["action"] for a in private_logs} == {"route_message", "extract_constraints"}
    assert "anchovies" not in str([a["payload"] for a in private_logs])
    with SessionLocal() as db:
        records = list(db.scalars(select(AuditRecord).where(AuditRecord.session_id == sid)))
        assert "anchovies" not in str([a.payload for a in records])
        intake = next(a for a in records if a.action == "extract_constraints")
        intake.payload = {**intake.payload, "raw_text": "legacy private anchovies request"}
        db.commit()
    # Older records must receive the same protection when read.
    assert "anchovies" not in client.get(f"/api/audit?session_id={sid}", headers=maya).text
