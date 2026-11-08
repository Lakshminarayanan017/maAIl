"""The result cache, keyed on everything that can change the answer.

Nine components, because eight is a cache that serves a stale answer after
someone edits a prompt:

    user_id          whose data
    thread_id        which conversation
    content_version  bumped by every ingested message
    feature_id       the capability being asked for
    agent_id         which agent
    agent_version    its manifest version
    prompt_version   its prompt version
    model_id         which model
    config_hash      temperature, max tokens, anything else that steers it

Leave out ``prompt_version`` and a prompt fix serves the old answer for ever.
Leave out ``content_version`` and a reply never changes the summary. Each
one is in here because its absence is a specific, silent bug.

The stored row is a **pointer** to the real result, never a copy. Two copies
of a summary is two things to invalidate.

See docs/architecture/07-harness.md §4.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["CacheKey", "lookup", "record"]


@dataclass(frozen=True)
class CacheKey:
    user_id: UUID
    thread_id: UUID | None
    content_version: int
    feature_id: str
    agent_id: str
    agent_version: str
    prompt_version: str
    model_id: str
    config_hash: str

    def digest(self) -> str:
        """sha256 over the nine parts, in a fixed order.

        JSON with sorted keys rather than string concatenation: joining
        with a separator makes ``("a", "bc")`` and ``("ab", "c")`` collide,
        which is a cache poisoning bug waiting for the right pair of ids.
        """
        material = json.dumps(
            {k: (str(v) if isinstance(v, UUID) else v) for k, v in asdict(self).items()},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


_LOOKUP = text(
    """
    UPDATE intelligence_cache
       SET hit_count = hit_count + 1, last_hit_at = now()
     WHERE cache_key = :key
    RETURNING result_ref
    """
)

_RECORD = text(
    """
    INSERT INTO intelligence_cache (cache_key, user_id, thread_id, agent_id, result_ref)
    VALUES (:key, :user_id, :thread_id, :agent_id, :result_ref)
    ON CONFLICT (cache_key) DO UPDATE SET result_ref = excluded.result_ref
    """
)


async def lookup(session: AsyncSession, key: CacheKey) -> dict[str, Any] | None:
    """A pointer to a previous result, or None. Counts the hit."""
    row = (await session.execute(_LOOKUP, {"key": key.digest()})).one_or_none()
    return dict(row[0]) if row else None


async def record(session: AsyncSession, key: CacheKey, result_ref: dict[str, Any]) -> None:
    """Remember where the answer lives, not what it said."""
    await session.execute(
        _RECORD,
        {
            "key": key.digest(),
            "user_id": str(key.user_id),
            "thread_id": str(key.thread_id) if key.thread_id else None,
            "agent_id": key.agent_id,
            "result_ref": json.dumps(result_ref),
        },
    )
