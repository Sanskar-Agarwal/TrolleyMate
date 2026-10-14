"""Deterministic services: normalisation, LLM JSON parsing, edit parsing, fallback."""

from app.core.config import Settings
from app.llm.base import extract_json
from app.llm.service import LLMService
from app.llm.tasks.parse_edit import mock as parse_edit
from app.services.pricing.normalisation import normalise


def test_unit_price_normalisation():
    assert normalise(4.50, 1000, "g").label() == "$0.45 / 100 g"
    assert normalise(5.05, 2000, "ml").value == 0.253
    assert normalise(6.20, 12, "each").basis == "each"
    assert normalise(3.0, 0, "g") is None
    assert normalise(3.0, 100, "bunch") is None


def test_extract_json_tolerates_fences_and_think_blocks():
    assert extract_json('<think>hmm</think>```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! {"b": 2} hope that helps') == {"b": 2}


def test_parse_edit_spec_example():
    out = parse_edit({"items": ["Beef Mince 500g"], "text": "replace the beef with chicken and make it $10 cheaper"})
    assert out["operations"][0] == {"op": "replace", "target": "beef", "replacement": "chicken"}
    assert out["budget_change"] == {"mode": "delta", "amount": -10.0}


def test_bad_provider_config_falls_back_to_mock():
    svc = LLMService(Settings(llm_provider="openai_compatible", llm_base_url="", llm_model=""))
    assert svc.provider_name == "mock"
    assert svc.config_error
    result = svc.run("chat_reply", {"text": "hi", "state": {}})
    assert result.provider == "mock" and result.data


def test_unreachable_provider_falls_back_and_flags_it():
    svc = LLMService(Settings(llm_provider="openai_compatible", llm_base_url="http://127.0.0.1:9", llm_model="x", llm_timeout_s=1))
    result = svc.run("classify_intent", {"text": "$50 for the week", "state": {}})
    assert result.fell_back
    assert result.data["intent"] == "new_request"
