"""Screen 06: conversations, turns, and the stream.

``POST /companion/conversations/{id}/ask`` streams. Three event types:

``route``   which path answered, as soon as that is known. The user sees
            "answered from your stored results" before any text arrives,
            which is both honest and faster than a spinner.
``delta``   the answer, in pieces.
``done``    the stored turn, with its validated citations.

One honest limitation, stated rather than hidden: the **transport**
streams and the **provider** does not. The stub completes and then this
emits the answer in pieces, so the shape of the client code is right and
a real streaming provider drops in behind it without the frontend
changing. What a reader sees today is paced playback, not generation.

The stream runs its own session rather than the request's, because a
``StreamingResponse`` outlives the dependency scope: the request
transaction is long gone by the time the second chunk goes out, and
writing a turn on a closed session is the kind of bug that only appears
under a slow network.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import AuthContext, require_csrf
from app.core.logging import get_logger
from app.core.tenancy import tenant_session
from app.modules.agents.defs import companion as companion_service
from app.modules.mcp import bootstrap
from app.modules.providers.llm.factory import provider_for

router = APIRouter(prefix="/companion", tags=["companion"])
log = get_logger(__name__)

#: The suggested prompts, exactly as specified (08-ui-spec.md, screen 06).
SUGGESTED_PROMPTS = (
    "Find pending internship emails",
    "What did my teammate say about the API?",
    "Summarize my technical conversations",
    "Draft a response to the recruiter",
    "Which emails need my attention?",
)

#: Paced playback of a completed answer. Small enough to look alive,
#: large enough not to flood a slow connection with frames.
CHUNK_WORDS = 6
CHUNK_DELAY_S = 0.03


class ConversationOut(BaseModel):
    id: UUID
    title: str | None
    thread_id: UUID | None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class TurnOut(BaseModel):
    id: UUID
    role: str
    content: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    route: str | None = None
    created_at: datetime


class ConversationDetail(BaseModel):
    conversation: ConversationOut
    turns: list[TurnOut] = Field(default_factory=list)
    suggested_prompts: list[str] = Field(default_factory=lambda: list(SUGGESTED_PROMPTS))


class NewConversation(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    #: Set when the chat is scoped to one thread, which is what the
    #: contextual panel opens.
    thread_id: UUID | None = None


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    #: Re-answer the previous question instead of adding a new one.
    regenerate: bool = False


_LIST = text(
    """
    SELECT c.id, c.title, c.thread_id, c.created_at, c.updated_at,
           (SELECT count(*) FROM chat_messages m WHERE m.conversation_id = c.id)
      FROM chat_conversations c
     ORDER BY c.updated_at DESC
     LIMIT 50
    """
)

_ONE = text(
    """
    SELECT c.id, c.title, c.thread_id, c.created_at, c.updated_at,
           (SELECT count(*) FROM chat_messages m WHERE m.conversation_id = c.id)
      FROM chat_conversations c
     WHERE c.id = :id
    """
)

_TURNS = text(
    """
    SELECT id, role, content, citations, route, created_at
      FROM chat_messages
     WHERE conversation_id = :id
     ORDER BY created_at
     LIMIT 200
    """
)


def _conversation(row: object) -> ConversationOut:
    data: tuple[Any, ...] = tuple(row)  # type: ignore[arg-type]
    return ConversationOut(
        id=data[0],
        title=data[1],
        thread_id=data[2],
        created_at=data[3],
        updated_at=data[4],
        message_count=int(data[5] or 0),
    )


@router.get("/conversations", response_model=list[ConversationOut], summary="Recent chats")
async def list_conversations(auth: AuthContext) -> list[ConversationOut]:
    rows = (await auth.session.execute(_LIST)).all()
    return [_conversation(row) for row in rows]


@router.post(
    "/conversations",
    response_model=ConversationDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
    summary="New chat",
)
async def create_conversation(body: NewConversation, auth: AuthContext) -> ConversationDetail:
    conversation_id = await auth.session.scalar(
        text(
            """
            INSERT INTO chat_conversations (user_id, title, thread_id)
            VALUES (:user_id, :title, :thread_id)
            RETURNING id
            """
        ),
        {
            "user_id": str(auth.user_id),
            "title": body.title,
            "thread_id": str(body.thread_id) if body.thread_id else None,
        },
    )
    return await read_conversation(UUID(str(conversation_id)), auth)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
    summary="One chat with its turns",
)
async def read_conversation(conversation_id: UUID, auth: AuthContext) -> ConversationDetail:
    row = (await auth.session.execute(_ONE, {"id": str(conversation_id)})).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such conversation")

    turns = [
        TurnOut(
            id=turn[0],
            role=str(turn[1]),
            content=str(turn[2]),
            citations=list(turn[3] or []),
            route=turn[4],
            created_at=turn[5],
        )
        for turn in (await auth.session.execute(_TURNS, {"id": str(conversation_id)})).all()
    ]
    return ConversationDetail(conversation=_conversation(row), turns=turns)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
    summary="Delete a chat",
)
async def delete_conversation(conversation_id: UUID, auth: AuthContext) -> None:
    await auth.session.execute(
        text("DELETE FROM chat_conversations WHERE id = :id"),
        {"id": str(conversation_id)},
    )


@router.post(
    "/conversations/{conversation_id}/ask",
    dependencies=[Depends(require_csrf)],
    summary="Ask a question (SSE)",
)
async def ask(conversation_id: UUID, body: Ask, auth: AuthContext) -> StreamingResponse:
    """Answer one question, streaming the result."""
    row = (await auth.session.execute(_ONE, {"id": str(conversation_id)})).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such conversation")

    runtime = bootstrap.runtime()
    spec = runtime.agents.get(companion_service.AGENT_ID)
    if spec is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The companion agent is not loaded"
        )

    user_id = auth.user_id
    thread_id: UUID | None = row[2]
    question = body.question.strip()
    had_turns = int(row[5] or 0) > 0

    async def events() -> AsyncIterator[str]:
        # Its own tenant session: this generator runs after the request's
        # transaction has closed.
        try:
            async with tenant_session(user_id) as session:
                if body.regenerate:
                    # Drop the last assistant turn so the conversation does
                    # not end up with two answers to one question.
                    await session.execute(
                        text(
                            """
                            DELETE FROM chat_messages
                             WHERE id = (
                               SELECT id FROM chat_messages
                                WHERE conversation_id = :id AND role = 'assistant'
                                ORDER BY created_at DESC LIMIT 1
                             )
                            """
                        ),
                        {"id": str(conversation_id)},
                    )
                else:
                    await companion_service.store_turn(
                        session,
                        conversation_id=conversation_id,
                        user_id=user_id,
                        role="user",
                        content=question,
                    )

                    if not had_turns:
                        # Name the chat from its first question, so the
                        # sidebar reads like a list of topics.
                        await session.execute(
                            text(
                                "UPDATE chat_conversations SET title = :title "
                                " WHERE id = :id AND title IS NULL"
                            ),
                            {"id": str(conversation_id), "title": question[:60]},
                        )

                result = await companion_service.answer_turn(
                    session,
                    spec=spec,
                    provider=provider_for(spec.tier),
                    host=runtime.host,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    question=question,
                    thread_id=thread_id,
                )

                yield _frame(
                    "route",
                    {
                        "route": result.route,
                        "costs_nothing": result.costs_nothing,
                        # What the user is told about it. "Answered from
                        # your stored results" is a different claim from
                        # "worked out just now", and they should know
                        # which they got.
                        "label": {
                            "sql": "Answered from your mailbox directly",
                            "cached": "Answered from results already stored",
                            "model": "Worked out just now",
                        }.get(result.route, result.route),
                    },
                )

                words = result.answer.split(" ")
                for index in range(0, len(words), CHUNK_WORDS):
                    piece = " ".join(words[index : index + CHUNK_WORDS])
                    yield _frame("delta", {"text": piece + " "})
                    await asyncio.sleep(CHUNK_DELAY_S)

                turn_id = await companion_service.store_turn(
                    session,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    role="assistant",
                    content=result.answer,
                    citations=result.citations,
                    route=result.route,
                    cost_micros=result.cost_micros,
                    run_id=result.run_id,
                )

                yield _frame(
                    "done",
                    {
                        "turn_id": str(turn_id),
                        "answer": result.answer,
                        "citations": result.citations,
                        "references": result.references,
                        "follow_ups": result.follow_ups,
                        "route": result.route,
                        "cost_micros": result.cost_micros,
                        "dropped_citations": result.dropped_citations,
                    },
                )
        except Exception:
            # The client is mid-stream, so an exception here would look
            # like the connection dropping. Say what happened instead.
            log.exception("companion.stream_failed", conversation=str(conversation_id))
            yield _frame("failed", {"message": "Something went wrong answering that."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _frame(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"
