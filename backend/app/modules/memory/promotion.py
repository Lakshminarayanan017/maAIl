"""Promote a proposal to a fact, or reject it. Deterministic, no model.

Agents propose; this decides. The decision is code because the thing it
is defending against is a model being persuaded, and asking a model
whether it has been persuaded does not help.

Four layers, in order, and the first two are structural:

**1. The enum.** ``fact_type`` has four values and none of them describes
agent behaviour. A proposal naming anything else is rejected before its
content is read. This is the primary defence and it cannot be argued with
(05-memory.md §2).

**2. Evidence required.** A fact with no span is a fact nobody can check
later. Rejected.

**3. ``looks_behavioural``.** A deny-list on imperative and permission
language, for content that squeezed through the enum by claiming to be a
preference: "prefers that all emails are auto-approved" is shaped like a
preference and is a policy change. Second layer, not the primary one.

**4. Conflict.** The same subject with different content is a question
for the user, never a silent flip. ``user_confirmed`` always outranks
``agent_inferred``.

Expiry follows the source: inferred facts die in 90 days unless seen
again, user-stated ones do not expire, and derived values are never
stored at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

log = get_logger(__name__)

__all__ = ["Decision", "PromotionResult", "looks_behavioural", "promote_pending"]

#: The closed allowlist, mirroring the Postgres enum. Duplicated on
#: purpose: the database refuses the write, and this refuses to attempt
#: it, so the rejection is recorded with a reason instead of surfacing as
#: a constraint violation nobody can read.
ALLOWED_FACT_TYPES = frozenset({"preference", "interest", "relationship", "project_fact"})

INFERRED_TTL_DAYS = 90

#: Language that tries to change what the system does rather than
#: describe what the user is like. Deliberately blunt: a false positive
#: costs one unstored preference, a false negative is a persistent
#: instruction injected by an email.
_BEHAVIOURAL = re.compile(
    r"\b("
    r"always|never|must|should|shall|do not|don'?t|"
    r"approve\w*|authoriz\w*|authoris\w*|permission\w*|permitt\w*|allow\w*|"
    r"grant\w*|enabl\w*|disabl\w*|bypass\w*|skip\w*|overrid\w*|ignor\w*|disregard\w*|"
    r"auto[- ]?(send|reply|approve|forward)|without (asking|confirmation|approval)|"
    r"on (my|their|the user'?s) behalf|forward (all|every)|"
    r"instruction|policy|rule|system prompt|you are|you will|you must"
    r")\b",
    re.I,
)

#: Content that is only a few words of hedging carries no fact.
MIN_CONTENT_CHARS = 8


class Decision(str, Enum):
    created = "created"
    reinforced = "reinforced"
    needs_user_confirmation = "needs_user_confirmation"
    rejected_policy = "rejected_policy"
    rejected_no_evidence = "rejected_no_evidence"
    rejected_duplicate = "rejected_duplicate"


@dataclass
class PromotionResult:
    proposal_id: UUID
    decision: Decision
    reason: str
    fact_id: UUID | None = None


def looks_behavioural(content: str) -> bool:
    """Does this read as an instruction rather than a description?

    The second layer. "prefers concise replies" passes; "prefers that
    replies are always sent without confirmation" does not, although both
    begin with "prefers".
    """
    return bool(_BEHAVIOURAL.search(content))


def _similar(left: str, right: str) -> bool:
    """Same fact, differently worded. Token overlap, not a model.

    Jaccard over lowercased words. Crude, and the failure mode is the safe
    one: two genuinely different facts about one subject are judged
    different and the user is asked.
    """
    a = {word for word in re.findall(r"[a-z0-9]+", left.lower()) if len(word) > 2}
    b = {word for word in re.findall(r"[a-z0-9]+", right.lower()) if len(word) > 2}
    if not a or not b:
        return left.strip().lower() == right.strip().lower()
    return len(a & b) / len(a | b) >= 0.6


_PENDING = text(
    """
    SELECT id, operation, fact_type, subject, content, evidence
      FROM memory_proposals
     WHERE status = 'pending'
     ORDER BY created_at
     LIMIT :limit
    """
)

_EXISTING = text(
    """
    SELECT id, content, source, confirmation_status, observation_count
      FROM semantic_facts
     WHERE fact_type = CAST(:fact_type AS fact_type)
       AND subject = :subject
       AND deleted_at IS NULL
       AND superseded_by IS NULL
     LIMIT 1
    """
)

_SETTLE = text(
    """
    UPDATE memory_proposals
       SET status = :status, rejection_reason = :reason
     WHERE id = :id
    """
)

_CREATE = text(
    """
    INSERT INTO semantic_facts
        (user_id, fact_type, subject, content, source,
         source_thread_id, source_message_id, evidence_char_start, evidence_char_end,
         confidence_band, expires_at)
    VALUES (:user_id, CAST(:fact_type AS fact_type), :subject, :content, 'agent_inferred',
            :thread_id, :message_id, :char_start, :char_end,
            :confidence, now() + make_interval(days => :ttl))
    RETURNING id
    """
)

_REINFORCE = text(
    """
    UPDATE semantic_facts
       SET observation_count = observation_count + 1,
           last_confirmed_at = now(),
           expires_at = CASE
             WHEN source = 'agent_inferred' THEN now() + make_interval(days => :ttl)
             ELSE expires_at
           END
     WHERE id = :id
    RETURNING id
    """
)


async def promote_pending(
    session: AsyncSession, *, user_id: UUID, limit: int = 50
) -> list[PromotionResult]:
    """Settle every pending proposal. Returns what happened to each."""
    rows = (await session.execute(_PENDING, {"limit": limit})).all()
    results: list[PromotionResult] = []

    for row in rows:
        proposal_id = UUID(str(row[0]))
        fact_type = str(row[2])
        subject = str(row[3]).strip()
        content = str(row[4]).strip()
        evidence = row[5] or []

        result = await _promote_one(
            session,
            user_id=user_id,
            proposal_id=proposal_id,
            fact_type=fact_type,
            subject=subject,
            content=content,
            evidence=evidence,
        )
        await session.execute(
            _SETTLE,
            {
                "id": str(proposal_id),
                "status": _stored_status(result.decision),
                "reason": result.reason,
            },
        )
        results.append(result)

    return results


async def _promote_one(
    session: AsyncSession,
    *,
    user_id: UUID,
    proposal_id: UUID,
    fact_type: str,
    subject: str,
    content: str,
    evidence: Any,
) -> PromotionResult:
    # Layer 1. Before the content is even looked at.
    if fact_type not in ALLOWED_FACT_TYPES:
        log.warning(
            "memory.rejected_fact_type",
            fact_type=fact_type,
            subject=subject[:40],
        )
        return PromotionResult(
            proposal_id,
            Decision.rejected_policy,
            f"'{fact_type}' is not a storable kind of fact",
        )

    # Layer 2.
    spans = evidence if isinstance(evidence, list) else []
    first = spans[0] if spans and isinstance(spans[0], dict) else None
    if first is None or not first.get("message_id"):
        return PromotionResult(proposal_id, Decision.rejected_no_evidence, "no message to point at")

    if len(content) < MIN_CONTENT_CHARS or not subject:
        return PromotionResult(
            proposal_id, Decision.rejected_policy, "nothing substantive to store"
        )

    # Layer 3.
    if looks_behavioural(content):
        log.warning("memory.rejected_behavioural", content=content[:80])
        return PromotionResult(
            proposal_id,
            Decision.rejected_policy,
            "reads as an instruction rather than a description of the user",
        )

    # Layer 4.
    existing = (
        await session.execute(_EXISTING, {"fact_type": fact_type, "subject": subject})
    ).first()

    if existing is not None:
        if _similar(str(existing[1]), content):
            reinforced = await session.scalar(
                _REINFORCE, {"id": str(existing[0]), "ttl": INFERRED_TTL_DAYS}
            )
            return PromotionResult(
                proposal_id,
                Decision.reinforced,
                "already known; seen again",
                fact_id=UUID(str(reinforced)) if reinforced else None,
            )
        # A conflict is a question, not a write. Silently replacing what
        # the user confirmed with what an email implied is how memory
        # becomes something they cannot trust.
        return PromotionResult(
            proposal_id,
            Decision.needs_user_confirmation,
            f"conflicts with what is stored: {str(existing[1])[:120]}",
            fact_id=UUID(str(existing[0])),
        )

    fact_id = await session.scalar(
        _CREATE,
        {
            "user_id": str(user_id),
            "fact_type": fact_type,
            "subject": subject[:120],
            "content": content[:300],
            "thread_id": str(first["thread_id"]) if first.get("thread_id") else None,
            "message_id": str(first["message_id"]),
            "char_start": first.get("char_start"),
            "char_end": first.get("char_end"),
            # Never 'high' on first sighting. One observation is one
            # observation, and the band says so until it is seen again.
            "confidence": "low",
            "ttl": INFERRED_TTL_DAYS,
        },
    )
    return PromotionResult(
        proposal_id,
        Decision.created,
        "stored, unconfirmed",
        fact_id=UUID(str(fact_id)) if fact_id else None,
    )


def _stored_status(decision: Decision) -> str:
    return {
        Decision.created: "accepted",
        Decision.reinforced: "accepted",
        Decision.needs_user_confirmation: "needs_user_confirmation",
        Decision.rejected_policy: "rejected_policy",
        Decision.rejected_no_evidence: "rejected_no_evidence",
        Decision.rejected_duplicate: "rejected_duplicate",
    }[decision]
