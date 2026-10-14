from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class Task:
    """One thing an agent asks an LLM to do.

    name         unique key used by `agent.think(name, ctx)`
    system       the system prompt
    build_user   turns the agent's context dict into the user message
    mock         deterministic offline answer for the same context (used when
                 LLM_PROVIDER=mock, in tests, and as a fallback if the real
                 provider fails)
    schema       JSON schema for structured output; None means free text
    output_model optional Pydantic model used to validate structured output
    """

    name: str
    system: str
    build_user: Callable[[dict], str]
    mock: Callable[[dict], Any]
    schema: dict | None = None
    output_model: type[BaseModel] | None = None


def nullable(type_name: str, **extra: Any) -> dict:
    return {"type": [type_name, "null"], **extra}


def obj(properties: dict, required: list[str] | None = None) -> dict:
    """A strict JSON-schema object: every property required, no extras."""
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }
