"""MCP server: search. Read-only, Plane U.

Postgres full-text search over the stripped text, which is what replaces a
vector store in v1. Relevance is better for it as well as cheaper: a quoted
chain repeats last week's words, and ranking against them buries the
message that actually said something.

``websearch_to_tsquery`` rather than ``plainto_tsquery``, because an agent
writing a query will reach for quotes and ``OR`` and should get what it
meant.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.tenancy import tenant_session
from app.modules.mcp.catalog import Capability, Plane, ToolSpec
from app.modules.mcp.transports.inprocess import InProcessServer

server = InProcessServer(name="search")

MAX_RESULTS = 25

_SEARCH = text(
    """
    SELECT t.id, t.subject, t.latest_message_at, t.message_count,
           ts_rank(t.search_tsv, websearch_to_tsquery('english', :q)) AS rank
      FROM email_threads t
     WHERE t.search_tsv @@ websearch_to_tsquery('english', :q)
       AND t.merged_into_thread_id IS NULL
     ORDER BY rank DESC, t.latest_message_at DESC NULLS LAST
     LIMIT :limit
    """
)


@server.tool(
    ToolSpec(
        name="search.threads",
        server="search",
        description=(
            "Full-text search across the user's email threads. Returns matching "
            "threads ranked by relevance, with subjects but no bodies. Read-only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "format": "uuid"},
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS},
            },
            "required": ["user_id", "query"],
            "additionalProperties": False,
        },
        plane=Plane.U,
        capabilities=frozenset({Capability.read}),
    )
)
async def search_threads(args: dict[str, Any]) -> dict[str, Any]:
    user_id = UUID(str(args["user_id"]))
    query = str(args["query"])[:200]
    limit = min(int(args.get("limit", 10)), MAX_RESULTS)

    async with tenant_session(user_id) as session:
        # RLS scopes this to the armed tenant, so the query carries no
        # user_id clause of its own and cannot forget one.
        rows = (await session.execute(_SEARCH, {"q": query, "limit": limit})).all()

    return {
        "query": query,
        "results": [
            {
                "thread_id": str(row[0]),
                "subject": row[1],
                "latest_message_at": row[2].isoformat() if row[2] else None,
                "message_count": int(row[3] or 0),
                "rank": round(float(row[4] or 0.0), 5),
            }
            for row in rows
        ],
    }


_MESSAGES = text(
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


@server.tool(
    ToolSpec(
        name="search.messages",
        server="search",
        description=(
            "Search individual messages and return the matching passage from "
            "each, with the character offsets it was found at. Use this when a "
            "claim needs to be attributable to specific words. Read-only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "format": "uuid"},
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS},
            },
            "required": ["user_id", "query"],
            "additionalProperties": False,
        },
        plane=Plane.U,
        capabilities=frozenset({Capability.read}),
    )
)
async def search_messages(args: dict[str, Any]) -> dict[str, Any]:
    """Returns the span, so the caller never computes one.

    The same principle as the Deadline agent not writing dates: a citation
    whose offsets were produced by code cannot be off by four characters
    because a model counted badly. The passage and its ``char_start`` come
    from the same ``find`` call, so they agree by construction.
    """
    user_id = UUID(str(args["user_id"]))
    query = str(args["query"])[:200]
    limit = min(int(args.get("limit", 8)), MAX_RESULTS)

    async with tenant_session(user_id) as session:
        rows = (await session.execute(_MESSAGES, {"q": query, "limit": limit})).all()

    terms = [word.strip('"').lower() for word in query.split() if len(word.strip('"')) > 2]
    results: list[dict[str, Any]] = []

    for row in rows:
        body = str(row[5] or "")
        lowered = body.lower()
        found = next(
            ((term, lowered.find(term)) for term in terms if lowered.find(term) >= 0),
            None,
        )
        # No locatable term means no quotable passage, so the result says
        # so rather than offering offsets that point at nothing.
        if found is None:
            start, end, passage = 0, 0, ""
        else:
            _, at = found
            start = max(0, at - 120)
            end = min(len(body), at + 180)
            passage = body[start:end]

        results.append(
            {
                "message_id": str(row[0]),
                "thread_id": str(row[1]),
                "subject": row[2],
                "from": row[3],
                "sent_at": row[4].isoformat() if row[4] else None,
                "passage": passage,
                "char_start": start,
                "char_end": end,
                "quotable": bool(passage),
                "rank": round(float(row[6] or 0.0), 5),
            }
        )

    return {"query": query, "results": results}
