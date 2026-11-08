"""The LLM provider contract, and the three tiers.

Three tiers rather than one model, because the cost architecture depends on
routing: a cheap model decides what an expensive model looks at, and the
expensive one is reached only when the cheap one says so. A codebase with
one hard-coded model has no way to express that.

Costs are in **micros** (millionths of a currency unit) as integers.
Floating-point money accumulates error, and a budget that drifts is a
budget nobody trusts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

__all__ = [
    "Completion",
    "LLMError",
    "LLMProvider",
    "ModelTier",
    "Prompt",
    "ToolCall",
    "price_micros",
]


class LLMError(Exception):
    """The provider failed. Retryable or not is the caller's decision."""


class ModelTier(str, Enum):
    small = "small"
    large = "large"


@dataclass(frozen=True)
class Prompt:
    """Ordered for prefix caching: stable first, volatile last (gap B5)."""

    system: str
    user: str
    #: JSON Schema the output must satisfy. Enforced by the runtime, not
    #: hoped for: an agent without an output schema is an agent whose
    #: failures look like content.
    output_schema: dict[str, Any] | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    max_output_tokens: int = 1024
    temperature: float = 0.0


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str = ""


@dataclass(frozen=True)
class Completion:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0
    #: Tokens served from the provider's prefix cache. Tracked separately
    #: because they are the measure of whether prompt ordering is working.
    cached_input_tokens: int = 0
    model: str = ""
    stop_reason: str = ""

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


#: Price per million tokens, in micros. One place to correct.
PRICING: dict[str, tuple[int, int]] = {
    "stub": (0, 0),
}


def price_micros(model: str, *, input_tokens: int, output_tokens: int) -> int:
    """What a call cost, in micros. Unknown models price at zero and log."""
    rates = PRICING.get(model)
    if rates is None:
        return 0
    input_rate, output_rate = rates
    return (input_tokens * input_rate + output_tokens * output_rate) // 1_000_000


class LLMProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def tier(self) -> ModelTier: ...

    async def complete(self, prompt: Prompt) -> Completion: ...
