"""KAN-29 — the app keeps working, and says so, when the AI key is missing or the network fails.

No test here touches the real network: failures are simulated with a refused local port and a
stubbed HTTP response.
"""

import httpx
import pytest

import app.api.escalations as escalations_api
import app.api.system as system_api
import app.core.deps as deps
from app.core.config import Settings
from app.llm.base import LLMError
from app.llm.service import LLMService
from tests.test_basket_flow import confirmed_session


def live_settings(**overrides) -> Settings:
    base = dict(llm_provider="openai_compatible", llm_base_url="http://127.0.0.1:9/v1", llm_model="qwen-demo", llm_api_key="k", llm_timeout_s=1)
    return Settings(**{**base, **overrides})


@pytest.fixture()
def use_llm(monkeypatch):
    """Swap the app's LLM service for one built from the given settings."""
    def install(settings: Settings) -> LLMService:
        svc = LLMService(settings)
        for module in (deps, escalations_api, system_api):
            monkeypatch.setattr(module, "get_llm", lambda: svc)
        return svc
    return install


def test_default_install_runs_offline_and_says_so(client):
    status = client.get("/api/system/llm").json()
    assert status["mode"] == "offline"
    assert status["mode_label"].startswith("Offline agent mode")


def test_misconfigured_provider_runs_offline_and_explains_why(client, use_llm):
    use_llm(Settings(llm_provider="openai_compatible", llm_base_url="", llm_model=""))
    status = client.get("/api/system/llm").json()
    assert status["mode"] == "offline_unconfigured"
    assert "LLM_BASE_URL" in status["config_error"]


def test_absent_or_rejected_key_falls_back_and_is_flagged(monkeypatch):
    def rejected(*_args, **_kwargs):
        return httpx.Response(401, json={"error": {"message": "Missing API key"}}, request=httpx.Request("POST", "http://proxy/v1/chat/completions"))

    monkeypatch.setattr("app.llm.providers.httpx.post", rejected)
    svc = LLMService(live_settings(llm_api_key=""))
    result = svc.run("classify_intent", {"text": "$50 for the week, dinners", "state": {}})
    assert result.fell_back and "401" in result.error
    assert result.model_version.endswith("(fallback)")
    assert result.data["intent"] == "new_request"  # the offline answer still did the job
    assert svc.status()["mode"] == "degraded" and "401" in svc.status()["last_error"]


def test_whole_shopper_journey_survives_a_network_failure(client, riley, maya, use_llm):
    svc = use_llm(live_settings())  # nothing listens on port 9: every call is refused
    sid = confirmed_session(client, riley, "$70 for the week, two meals a day for myself")
    r = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=riley).json()
    assert r["status"] == "ok" and r["basket"]["items"]

    llm_steps = [t for t in r["trace"] if t["llm"]]
    assert llm_steps and all(t["fell_back"] for t in llm_steps)  # every AI step is labelled
    explained = client.get(f"/api/baskets/{r['basket']['id']}/explain", headers=riley).json()
    assert explained["available"] and explained["text"]

    audited = [a for a in client.get(f"/api/audit?basket_id={r['basket']['id']}", headers=maya).json() if a["provider"] != "deterministic"]
    assert audited and all(a["model_version"].endswith("(fallback)") for a in audited)
    status = client.get("/api/system/llm").json()
    assert status["mode"] == "degraded" and status["fallbacks"] == svc.fallbacks > 0


def test_fallback_can_be_switched_off_to_surface_failures():
    svc = LLMService(live_settings(llm_fallback_to_mock=False))
    with pytest.raises((LLMError, httpx.HTTPError)):
        svc.run("chat_reply", {"text": "hi", "state": {}})
