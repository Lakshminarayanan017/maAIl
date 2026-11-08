"""A provider that answers without a model, for development and tests.

Not a mock: it is a real implementation of the Protocol, selected by
configuration when no API key is set. It lets the whole runtime -- the
planner, the bounded loop, the trace, the budget -- be exercised end to end
before anyone has pasted a key in, which is the difference between phase 5
being demoable and being a diagram.

It refuses to exist in production. A stub that silently serves real users
is worse than a missing key, because the output looks like an answer.
"""

from __future__ import annotations

import hashlib
import json

from app.core.config import settings
from app.modules.providers.llm import extractive
from app.modules.providers.llm.base import Completion, ModelTier, Prompt

MODEL_ID = "stub"


class StubProvider:
    """Deterministic, free, and obviously not intelligence."""

    def __init__(self, tier: ModelTier = ModelTier.small) -> None:
        if settings.is_production:
            raise RuntimeError(
                "the stub LLM provider must never run in production; "
                "set an API key for a real provider"
            )
        self._tier = tier

    @property
    def model_id(self) -> str:
        return MODEL_ID

    @property
    def tier(self) -> ModelTier:
        return self._tier

    async def complete(self, prompt: Prompt) -> Completion:
        # Deterministic from the prompt, so a trace replays identically and
        # a test asserting on output is not asserting on a coin flip.
        material = f"{prompt.system}\n{prompt.user}".encode()
        digest = hashlib.sha256(material).hexdigest()[:12]

        extracted = extractive.answer(prompt.user, prompt.output_schema)
        if extracted is not None:
            # Real sentences from the real email, with offsets that really
            # resolve. Not intelligence -- extraction. See extractive.py
            # for why this is worth more than a digest string: it is what
            # makes the evidence gate test something.
            text = json.dumps(extracted)
        elif prompt.output_schema:
            # An unrecognised schema. Satisfy the required fields with
            # something visibly synthetic, so a stub answer is never
            # mistaken for an answer on screen.
            required = prompt.output_schema.get("required", [])
            properties = prompt.output_schema.get("properties", {})
            payload: dict[str, object] = {}
            for name in required:
                kind = properties.get(name, {}).get("type")
                if kind in ("integer", "number"):
                    payload[name] = 0
                elif kind == "boolean":
                    payload[name] = False
                elif kind == "array":
                    payload[name] = []
                elif kind == "object":
                    payload[name] = {}
                else:
                    payload[name] = f"stub:{digest}"
            text = json.dumps(payload)
        else:
            text = f"stub:{digest}"

        return Completion(
            text=text,
            input_tokens=len(material) // 4,
            output_tokens=len(text) // 4,
            model=MODEL_ID,
            stop_reason="end_turn",
        )
