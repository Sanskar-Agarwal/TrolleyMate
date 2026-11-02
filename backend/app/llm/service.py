"""LLMService — the single entry point agents use to call a language model.

    result = llm.run("extract_constraints", {"text": "..."})
    result.data          # validated dict (structured tasks) or str (text tasks)
    result.model_version # e.g. "openai_compatible:qwen3-32b" → stored in the audit log

If the configured provider fails (network, bad key, invalid JSON) and
LLM_FALLBACK_TO_MOCK is on, the task's offline mock answers instead and the
result is marked `fell_back=True` so the UI and audit log can show it.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from functools import lru_cache

from app.core.config import Settings, get_settings
from app.core.tracing import operation
from app.llm.base import LLMError, LLMProvider, LLMResult, extract_json, strip_thinking
from app.llm.tasks import TASKS

log = logging.getLogger("trolleymate.llm")


class LLMService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.provider: LLMProvider | None = None
        self.config_error: str | None = None
        self.last_error: str | None = None
        self.last_error_at: datetime | None = None
        self.calls = 0
        self.fallbacks = 0
        name = settings.llm_provider.lower()
        try:
            if name == "openai_compatible":
                from app.llm.providers import OpenAICompatibleProvider

                self.provider = OpenAICompatibleProvider(settings)
            elif name == "anthropic":
                from app.llm.providers import AnthropicProvider

                self.provider = AnthropicProvider(settings)
            elif name != "mock":
                raise LLMError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'")
        except Exception as exc:  # misconfiguration → run on the mock, but say so
            self.config_error = str(exc)
            log.warning("LLM provider not available, using mock: %s", exc)

    @property
    def provider_name(self) -> str:
        return self.provider.name if self.provider else "mock"

    @property
    def model_name(self) -> str:
        return self.provider.model if self.provider else "rule-based"

    @property
    def mode(self) -> str:
        """What is actually answering, so the UI can label it (KAN-29):
        live · degraded (live with offline fallbacks) · offline (chosen) · offline_unconfigured."""
        if self.provider is None:
            return "offline_unconfigured" if self.config_error else "offline"
        return "degraded" if self.fallbacks else "live"

    def status(self) -> dict:
        labels = {
            "live": f"Live AI ({self.model_name})",
            "degraded": f"Live AI ({self.model_name}) with {self.fallbacks} offline fallback(s)",
            "offline": "Offline agent mode: rule-based answers, no AI provider",
            "offline_unconfigured": "Offline agent mode: AI provider not configured",
        }
        return {
            "mode": self.mode,
            "mode_label": labels[self.mode],
            "provider": self.provider_name,
            "model": self.model_name,
            "configured_provider": self.settings.llm_provider,
            "fallback_to_mock": self.settings.llm_fallback_to_mock,
            "config_error": self.config_error,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at.isoformat() if self.last_error_at else None,
            "calls": self.calls,
            "fallbacks": self.fallbacks,
        }

    def run(self, task_name: str, ctx: dict) -> LLMResult:
        # Attribute values are operational identifiers, never the prompt/context.
        with operation("ai.task", {"ai.task": task_name if task_name in TASKS else "unknown",
                                   "ai.provider": self.provider_name, "ai.model": self.model_name}) as span:
            result = self._run(task_name, ctx)
            span.set_attribute("ai.fallback", result.fell_back)
            return result

    def _run(self, task_name: str, ctx: dict) -> LLMResult:
        task = TASKS[task_name]
        self.calls += 1
        started = time.perf_counter()
        prompt = {"system": task.system, "user": task.build_user(ctx)}

        if self.provider is None:
            return LLMResult(
                data=task.mock(ctx), provider="mock", model="rule-based", prompt=prompt,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        try:
            with operation("ai.provider.call"):
                raw = self.provider.generate(system=prompt["system"], user=prompt["user"], schema=task.schema)
            if task.schema is None:
                data = strip_thinking(raw)
            else:
                data = extract_json(raw)
                if task.output_model is not None:
                    data = task.output_model.model_validate(data).model_dump()
            return LLMResult(
                data=data, provider=self.provider.name, model=self.provider.model, prompt=prompt, raw=raw,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            self.last_error = f"{task_name}: {exc}"[:500]
            self.last_error_at = datetime.now()
            log.warning("LLM task %s failed on %s: %s", task_name, self.provider.name, exc)
            if not self.settings.llm_fallback_to_mock:
                raise
            self.fallbacks += 1
            return LLMResult(
                data=task.mock(ctx), provider=self.provider.name, model=self.provider.model, fell_back=True,
                error=str(exc)[:300], prompt=prompt, latency_ms=int((time.perf_counter() - started) * 1000),
            )


@lru_cache
def get_llm() -> LLMService:
    return LLMService(get_settings())
