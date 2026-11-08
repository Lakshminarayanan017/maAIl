"""One place that decides which model provider answers.

Phases 8 to 10 add four more call sites that need a provider, and six
copies of ``StubProvider(tier=...)`` would be six places to change when a
real key arrives -- and six chances to miss one, which is how a stub ends
up serving one screen in production while the rest are real.

The tier comes from the agent's own manifest, not from the caller. An
agent that declared ``tier: small`` does not get a large model because
the endpoint invoking it felt generous; tiering is the cost architecture
and it belongs to the agent.
"""

from __future__ import annotations

import os

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.providers.llm.base import LLMProvider, ModelTier
from app.modules.providers.llm.stub import StubProvider

log = get_logger(__name__)

__all__ = ["get_provider", "provider_for"]

#: Read from the environment rather than from settings, so that adding a
#: real provider later is a new module plus one branch here, with no
#: change to the settings schema that every test constructs.
API_KEY_ENV = "ANTHROPIC_API_KEY"


def get_provider(tier: ModelTier = ModelTier.small) -> LLMProvider:
    """The provider for one tier.

    With no key configured this is the extractive stub, which is a real
    implementation of the Protocol and visibly not intelligence. In
    production it is a hard failure instead: a stub quietly serving real
    users is worse than a missing key, because its output looks like an
    answer.
    """
    key = os.environ.get(API_KEY_ENV, "").strip()

    if not key:
        if settings.is_production:
            raise RuntimeError(
                f"no model provider is configured; set {API_KEY_ENV} "
                "(the stub provider must never serve production traffic)"
            )
        return StubProvider(tier=tier)

    # The real client lands here. Until then, say so loudly rather than
    # silently ignoring a key someone has gone to the trouble of setting.
    raise RuntimeError(
        f"{API_KEY_ENV} is set but no real provider is wired up yet; "
        "unset it to use the development stub"
    )


def provider_for(tier: str | ModelTier) -> LLMProvider:
    """Convenience for callers holding an ``AgentSpec.tier``."""
    return get_provider(ModelTier(tier) if isinstance(tier, str) else tier)
