"""1.2.13 — shoppers can create their own account and household."""

import pytest


def test_new_shopper_can_register_sign_in_and_shop(client):
    r = client.post("/api/auth/register", json={"display_name": "Jordan Lee", "email": "Jordan@Example.com", "password": "groceries1"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["role"] == "shopper" and body["user"]["email"] == "jordan@example.com"
    headers = {"Authorization": f"Bearer {body['token']}"}
    household = client.get("/api/households/me", headers=headers).json()
    assert household["name"] == "Jordan's household" and [m["name"] for m in household["members"]] == ["Jordan"]

    login = client.post("/api/auth/login", json={"email": "jordan@example.com", "password": "groceries1"})
    assert login.status_code == 200
    sid = client.post("/api/sessions", headers=headers).json()["session"]["id"]
    assert client.post(f"/api/sessions/{sid}/requests", json={"text": "$60 for 5 days, dinner only"}, headers=headers).status_code == 200


def test_duplicate_email_is_refused(client):
    r = client.post("/api/auth/register", json={"display_name": "Copy", "email": "alex@trolleymate.demo", "password": "longenough"})
    assert r.status_code == 409


@pytest.mark.parametrize("body", [
    {"display_name": "A", "email": "not-an-email", "password": "longenough"},
    {"display_name": "A", "email": "a@b.co", "password": "short"},
    {"display_name": "   ", "email": "a@b.co", "password": "longenough"},
])
def test_invalid_registration_is_refused(client, body):
    assert client.post("/api/auth/register", json=body).status_code == 422


def test_registration_cannot_create_a_reviewer(client):
    r = client.post("/api/auth/register", json={"display_name": "Eve", "email": "eve@x.io", "password": "longenough", "role": "founder"})
    assert r.status_code == 201 and r.json()["user"]["role"] == "shopper"
