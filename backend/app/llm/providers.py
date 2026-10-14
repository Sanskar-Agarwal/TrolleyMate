"""Concrete LLM providers. Pick one with LLM_PROVIDER in `.env`.

- OpenAICompatibleProvider: any server exposing POST /chat/completions — the
  ELEC5620 Campus Qwen proxy, OpenAI, Ollama (local models), LM Studio, Groq...
- AnthropicProvider: Claude through the official `anthropic` SDK.

The offline MockProvider lives in the task modules (each task has a `mock()`),
so it needs no class here.
"""

from __future__ import annotations

import json

import httpx

from app.core.config import Settings
from app.llm.base import JSON_INSTRUCTION, LLMError, LLMProvider


class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(self, settings: Settings):
        if not settings.llm_base_url:
            raise LLMError("LLM_BASE_URL is required for the openai_compatible provider")
        if not settings.llm_model:
            raise LLMError("LLM_MODEL is required for the openai_compatible provider")
        self.base_url = settings.llm_base_url.rstrip("/")
        self.model = settings.llm_model
        self.api_key = settings.llm_api_key
        self.timeout = settings.llm_timeout_s
        self.temperature = settings.llm_temperature
        self.json_mode = settings.llm_json_mode

    def generate(self, *, system: str, user: str, schema: dict | None) -> str:
        if schema is not None:
            system = system + JSON_INSTRUCTION + json.dumps(schema)
        body: dict = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if schema is not None and self.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

        response = httpx.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout)
        if response.status_code == 400 and "response_format" in body:
            # Some servers (older vLLM / proxies) reject JSON mode — retry with prompt-only JSON.
            body.pop("response_format")
            response = httpx.post(
                f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout
            )
        if response.status_code >= 400:
            raise LLMError(f"{response.status_code} from {self.base_url}: {response.text[:300]}")
        try:
            return response.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"Unexpected response shape: {response.text[:300]}") from exc


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, settings: Settings):
        import anthropic  # imported lazily so the mock/openai paths don't need it

        self._anthropic = anthropic
        api_key = settings.anthropic_api_key or settings.llm_api_key or None
        self.client = anthropic.Anthropic(api_key=api_key, timeout=settings.llm_timeout_s, max_retries=1)
        self.model = settings.llm_model or "claude-opus-5-5"
        self.effort = settings.anthropic_effort
        self.fallbacks = settings.anthropic_fallbacks

    def generate(self, *, system: str, user: str, schema: dict | None) -> str:
        anthropic = self._anthropic
        output_config: dict = {"effort": self.effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        request = {
            "model": self.model,
            "max_tokens": 16000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": output_config,
        }
        try:
            if self.fallbacks:
                # Server-side refusal fallback: if this model declines, the API re-runs
                # the request on a suitable fallback model inside the same call.
                response = self.client.beta.messages.create(
                    **request, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
                )
            else:
                response = self.client.messages.create(**request)
        except anthropic.BadRequestError:
            # Schema not accepted for structured output (or beta unavailable on this
            # account): fall back to prompt-only JSON on the plain endpoint.
            request["output_config"] = {"effort": self.effort}
            if schema is not None:
                request["system"] = system + JSON_INSTRUCTION + json.dumps(schema)
            response = self.client.messages.create(**request)

        if response.stop_reason == "refusal":
            raise LLMError("The model declined this request")
        return "".join(block.text for block in response.content if block.type == "text")
