import os
import tempfile
from pathlib import Path

# Must be set before the app is imported: a throwaway DB and the offline LLM.
_tmp = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.as_posix()}"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["SEED_ON_STARTUP"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import SessionLocal, reset_db  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_all  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    # Functional suites exercise bursts; security tests override individual limits.
    from app.core.config import get_settings
    for key in ("api_requests_per_minute", "account_writes_per_minute", "auth_attempts_per_minute",
                "account_login_attempts_per_quarter_hour", "registrations_per_hour"):
        monkeypatch.setattr(get_settings(), key, 10000)
    from app.core.request_security import reset_limits
    reset_limits()
    reset_db()
    with SessionLocal() as db:
        seed_all(db)
    with TestClient(app, headers={"X-TrolleyMate-Request": "1"}) as c:
        yield c


def login(client: TestClient, email: str) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": "demo1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture()
def alex(client):
    return login(client, "alex@trolleymate.demo")


@pytest.fixture()
def riley(client):
    return login(client, "riley@trolleymate.demo")


@pytest.fixture()
def sam(client):
    return login(client, "sam@trolleymate.demo")


@pytest.fixture()
def maya(client):
    return login(client, "maya@trolleymate.demo")
