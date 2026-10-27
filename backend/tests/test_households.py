"""KAN-26 / UC-10 — accounts and household dietary profiles.

Evidence: profile lifecycle, multi-member restrictions, failed save and access tests.
"""

import pytest

from tests.conftest import login


def members(client, headers) -> dict:
    return {m["name"]: m for m in client.get("/api/households/me", headers=headers).json()["members"]}


def test_profile_lifecycle_add_edit_remove(client, riley):
    r = client.post(
        "/api/households/me/members",
        json={"name": "Sam", "age_group": "child", "restrictions": [{"restriction": "peanuts", "severity": "severe"}]},
        headers=riley,
    )
    assert r.status_code == 200, r.text
    sam = members(client, riley)["Sam"]
    assert sam["age_group"] == "child"
    assert [x["restriction"] for x in sam["restrictions"]] == ["peanuts"]
    assert sam["restrictions"][0]["kind"] == "allergy"  # filled in from the vocabulary

    r = client.put(
        f"/api/households/me/members/{sam['id']}",
        json={"name": "Sam", "age_group": "teen", "restrictions": [{"restriction": "vegetarian", "severity": "moderate"}]},
        headers=riley,
    )
    assert r.status_code == 200, r.text
    sam = members(client, riley)["Sam"]
    assert sam["age_group"] == "teen"
    assert [x["restriction"] for x in sam["restrictions"]] == ["vegetarian"]

    assert client.delete(f"/api/households/me/members/{sam['id']}", headers=riley).status_code == 200
    assert "Sam" not in members(client, riley)


def test_mandatory_restrictions_combine_across_members_keeping_the_strictest(client, alex):
    jamie = members(client, alex)["Jamie"]
    # Add a second member with the same allergy at a milder level, plus a new diet.
    client.post(
        "/api/households/me/members",
        json={"name": "Kit", "restrictions": [{"restriction": "tree_nuts", "severity": "mild"}, {"restriction": "halal", "severity": "moderate"}]},
        headers=alex,
    )
    h = client.get("/api/households/me", headers=alex).json()
    merged = {r["restriction"]: r for r in h["mandatory_restrictions"]}
    assert set(merged) == {"lactose", "tree_nuts", "halal"}
    assert merged["tree_nuts"]["severity"] == "severe"  # Jamie's, not Kit's milder one
    assert set(merged["tree_nuts"]["members"]) == {jamie["name"], "Kit"}
    assert h["size"] == 3


def test_preferences_are_never_mandatory(client, riley):
    rid = members(client, riley)["Riley"]["id"]
    client.put(
        f"/api/households/me/members/{rid}",
        json={"name": "Riley", "restrictions": [{"restriction": "pork_free", "severity": "preference"}]},
        headers=riley,
    )
    assert client.get("/api/households/me", headers=riley).json()["mandatory_restrictions"] == []


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "Riley", "restrictions": [{"restriction": "moonbeams"}]},
        {"name": "Riley", "restrictions": [{"restriction": "egg"}, {"restriction": "eggs"}]},  # same id twice
        {"name": "   ", "restrictions": []},
        {"name": "Riley", "age_group": "toddler", "restrictions": []},
    ],
)
def test_failed_save_keeps_the_last_valid_profile(client, riley, bad):
    rid = members(client, riley)["Riley"]["id"]
    client.put(f"/api/households/me/members/{rid}", json={"name": "Riley", "restrictions": [{"restriction": "fish"}]}, headers=riley)
    before = client.get("/api/households/me", headers=riley).json()

    r = client.put(f"/api/households/me/members/{rid}", json=bad, headers=riley)
    assert r.status_code in (400, 422)
    if r.status_code == 400:
        assert "hasn't changed" in r.json()["detail"]
    assert client.get("/api/households/me", headers=riley).json() == before


def test_cannot_remove_the_last_member(client, riley):
    rid = members(client, riley)["Riley"]["id"]
    r = client.delete(f"/api/households/me/members/{rid}", headers=riley)
    assert r.status_code == 400
    assert "Riley" in members(client, riley)


def test_profile_access_is_limited_to_the_owner(client, alex, riley, sam):
    assert client.get("/api/households/me").status_code == 401
    # Staff accounts have no household of their own.
    assert client.get("/api/households/me", headers=sam).status_code == 404
    # A shopper can't reach another household's members by id.
    jamie_id = members(client, alex)["Jamie"]["id"]
    assert client.put(f"/api/households/me/members/{jamie_id}", json={"name": "x", "restrictions": []}, headers=riley).status_code == 404
    assert client.delete(f"/api/households/me/members/{jamie_id}", headers=riley).status_code == 404
    assert "Jamie" in members(client, alex)


def test_profile_changes_apply_to_future_sessions(client, riley):
    rid = members(client, riley)["Riley"]["id"]
    client.put(f"/api/households/me/members/{rid}", json={"name": "Riley", "restrictions": [{"restriction": "gluten"}]}, headers=riley)
    s = client.post("/api/sessions", headers=riley).json()["session"]
    draft = client.post(f"/api/sessions/{s['id']}/requests", json={"text": "$60 for 5 days, dinner only"}, headers=riley).json()["intake"]["draft"]
    locked = {r["restriction"] for r in draft["restrictions"] if r.get("locked")}
    assert "gluten" in locked


def test_profile_changes_are_audited_without_health_details(client, riley):
    rid = members(client, riley)["Riley"]["id"]
    client.put(f"/api/households/me/members/{rid}", json={"name": "Riley", "restrictions": [{"restriction": "sesame"}]}, headers=riley)
    maya = login(client, "maya@trolleymate.demo")
    entries = [e for e in client.get("/api/audit?limit=50", headers=maya).json() if e["action"] == "update_profile"]
    assert entries, "profile change was not audited"
    assert all("sesame" not in e["decision"] and "Riley" not in e["decision"] for e in entries)
