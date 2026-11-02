"""Authentication, CSRF, throttling and persisted session acceptance tests."""
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.request_security import enforce_limit
from app.core.security import hash_password, token_digest, verify_password
from app.domain import LoginSession, User

LOGIN = {"email": "riley@trolleymate.demo", "password": "demo1234"}


def sign_in(client):
    result = client.post("/api/auth/login", json=LOGIN)
    assert result.status_code == 200, result.text
    return result.json()["token"]


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_passwords_salted_and_versioned():
    first, second = hash_password("long test password"), hash_password("long test password")
    assert first != second
    assert first.startswith("pbkdf2_sha256$600000$")
    assert verify_password("long test password", first)
    assert not verify_password("wrong", first)
    for malformed in ("", "other$salt$hash", "pbkdf2_sha256$huge$salt$hash", "pbkdf2_sha256$999999999$salt$hash"):
        assert not verify_password("wrong", malformed)


def test_legacy_password_upgrades_only_after_valid_login(client):
    salt = "a" * 32
    digest = hashlib.pbkdf2_hmac("sha256", b"demo1234", salt.encode(), 120_000).hex()
    legacy = f"pbkdf2${salt}${digest}"
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == LOGIN["email"]))
        user.password_hash = legacy
        db.commit()
    assert client.post("/api/auth/login", json={**LOGIN, "password": "wrong"}).status_code == 401
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email == LOGIN["email"])).password_hash == legacy
    token = sign_in(client)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == LOGIN["email"]))
        assert user.password_hash.startswith("pbkdf2_sha256$600000$")
        assert db.get(LoginSession, token_digest(token)) is not None
        assert token not in str(list(db.scalars(select(LoginSession.token_hash))))


def test_no_browser_cookies_and_logout_revokes_token(client):
    response = client.post("/api/auth/login", json=LOGIN)
    token = response.json()["token"]
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/auth/me", headers=headers(token)).status_code == 200
    assert client.get("/api/auth/me", headers={"Cookie": f"token={token}"}).status_code == 401
    assert client.post("/api/auth/logout", headers=headers(token), json={}).status_code == 200
    assert client.get("/api/auth/me", headers=headers(token)).status_code == 401


def test_session_cap_evicts_oldest_and_logout_all_is_account_scoped(client, alex, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_active_sessions", 2)
    first, second, third = sign_in(client), sign_in(client), sign_in(client)
    assert len({first, second, third}) == 3
    assert client.get("/api/auth/me", headers=headers(first)).status_code == 401
    assert client.get("/api/auth/me", headers=headers(second)).status_code == 200
    assert client.post("/api/auth/logout-all", headers=headers(third), json={}).status_code == 200
    for token in (second, third):
        assert client.get("/api/auth/me", headers=headers(token)).status_code == 401
    assert client.get("/api/auth/me", headers=alex).status_code == 200


@pytest.mark.parametrize("field", ["last_seen", "expires_at"])
def test_server_enforces_idle_and_absolute_expiry(client, field):
    token = sign_in(client)
    with SessionLocal() as db:
        session = db.get(LoginSession, token_digest(token))
        setattr(session, field, time.time() - 31 * 60)
        db.commit()
    assert client.get("/api/auth/me", headers=headers(token)).status_code == 401


def test_activity_touches_idle_time_without_extending_absolute_expiry(client):
    token = sign_in(client)
    with SessionLocal() as db:
        session = db.get(LoginSession, token_digest(token))
        expires = session.expires_at
        session.last_seen = time.time() - 60
        old = session.last_seen
        db.commit()
    assert client.get("/api/auth/me", headers=headers(token)).status_code == 200
    with SessionLocal() as db:
        session = db.get(LoginSession, token_digest(token))
        assert session.last_seen > old
        assert session.expires_at == expires
    for bad in ("bogus", "a" * 43, "payload.signature"):
        assert client.get("/api/auth/me", headers=headers(bad)).status_code == 401


@pytest.mark.parametrize("extra", [
    {"Origin": "https://evil.example"}, {"Origin": "null"},
    {"Referer": "https://evil.example/attack"}, {"Sec-Fetch-Site": "cross-site"},
    {"X-TrolleyMate-Request": ""},
])
def test_csrf_rejects_untrusted_writes_before_login(client, extra):
    assert client.post("/api/auth/login", headers=extra, json=LOGIN).status_code == 403


def test_csrf_allows_same_origin_and_configured_dev_origin(client):
    for origin in ("http://testserver", "http://localhost:5173"):
        assert client.post("/api/auth/login", headers={"Origin": origin}, json=LOGIN).status_code == 200
    assert client.post("/api/auth/login", content='{"email":"x"}', headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.post("/api/auth/login", data=LOGIN).status_code == 415


def test_csrf_applies_to_authenticated_delete_and_cors_preflight(client, riley):
    assert client.delete("/api/households/members/1", headers={**riley, "Origin": "https://evil.example"}).status_code == 403
    preflight = client.options("/api/auth/login", headers={"Origin": "https://evil.example",
        "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-trolleymate-request"})
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers


def test_login_ip_limit_and_retry_after(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_attempts_per_minute", 2)
    for _ in range(2):
        assert client.post("/api/auth/login", json={**LOGIN, "password": "bad"}).status_code == 401
    blocked = client.post("/api/auth/login", headers={"X-Forwarded-For": "203.0.113.1"}, json=LOGIN)
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["retry-after"]) <= 60


def test_account_limit_normalises_email(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "account_login_attempts_per_quarter_hour", 1)
    assert client.post("/api/auth/login", json={**LOGIN, "password": "bad"}).status_code == 401
    blocked = client.post("/api/auth/login", json={**LOGIN, "email": " RILEY@TROLLEYMATE.DEMO "})
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) <= 900


@pytest.mark.parametrize("logout_path", ["/api/auth/logout", "/api/auth/logout-all"])
def test_api_and_account_write_limits_leave_health_and_logout_available(client, riley, monkeypatch, logout_path):
    monkeypatch.setattr(get_settings(), "account_writes_per_minute", 1)
    assert client.post("/api/sessions", headers=riley, json={}).status_code == 200
    assert client.post("/api/sessions", headers=riley, json={}).status_code == 429
    assert client.post(logout_path, headers=riley, json={}).status_code == 200
    monkeypatch.setattr(get_settings(), "api_requests_per_minute", 1)
    assert client.get("/api/auth/demo-accounts").status_code == 429
    assert client.get("/api/health").status_code == 200


def test_rate_limit_shared_atomic_window_and_reset(client, monkeypatch):
    from fastapi import HTTPException
    def attempt(_):
        try:
            enforce_limit("parallel-test", "test-user", 3, 60)
            return 200
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count(200) == 3
    assert results.count(429) == 5
    now = time.time()
    monkeypatch.setattr("app.core.request_security.time.time", lambda: now + 61)
    enforce_limit("parallel-test", "test-user", 3, 60)


def test_registration_throttled_separately(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "registrations_per_hour", 1)
    body = {"display_name": "Tester", "email": "security@example.test", "password": "test-password"}
    assert client.post("/api/auth/register", json=body).status_code == 201
    assert client.post("/api/auth/register", json={**body, "email": "second@example.test"}).status_code == 429
