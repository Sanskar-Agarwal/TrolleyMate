"""Short provider rate limits are waited out; long ones fall back immediately."""

import httpx
import pytest

from app.core.config import Settings
from app.llm.base import LLMError
from app.llm.providers import OpenAICompatibleProvider, retry_after

OK = {"choices": [{"message": {"content": "hello"}}]}


def _provider(**overrides) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(Settings(llm_base_url="http://llm.test/v1", llm_model="m", **overrides))


def _script(monkeypatch, responses: list[httpx.Response]) -> list[float]:
    calls, sleeps = iter(responses), []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: next(calls))
    monkeypatch.setattr("app.llm.providers.time.sleep", sleeps.append)
    return sleeps


def _limited(text: str = "", headers: dict | None = None) -> httpx.Response:
    return httpx.Response(429, text=text, headers=headers or {})


def test_short_rate_limit_is_retried(monkeypatch):
    sleeps = _script(monkeypatch, [_limited("Please try again in 1.5s."), httpx.Response(200, json=OK)])
    assert _provider().generate(system="s", user="u", schema=None) == "hello"
    assert sleeps == [1.5]


def test_long_rate_limit_fails_fast_so_the_mock_takes_over(monkeypatch):
    sleeps = _script(monkeypatch, [_limited("Please try again in 18.96s.")])
    with pytest.raises(LLMError, match="429"):
        _provider().generate(system="s", user="u", schema=None)
    assert sleeps == []


def test_retries_are_bounded(monkeypatch):
    sleeps = _script(monkeypatch, [_limited(headers={"retry-after": "1"})] * 3)
    with pytest.raises(LLMError):
        _provider(llm_max_retries=2).generate(system="s", user="u", schema=None)
    assert sleeps == [1.0, 1.0]


@pytest.mark.parametrize("text,headers,expected", [
    ("", {"retry-after": "3"}, 3.0),
    ("Please try again in 1m2.5s.", {}, 62.5),
    ("no hint", {}, None),
])
def test_retry_after_parsing(text, headers, expected):
    assert retry_after(_limited(text, headers)) == expected


def test_request_bounds_output_and_uses_groq_qwen_instruct_mode(monkeypatch):
    sent = []
    def post(*args, **kwargs):
        sent.append(kwargs["json"])
        return httpx.Response(200, json=OK)
    monkeypatch.setattr(httpx, "post", post)
    provider = OpenAICompatibleProvider(Settings(_env_file=None, llm_base_url="https://api.groq.com/openai/v1",
        llm_model="qwen/qwen3.8-27b", llm_max_output_tokens=600))
    assert provider.generate(system="s", user="u", schema=None) == "hello"
    assert sent[0]["max_tokens"] == 600
    assert sent[0]["reasoning_effort"] == "none"
    _provider(llm_reasoning_effort="").generate(system="s", user="u", schema=None)
    assert "reasoning_effort" not in sent[1]


@pytest.mark.parametrize("choice", [
    {"finish_reason": "length", "message": {"content": '{"safe": true}'}},
    {"finish_reason": "stop", "message": {"content": ""}},
])
def test_incomplete_or_empty_model_answer_is_not_accepted(monkeypatch, choice):
    _script(monkeypatch, [httpx.Response(200, json={"choices": [choice]})])
    with pytest.raises(LLMError):
        _provider().generate(system="s", user="u", schema=None)
