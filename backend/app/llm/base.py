from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    """What every LLM call returns. `provider`/`model` go straight into the audit log."""

    data: Any
    provider: str
    model: str
    fell_back: bool = False
    latency_ms: int = 0
    error: str | None = None
    prompt: dict = field(default_factory=dict)
    raw: str = ""

    @property
    def model_version(self) -> str:
        suffix = " (fallback)" if self.fell_back else ""
        return f"{self.provider}:{self.model}{suffix}"


class LLMProvider(ABC):
    name: str = "base"
    model: str = ""

    @abstractmethod
    def generate(self, *, system: str, user: str, schema: dict | None) -> str:
        """Return the model's raw text. JSON parsing happens in LLMService."""


JSON_INSTRUCTION = (
    "\n\nRespond with ONLY a JSON object (no prose, no code fences) that matches this JSON schema:\n"
)

_THINK = re.compile(r"<think>.*?</think>", re.S)


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates fences and <think> blocks)."""
    cleaned = _THINK.sub("", text).strip()
    cleaned = re.sub(r"^```(?:json)?|```$", "", cleaned, flags=re.M).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise LLMError(f"No JSON object in model reply: {text[:200]!r}") from None
        return json.loads(cleaned[start : end + 1])


def strip_thinking(text: str) -> str:
    return _THINK.sub("", text).strip()
