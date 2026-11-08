"""The memory inspector: see it, confirm it, reject it, delete it.

> Users must be able to inspect, edit and delete these stored preferences
> and memories. (08-ui-spec.md, screen 10)

So every row comes back with everything needed to judge it: the content,
where it came from, the words it came from, whether it has been confirmed,
and when it expires. A memory the user cannot see the provenance of is a
memory they have to either trust blindly or wipe wholesale.

``rejected`` is kept rather than deleted, and that is deliberate: a
rejected fact is a standing instruction not to re-learn the same thing
next week. Delete removes it and the promoter may then see it again.

The conflicts route is the other half of the promotion rules. When a new
proposal contradicts a stored fact, nothing is written and the two are
shown side by side -- because silently replacing what a user confirmed
with what an email implied is how memory stops being theirs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import AuthContext, require_csrf
from app.core.logging import get_logger
from app.modules.memory.promotion import ALLOWED_FACT_TYPES, looks_behavioural

router = APIRouter(prefix="/memory", tags=["memory"])
log = get_logger(__name__)

FactType = Literal["preference", "interest", "relationship", "project_fact"]


class FactOut(BaseModel):
    id: UUID
    fact_type: str
    subject: str
    content: str
    source: str
    confirmation_status: str
    confidence_band: str
    observation_count: int
    first_seen_at: datetime
    last_confirmed_at: datetime | None
    expires_at: datetime | None
    #: The words it came from, resolved. None when the span no longer
    #: points anywhere -- the message was deleted, or the offsets were
    #: wrong -- and the interface says so rather than showing nothing.
    quote: str | None = None
    source_thread_id: UUID | None = None
    source_message_id: UUID | None = None


class ConflictOut(BaseModel):
    """A proposal that contradicts something stored. The user decides."""

    proposal_id: UUID
    fact_type: str
    subject: str
    proposed_content: str
    stored_fact_id: UUID | None
    stored_content: str | None
    created_at: datetime


class RejectionOut(BaseModel):
    """What the promoter refused, and why. The injection audit trail."""

    id: UUID
    fact_type: str
    subject: str
    content: str
    status: str
    rejection_reason: str | None
    created_at: datetime


class StateFact(BaseModel):
    """A fact the user states about themselves."""

    fact_type: FactType
    subject: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=300)


_FACTS = text(
    """
    SELECT f.id, f.fact_type::text, f.subject, f.content, f.source,
           f.confirmation_status, f.confidence_band, f.observation_count,
           f.first_seen_at, f.last_confirmed_at, f.expires_at,
           f.source_thread_id, f.source_message_id,
           f.evidence_char_start, f.evidence_char_end
      FROM semantic_facts f
     WHERE f.deleted_at IS NULL
       AND f.superseded_by IS NULL
       AND (:include_rejected OR f.confirmation_status <> 'user_rejected')
     ORDER BY (f.confirmation_status = 'user_confirmed') DESC,
              f.fact_type, f.observation_count DESC
     LIMIT 200
    """
)

_CONFLICTS = text(
    """
    SELECT p.id, p.fact_type, p.subject, p.content, p.created_at,
           f.id, f.content
      FROM memory_proposals p
      LEFT JOIN semantic_facts f
        ON f.subject = p.subject
       AND f.fact_type::text = p.fact_type
       AND f.deleted_at IS NULL
       AND f.superseded_by IS NULL
     WHERE p.status = 'needs_user_confirmation'
     ORDER BY p.created_at DESC
     LIMIT 25
    """
)

_REJECTIONS = text(
    """
    SELECT id, fact_type, subject, content, status, rejection_reason, created_at
      FROM memory_proposals
     WHERE status LIKE 'rejected%'
     ORDER BY created_at DESC
     LIMIT 50
    """
)


@router.get("/facts", response_model=list[FactOut], summary="Everything remembered")
async def list_facts(
    auth: AuthContext,
    include_rejected: bool = Query(False),
) -> list[FactOut]:
    from app.modules.harness.evidence import load_resolver_for_messages

    rows = (await auth.session.execute(_FACTS, {"include_rejected": include_rejected})).all()

    message_ids = [row[12] for row in rows if row[12] is not None]
    resolver = await load_resolver_for_messages(auth.session, message_ids)

    out: list[FactOut] = []
    for row in rows:
        span = resolver.resolve({"message_id": row[12], "char_start": row[13], "char_end": row[14]})
        out.append(
            FactOut(
                id=row[0],
                fact_type=str(row[1]),
                subject=str(row[2]),
                content=str(row[3]),
                source=str(row[4]),
                confirmation_status=str(row[5]),
                confidence_band=str(row[6]),
                observation_count=int(row[7] or 1),
                first_seen_at=row[8],
                last_confirmed_at=row[9],
                expires_at=row[10],
                source_thread_id=row[11],
                source_message_id=row[12],
                quote=span.quote if span else None,
            )
        )
    return out


@router.get(
    "/conflicts",
    response_model=list[ConflictOut],
    summary="Proposals that contradict a stored fact",
)
async def list_conflicts(auth: AuthContext) -> list[ConflictOut]:
    rows = (await auth.session.execute(_CONFLICTS)).all()
    return [
        ConflictOut(
            proposal_id=row[0],
            fact_type=str(row[1]),
            subject=str(row[2]),
            proposed_content=str(row[3]),
            created_at=row[4],
            stored_fact_id=row[5],
            stored_content=row[6],
        )
        for row in rows
    ]


@router.get(
    "/rejections",
    response_model=list[RejectionOut],
    summary="What the promoter refused to store",
)
async def list_rejections(auth: AuthContext) -> list[RejectionOut]:
    """Worth a screen of its own.

    A run of ``rejected_policy`` rows all saying "reads as an instruction"
    is an email trying to write itself into the user's memory, and this is
    where that becomes visible instead of vanishing.
    """
    rows = (await auth.session.execute(_REJECTIONS)).all()
    return [
        RejectionOut(
            id=row[0],
            fact_type=str(row[1]),
            subject=str(row[2]),
            content=str(row[3]),
            status=str(row[4]),
            rejection_reason=row[5],
            created_at=row[6],
        )
        for row in rows
    ]


@router.post(
    "/facts/{fact_id}/confirm",
    response_model=FactOut,
    dependencies=[Depends(require_csrf)],
    summary="Confirm a fact",
)
async def confirm_fact(fact_id: UUID, auth: AuthContext) -> FactOut:
    """Confirmed facts never expire and outrank inferred ones on conflict."""
    updated = await auth.session.scalar(
        text(
            """
            UPDATE semantic_facts
               SET confirmation_status = 'user_confirmed',
                   last_confirmed_at = now(),
                   confidence_band = 'high',
                   expires_at = NULL
             WHERE id = :id AND deleted_at IS NULL
            RETURNING id
            """
        ),
        {"id": str(fact_id)},
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such fact")
    return await _one_fact(auth, fact_id)


@router.post(
    "/facts/{fact_id}/reject",
    response_model=FactOut,
    dependencies=[Depends(require_csrf)],
    summary="Reject a fact without forgetting the rejection",
)
async def reject_fact(fact_id: UUID, auth: AuthContext) -> FactOut:
    """Kept, so it is not re-learned next week.

    A rejected fact is excluded from every retrieval, and it is also a
    record that this particular inference was wrong -- which is exactly
    what the promoter needs in order not to make it again.
    """
    updated = await auth.session.scalar(
        text(
            """
            UPDATE semantic_facts
               SET confirmation_status = 'user_rejected', expires_at = NULL
             WHERE id = :id AND deleted_at IS NULL
            RETURNING id
            """
        ),
        {"id": str(fact_id)},
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such fact")
    return await _one_fact(auth, fact_id)


@router.delete(
    "/facts/{fact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
    summary="Forget a fact entirely",
)
async def delete_fact(fact_id: UUID, auth: AuthContext) -> None:
    """Soft delete, and then it really is gone from every read path.

    Soft rather than hard so a cascade from a deleted message cannot take
    the audit trail with it. Nothing reads a deleted row.
    """
    await auth.session.execute(
        text("UPDATE semantic_facts SET deleted_at = now() WHERE id = :id"),
        {"id": str(fact_id)},
    )


@router.post(
    "/conflicts/{proposal_id}/resolve",
    dependencies=[Depends(require_csrf)],
    summary="Keep the stored fact or take the new one",
)
async def resolve_conflict(
    proposal_id: UUID,
    auth: AuthContext,
    keep: Literal["stored", "proposed"] = Query("stored"),
) -> dict[str, str]:
    row = (
        await auth.session.execute(
            text(
                """
                SELECT fact_type, subject, content
                  FROM memory_proposals
                 WHERE id = :id AND status = 'needs_user_confirmation'
                """
            ),
            {"id": str(proposal_id)},
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such open conflict")

    if keep == "proposed":
        # The user chose the new wording, so it is theirs now: stated,
        # confirmed, no expiry. It arrived as an inference and leaves as
        # a decision.
        await auth.session.execute(
            text(
                """
                UPDATE semantic_facts
                   SET content = :content, source = 'user_stated',
                       confirmation_status = 'user_confirmed',
                       confidence_band = 'high', expires_at = NULL,
                       last_confirmed_at = now()
                 WHERE fact_type = CAST(:fact_type AS fact_type)
                   AND subject = :subject
                   AND deleted_at IS NULL AND superseded_by IS NULL
                """
            ),
            {
                "fact_type": str(row[0]),
                "subject": str(row[1]),
                "content": str(row[2]),
            },
        )

    await auth.session.execute(
        text(
            "UPDATE memory_proposals SET status = :status, rejection_reason = :reason "
            " WHERE id = :id"
        ),
        {
            "id": str(proposal_id),
            "status": "accepted" if keep == "proposed" else "rejected_duplicate",
            "reason": f"user kept the {keep} version",
        },
    )
    return {"proposal_id": str(proposal_id), "kept": keep}


@router.post(
    "/facts",
    response_model=FactOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
    summary="State a fact about yourself",
)
async def state_fact(body: StateFact, auth: AuthContext) -> FactOut:
    """The user's own words, stored directly. Still checked.

    The behavioural check applies here too, and that is not distrust of
    the user: this endpoint is reachable from a chat message, and a chat
    message can quote an email. The enum and the deny-list are about what
    can be *stored*, not about who is asking.
    """
    if body.fact_type not in ALLOWED_FACT_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Not a storable kind of fact")
    if looks_behavioural(body.content):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Memory stores what you are like, not instructions. "
            "Use settings to change what Maail does.",
        )

    fact_id = await auth.session.scalar(
        text(
            """
            INSERT INTO semantic_facts
                (user_id, fact_type, subject, content, source,
                 confirmation_status, confidence_band, last_confirmed_at)
            VALUES (:user_id, CAST(:fact_type AS fact_type), :subject, :content,
                    'user_stated', 'user_confirmed', 'high', now())
            ON CONFLICT (user_id, fact_type, subject) DO UPDATE SET
                content = excluded.content,
                source = 'user_stated',
                confirmation_status = 'user_confirmed',
                confidence_band = 'high',
                expires_at = NULL,
                last_confirmed_at = now()
            RETURNING id
            """
        ),
        {
            "user_id": str(auth.user_id),
            "fact_type": body.fact_type,
            "subject": body.subject,
            "content": body.content,
        },
    )
    return await _one_fact(auth, UUID(str(fact_id)))


async def _one_fact(auth: AuthContext, fact_id: UUID) -> FactOut:
    facts = await list_facts(auth, include_rejected=True)
    found = next((fact for fact in facts if fact.id == fact_id), None)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such fact")
    return found
