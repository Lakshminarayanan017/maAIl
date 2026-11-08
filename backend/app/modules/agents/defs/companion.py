"""The companion: route it cheaply, run it if you must, check what it said.

Three stages, and the middle one is the expensive one, so it is reached
last:

**Route.** The deterministic intent router answers counts, filters and
stored judgements in SQL. Those turns cost nothing and are recorded as
``route = 'sql'`` or ``'cached'``, which is how the tracked number --
share of turns resolved with zero model calls -- becomes measurable
rather than aspirational.

**Run.** What is left goes to the agent, with retrieved context and the
user's own facts in a delimited data block.

**Check.** Every citation is resolved against the message it names, and
an answer whose citations all fail is **not served as an answer**. This
is the phase 10 gate, and it is enforced here rather than in the
interface because only here is the message text available to check
against.

The check is also where user A's facts stay away from user B: the
resolver queries through RLS with the armed tenant, so a message id from
another mailbox resolves to nothing. A model asked to cite someone
else's mail cannot, because the lookup comes back empty.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.agents.runtime import RunOutcome, run_agent
from app.modules.agents.runtime.spec import AgentSpec
from app.modules.harness import budget as budget_manager
from app.modules.harness.evidence import load_resolver_for_messages
from app.modules.harness.planner import Decision, IntelligenceRequest, Tier, plan
from app.modules.mcp.client_manager import ClientHost
from app.modules.providers.llm.base import LLMProvider
from app.modules.retrieval.intent_router import RoutedAnswer, ThreadRef, route_question

log = get_logger(__name__)

AGENT_ID = "companion"
FEATURE_ID = "ai_companion"

#: How many earlier turns go into the prompt. Beyond this the Context
#: Builder summarises rather than truncating, because dropping the middle
#: of a conversation makes the model contradict itself.
HISTORY_TURNS = 8
#: Retrieved passages. More than this and the prompt is a search results
#: page, which is not what the user asked for.
RETRIEVED = 6


@dataclass
class TurnResult:
    answer: str
    #: 'sql' | 'cached' | 'model'
    route: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    run_id: UUID | None = None
    cost_micros: int = 0
    #: Citations the model offered that did not resolve. Surfaced rather
    #: than hidden: a model that keeps citing nothing is a problem worth
    #: seeing, and the number is the only way to see it.
    dropped_citations: int = 0

    @property
    def costs_nothing(self) -> bool:
        return self.route in ("sql", "cached")


_RECENT_TURNS = text(
    """
    SELECT role, content FROM chat_messages
     WHERE conversation_id = :conversation_id
     ORDER BY created_at DESC
     LIMIT :limit
    """
)

_SEARCH = text(
    """
    SELECT m.id, m.thread_id, t.subject, m.from_email, m.sent_at,
           m.body_text_stripped,
           ts_rank(
             to_tsvector('english', coalesce(m.body_text_stripped, m.snippet, '')),
             websearch_to_tsquery('english', :q)
           ) AS rank
      FROM email_messages m
      JOIN email_threads t ON t.id = m.thread_id
     WHERE m.deleted_at IS NULL
       AND to_tsvector('english', coalesce(m.body_text_stripped, m.snippet, ''))
           @@ websearch_to_tsquery('english', :q)
     ORDER BY rank DESC, m.sent_at DESC
     LIMIT :limit
    """
)

_THREAD_MESSAGES = text(
    """
    SELECT m.id, m.thread_id, t.subject, m.from_email, m.sent_at, m.body_text_stripped
      FROM email_messages m
      JOIN email_threads t ON t.id = m.thread_id
     WHERE m.thread_id = :thread_id AND m.deleted_at IS NULL
     ORDER BY m.sent_at
     LIMIT 20
    """
)

_FACTS_BLOCK = text(
    """
    SELECT content, confirmation_status, confidence_band
      FROM semantic_facts
     WHERE deleted_at IS NULL AND superseded_by IS NULL
       AND confirmation_status <> 'user_rejected'
       AND (expires_at IS NULL OR expires_at > now())
     ORDER BY (confirmation_status = 'user_confirmed') DESC, observation_count DESC
     LIMIT 15
    """
)


async def answer_turn(
    session: AsyncSession,
    *,
    spec: AgentSpec,
    provider: LLMProvider,
    host: ClientHost,
    user_id: UUID,
    conversation_id: UUID,
    question: str,
    thread_id: UUID | None = None,
) -> TurnResult:
    """One conversational turn, by the cheapest route that can answer it."""
    # Stage one. A thread-scoped question is about one thread and the
    # generic router's mailbox-wide answers would be wrong for it, so
    # routing is skipped there.
    if thread_id is None:
        routed = await route_question(session, question)
        if routed is not None:
            log.info("companion.routed", route=routed.route)
            return _from_routed(routed)

    request = IntelligenceRequest(
        user_id=user_id,
        feature_id=FEATURE_ID,
        agent_id=spec.id,
        agent_version=spec.version,
        prompt_version=spec.prompt_version,
        model_id=provider.model_id,
        config_hash=spec.config_hash(),
        thread_id=thread_id,
        content_version=0,
        tier=Tier.large,
        #: A person is waiting for this, so it is never bypassed.
        user_initiated=True,
    )
    decision = await plan(session, request)
    if decision.decision is Decision.skip:
        return TurnResult(
            answer=(
                "I have reached this month's analysis budget, so I cannot work "
                "anything new out right now. Counts and stored results still work."
                if "budget" in decision.reason
                else "The companion is turned off in your settings."
            ),
            route="sql",
        )

    prompt, cited_messages = await _build_prompt(
        session,
        spec=spec,
        user_id=user_id,
        conversation_id=conversation_id,
        question=question,
        thread_id=thread_id,
    )

    result = await run_agent(
        session,
        spec=spec,
        provider=provider,
        host=host,
        user_id=user_id,
        user_prompt=prompt,
        trigger="user_requested",
        subject_type="conversation",
        subject_id=conversation_id,
    )
    await budget_manager.spend(session, user_id, result.cost_micros)

    if result.outcome is not RunOutcome.succeeded or result.output is None:
        # A cap is a recorded terminal state, not an error, and the user
        # is told which one in their own terms. ``stopped_because`` names
        # the budget; the reader does not need to know its variable name.
        if result.outcome is RunOutcome.cap_exceeded:
            because = result.stopped_because or ""
            reason = (
                "This took more steps than it is allowed."
                if "max_steps" in because
                else "This needed more context than it is allowed."
                if "max_tokens" in because
                else "This took too long."
            )
        else:
            reason = "Something went wrong working that out."
        return TurnResult(
            answer=f"{reason} Try asking for something narrower.",
            route="model",
            run_id=result.run_id,
            cost_micros=result.cost_micros,
        )

    return await _validated(
        session,
        output=result.output,
        candidate_messages=cited_messages,
        run_id=result.run_id,
        cost_micros=result.cost_micros,
    )


# ---------------------------------------------------------------------------
async def _build_prompt(
    session: AsyncSession,
    *,
    spec: AgentSpec,
    user_id: UUID,
    conversation_id: UUID,
    question: str,
    thread_id: UUID | None,
) -> tuple[str, list[UUID]]:
    """Stable first, volatile last, so prefix caching has something to hit.

    Order: system prompt, then the user's facts, then the conversation so
    far, then the retrieved mail, then the question. The question moves
    every turn and so it goes at the end; the facts barely move and so
    they go near the front (gap B5).
    """
    facts = (await session.execute(_FACTS_BLOCK)).all()
    if facts:
        lines = [
            "  [{}] {}".format(
                "confirmed" if row[1] == "user_confirmed" else f"inferred, {row[2]}",
                row[0],
            )
            for row in facts
        ]
        # A delimited data block, not prose in the system prompt. Facts
        # are things the model reads about the user, never instructions it
        # follows (05-memory.md §2, defence 3).
        facts_block = (
            '<user_facts source="maail_semantic_memory">\n' + "\n".join(lines) + "\n</user_facts>"
        )
    else:
        facts_block = ""

    history_rows = (
        await session.execute(
            _RECENT_TURNS,
            {"conversation_id": str(conversation_id), "limit": HISTORY_TURNS},
        )
    ).all()
    history = "\n".join(f"{row[0]}: {row[1]}" for row in reversed(list(history_rows)))

    if thread_id is not None:
        rows = (await session.execute(_THREAD_MESSAGES, {"thread_id": str(thread_id)})).all()
    else:
        rows = (
            await session.execute(_SEARCH, {"q": _as_query(question), "limit": RETRIEVED})
        ).all()

    from app.modules.harness.context_builder import BODY_MARKER

    blocks: list[str] = []
    message_ids: list[UUID] = []
    for row in rows:
        body = str(row[5] or "")
        if not body:
            continue
        message_ids.append(row[0])
        stamp = row[4].strftime("%Y-%m-%d %H:%M") if row[4] else ""
        blocks.append(
            f"Message: {row[0]}\n"
            f"From: {row[3]}\n"
            f"Date: {stamp}\n"
            f"Subject: {row[2]}\n"
            f"{BODY_MARKER}\n{body[:4000]}"
        )

    retrieved = (
        "<retrieved_mail>\n" + "\n\n---\n\n".join(blocks) + "\n</retrieved_mail>"
        if blocks
        else "<retrieved_mail>(nothing matched)</retrieved_mail>"
    )

    parts = [
        spec.system_prompt,
        facts_block,
        f"<conversation_so_far>\n{history}\n</conversation_so_far>" if history else "",
        retrieved,
        f"The user asks: {question}",
    ]
    return "\n\n".join(part for part in parts if part), message_ids


def _as_query(question: str) -> str:
    """The question as a search query, with the question words removed.

    ``websearch_to_tsquery`` handles quoting and OR, but "what did my
    teammate say about the API" ranks on "what" and "say" unless the
    stopwords that are not stopwords in English configuration go first.
    """
    import re

    noise = {
        "what",
        "which",
        "when",
        "where",
        "who",
        "whom",
        "whose",
        "why",
        "how",
        "did",
        "does",
        "do",
        "is",
        "are",
        "was",
        "were",
        "my",
        "me",
        "mine",
        "the",
        "a",
        "an",
        "about",
        "from",
        "any",
        "anything",
        "tell",
        "show",
        "find",
        "say",
        "said",
        "please",
        "email",
        "emails",
        "mail",
    }
    words = [
        word
        for word in re.findall(r"[\w']+", question.lower())
        if len(word) > 2 and word not in noise
    ]
    return " or ".join(words[:8]) if words else question[:100]


async def _validated(
    session: AsyncSession,
    *,
    output: dict[str, Any],
    candidate_messages: list[UUID],
    run_id: UUID,
    cost_micros: int,
) -> TurnResult:
    """Resolve every citation. Refuse the answer if none of them hold."""
    raw_citations = output.get("citations") or []

    claimed_ids: list[UUID] = []
    for raw in raw_citations if isinstance(raw_citations, list) else []:
        if not isinstance(raw, dict):
            continue
        try:
            claimed_ids.append(UUID(str(raw.get("message_id", ""))))
        except (ValueError, TypeError):
            continue

    # Resolved against the messages the model claims, not against what it
    # was shown. An id it was never given still has to be checked -- it
    # may be a thread the user asked about last turn -- and RLS is what
    # makes the check safe.
    resolver = await load_resolver_for_messages(session, list({*claimed_ids, *candidate_messages}))
    resolved = resolver.resolve_all(raw_citations)
    dropped = len(claimed_ids) - len(resolved)

    answer = str(output.get("answer") or "").strip()

    if claimed_ids and not resolved:
        # Every citation failed. The answer is about email content and
        # nothing in it can be checked, so it is not served.
        log.warning("companion.all_citations_failed", run_id=str(run_id))
        return TurnResult(
            answer=(
                "I worked something out but could not tie any of it back to "
                "your actual messages, so I would rather not state it. Try "
                "asking about a specific thread."
            ),
            route="model",
            run_id=run_id,
            cost_micros=cost_micros,
            dropped_citations=dropped,
        )

    follow_ups = [
        str(item)[:120] for item in (output.get("follow_ups") or []) if str(item).strip()
    ][:3]

    return TurnResult(
        answer=answer or "I did not find anything to answer that from.",
        route="model",
        citations=[span.as_dict() for span in resolved],
        follow_ups=follow_ups,
        run_id=run_id,
        cost_micros=cost_micros,
        dropped_citations=dropped,
    )


def _from_routed(routed: RoutedAnswer) -> TurnResult:
    return TurnResult(
        answer=routed.answer,
        route=routed.route,
        citations=routed.citations,
        references=[_ref_dict(ref) for ref in routed.references],
        follow_ups=routed.follow_ups,
    )


def _ref_dict(ref: ThreadRef) -> dict[str, Any]:
    return {
        "thread_id": str(ref.thread_id),
        "subject": ref.subject,
        "sender": ref.sender,
        "detail": ref.detail,
    }


_STORE_TURN = text(
    """
    INSERT INTO chat_messages
        (conversation_id, user_id, role, content, citations, route, cost_micros, run_id)
    VALUES (:conversation_id, :user_id, :role, :content, CAST(:citations AS jsonb),
            :route, :cost_micros, :run_id)
    RETURNING id
    """
)


async def store_turn(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    user_id: UUID,
    role: str,
    content: str,
    citations: list[dict[str, Any]] | None = None,
    route: str | None = None,
    cost_micros: int = 0,
    run_id: UUID | None = None,
) -> UUID:
    """Write one turn. Only validated citations reach this."""
    message_id = await session.scalar(
        _STORE_TURN,
        {
            "conversation_id": str(conversation_id),
            "user_id": str(user_id),
            "role": role,
            "content": content,
            "citations": json.dumps(citations) if citations else None,
            "route": route,
            "cost_micros": cost_micros,
            "run_id": str(run_id) if run_id else None,
        },
    )
    await session.execute(
        text("UPDATE chat_conversations SET updated_at = now() WHERE id = :id"),
        {"id": str(conversation_id)},
    )
    return UUID(str(message_id))
