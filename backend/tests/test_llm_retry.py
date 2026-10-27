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
