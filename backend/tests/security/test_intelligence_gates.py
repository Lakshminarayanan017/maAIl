"""The phase 8 and 9 blocking gates. Short.

Phase 8: every AI value resolves to a real evidence span · a value with no
evidence is not offered as a value · no model call to re-open a thread
whose summary is current.

Phase 9: resolved dates are exact and ambiguity is recalled -- correctly
saying "unclear" is a pass, not a miss · stated and inferred are never
conflated · no repeated run for identical content, config and version.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.core.tenancy import tenant_session
from app.database.seed import USER_A
from app.modules.agents.defs import actions as action_service
from app.modules.agents.defs import deadline as deadline_service
from app.modules.harness.evidence import SpanResolver
from app.modules.ingest.date_parser import DateKind, find_date_candidates

pytestmark = pytest.mark.security

BODY = (
    "The staging deploy failed last night. Could you review the logs "
    "and confirm by Friday whether we should roll back?"
)


class TestEveryValueResolvesToRealWords:
    """Gate: an AI value with no resolvable span is not a value."""

    MESSAGE = UUID("11111111-1111-4111-8111-111111111111")

    def resolver(self) -> SpanResolver:
        return SpanResolver({self.MESSAGE: BODY})

    def test_a_span_that_resolves_comes_back_with_its_words(self) -> None:
        found = self.resolver().resolve(
            {"message_id": str(self.MESSAGE), "char_start": 4, "char_end": 25}
        )
        assert found is not None
        # The quote is sliced from the stored text, so it cannot disagree
        # with the offsets it claims.
        assert found.quote == BODY[4:25].strip()

    @pytest.mark.parametrize(
        "span",
        [
            # A message id from nowhere. The single most common failure.
            {"message_id": str(uuid4()), "char_start": 0, "char_end": 20},
            # Offsets past the end of the body.
            {"message_id": "MSG", "char_start": 9000, "char_end": 9100},
            # Inverted, so the slice is empty.
            {"message_id": "MSG", "char_start": 40, "char_end": 10},
            # In range but too short to read as a quotation.
            {"message_id": "MSG", "char_start": 3, "char_end": 4},
            # Not a uuid at all.
            {"message_id": "the first message", "char_start": 0, "char_end": 20},
            # Strings where integers belong.
            {"message_id": "MSG", "char_start": "start", "char_end": "end"},
            # Missing entirely.
            {},
            "not even a dict",
        ],
        ids=range(8),
    )
    def test_a_span_that_does_not_resolve_is_no_evidence(self, span: Any) -> None:
        if isinstance(span, dict) and span.get("message_id") == "MSG":
            span = {**span, "message_id": str(self.MESSAGE)}
        assert self.resolver().resolve(span) is None

    def test_a_partly_evidenced_claim_keeps_what_holds(self) -> None:
        """Three of five good means the value stands on three."""
        spans = [
            {"message_id": str(self.MESSAGE), "char_start": 0, "char_end": 30},
            {"message_id": str(uuid4()), "char_start": 0, "char_end": 30},
            {"message_id": str(self.MESSAGE), "char_start": 31, "char_end": 60},
        ]
        assert len(self.resolver().resolve_all(spans)) == 2

    def test_a_claim_with_nothing_behind_it_resolves_to_nothing(self) -> None:
        """Which is what makes the panel say "not determined"."""
        assert self.resolver().resolve_all([{"message_id": str(uuid4())}]) == []


class TestTheExtractorAndThePromptAgree:
    """A coupling worth a test: two modules share one text format.

    ``context_builder`` writes the message blocks and ``extractive``
    parses them. If the format changes on one side, extraction silently
    returns nothing -- which looks exactly like an email with nothing in
    it, and would make every stub-backed screen quietly empty.
    """

    def test_the_block_format_round_trips(self) -> None:
        from app.modules.providers.llm.extractive import parse_blocks

        message_id = str(uuid4())
        rendered = (
            f"Message: {message_id}\n"
            "From: sender@example.test\n"
            "Date: 2026-11-08 09:00\n"
            "Body (character offsets below start at 0):\n"
            f"{BODY}"
        )
        blocks = parse_blocks(rendered)
        assert len(blocks) == 1
        assert blocks[0].message_id == message_id
        # Offset zero means offset zero in *this* string, which is the
        # whole point of the marker.
        assert blocks[0].body == BODY

    def test_the_marker_in_the_builder_is_the_one_the_parser_expects(self) -> None:
        import re

        from app.modules.harness.context_builder import BODY_MARKER
        from app.modules.providers.llm import extractive

        assert re.escape(BODY_MARKER) in extractive._BLOCK.pattern or BODY_MARKER in (
            extractive._BLOCK.pattern.replace("\\", "")
        )

    def test_extracted_spans_point_at_the_text_they_came_from(self) -> None:
        from app.modules.providers.llm.extractive import answer

        message_id = uuid4()
        prompt = (
            f"Message: {message_id}\n"
            "From: sender@example.test\n"
            "Date: 2026-11-08 09:00\n"
            "Body (character offsets below start at 0):\n"
            f"{BODY}"
        )
        output = answer(
            prompt,
            {"properties": {"summary": {}, "intent": {}, "entities": {}, "evidence": {}}},
        )
        assert output is not None

        # The gate, against the extractor: every span it produced
        # resolves, because it produced them by slicing.
        resolver = SpanResolver({message_id: BODY})
        assert output["evidence"]
        assert len(resolver.resolve_all(output["evidence"])) == len(output["evidence"])


class TestDeadlinesAreClassifiedNotInvented:
    """Gate: exact dates where there are dates, "unclear" where there are not."""

    SENT = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)

    def candidates(self, body: str) -> list[tuple[UUID, Any]]:
        message_id = uuid4()
        return [
            (message_id, candidate) for candidate in find_date_candidates(body, sent_at=self.SENT)
        ]

    def test_the_agent_has_no_field_in_which_to_write_a_date(self) -> None:
        """The structural claim, checked against the manifest itself."""
        from app.modules.agents.runtime.registry import load_registry

        schema = load_registry()["deadline"].output_schema
        item = schema["properties"]["deadlines"]["items"]["properties"]

        # An exact set, not a substring scan: "candidate_index" contains
        # "date", which is exactly the kind of false positive a naive
        # check produces. Adding `normalized_date` to the manifest fails
        # this test, which is the point of writing it as a whole-set
        # assertion.
        assert set(item) == {
            "candidate_index",
            "is_deadline",
            "date_type",
            "resolution_status",
            "confidence_band",
            "is_for_user",
            "reason",
        }
        assert schema.get("additionalProperties") is False

    def test_a_resolved_date_comes_from_the_parser_not_the_model(self) -> None:
        candidates = self.candidates("Please confirm by 12 November.")
        assert candidates, "the parser should find an absolute date"

        # The model says resolved, and claims a different date in a field
        # it does not have. The stored date is the parser's.
        extracted = deadline_service._from_output(
            {
                "deadlines": [
                    {
                        "candidate_index": 0,
                        "is_deadline": True,
                        "date_type": "explicit_absolute",
                        "resolution_status": "resolved",
                        "confidence_band": "high",
                        "is_for_user": True,
                        "normalized_date": "2099-01-01",
                    }
                ]
            },
            candidates=candidates,
            timezone_name="UTC",
        )
        assert len(extracted) == 1
        assert extracted[0].normalized_date == candidates[0][1].resolved
        assert extracted[0].normalized_date.year == 2026

    def test_saying_unclear_is_a_pass_and_stores_no_date(self) -> None:
        """Ambiguity recall. A question that also shows a date is not one."""
        candidates = self.candidates("Can you get it to me by Friday?")
        assert candidates

        extracted = deadline_service._from_output(
            {
                "deadlines": [
                    {
                        "candidate_index": 0,
                        "is_deadline": True,
                        "date_type": "explicit_relative",
                        "resolution_status": "ambiguous",
                        "confidence_band": "medium",
                        "is_for_user": True,
                    }
                ]
            },
            candidates=candidates,
            timezone_name="UTC",
        )
        assert len(extracted) == 1
        assert extracted[0].resolution_status == "ambiguous"
        assert extracted[0].normalized_date is None
        # And the sender's words survive, because that is what the
        # question quotes.
        assert extracted[0].raw_phrase

    def test_claiming_resolved_without_a_date_is_corrected(self) -> None:
        candidates = self.candidates("Please get this finished soon.")
        vague = [c for c in candidates if c[1].resolved is None]
        if not vague:
            pytest.skip("the parser resolved everything in this phrasing")

        extracted = deadline_service._from_output(
            {
                "deadlines": [
                    {
                        "candidate_index": candidates.index(vague[0]),
                        "is_deadline": True,
                        "date_type": "vague",
                        "resolution_status": "resolved",
                        "confidence_band": "high",
                        "is_for_user": True,
                    }
                ]
            },
            candidates=candidates,
            timezone_name="UTC",
        )
        assert extracted[0].resolution_status == "unresolved"
        assert extracted[0].normalized_date is None

    def test_an_invented_candidate_index_stores_nothing(self) -> None:
        candidates = self.candidates("Please confirm by 12 November.")
        extracted = deadline_service._from_output(
            {
                "deadlines": [
                    {
                        "candidate_index": 99,
                        "is_deadline": True,
                        "date_type": "explicit_absolute",
                        "resolution_status": "resolved",
                        "confidence_band": "high",
                        "is_for_user": True,
                    }
                ]
            },
            candidates=candidates,
            timezone_name="UTC",
        )
        assert extracted == []

    def test_a_date_that_is_not_a_deadline_is_not_stored(self) -> None:
        candidates = self.candidates("We shipped the fix on 12 November.")
        extracted = deadline_service._from_output(
            {
                "deadlines": [
                    {
                        "candidate_index": 0,
                        "is_deadline": False,
                        "date_type": "explicit_absolute",
                        "resolution_status": "resolved",
                        "confidence_band": "high",
                        "is_for_user": False,
                    }
                ]
            },
            candidates=candidates,
            timezone_name="UTC",
        )
        assert extracted == []

    def test_the_parser_itself_bands_rather_than_scoring(self) -> None:
        for candidate in self.candidates("Please confirm by 12 November."):
            assert candidate[1].confidence_band in ("high", "medium", "low")
            assert candidate[1].kind in set(DateKind)


class TestStatedAndInferredNeverConflate:
    """Gate: the two labels mean different things and stay different."""

    MESSAGE = UUID("22222222-2222-4222-8222-222222222222")

    def resolver(self) -> SpanResolver:
        return SpanResolver({self.MESSAGE: BODY})

    def test_a_stated_item_with_a_real_span_keeps_its_label(self) -> None:
        outcome = action_service._from_output(
            uuid4(),
            {
                "items": [
                    {
                        "description": "Review the logs",
                        "owner": "user",
                        "source": "stated",
                        "message_id": str(self.MESSAGE),
                        "char_start": 34,
                        "char_end": 60,
                    }
                ],
                "follow_up_needed": True,
            },
            resolver=self.resolver(),
        )
        assert len(outcome.items) == 1
        assert outcome.items[0].source == "stated"
        assert outcome.items[0].quote

    def test_a_stated_item_that_cannot_be_quoted_is_dropped(self) -> None:
        """Not softened to 'inferred'.

        What it asserts is that a person asked for this. Kept as an
        inference, it would sit on the user's task list as an obligation
        nobody made of them.
        """
        outcome = action_service._from_output(
            uuid4(),
            {
                "items": [
                    {
                        "description": "Wire the payment through",
                        "owner": "user",
                        "source": "stated",
                        "message_id": str(uuid4()),
                        "char_start": 0,
                        "char_end": 40,
                    }
                ],
                "follow_up_needed": True,
            },
            resolver=self.resolver(),
        )
        assert outcome.items == []
        assert outcome.dropped_unsupported == 1
        # And nothing is left claiming the user is holding something up.
        assert outcome.follow_up_needed is False

    def test_an_inferred_item_needs_no_span(self) -> None:
        outcome = action_service._from_output(
            uuid4(),
            {
                "items": [
                    {
                        "description": "Someone should check the deploy pipeline",
                        "owner": "unclear",
                        "source": "inferred",
                    }
                ],
                "follow_up_needed": False,
            },
            resolver=self.resolver(),
        )
        assert len(outcome.items) == 1
        assert outcome.items[0].source == "inferred"
        assert outcome.items[0].evidence_char_start is None

    def test_an_unknown_source_label_becomes_inferred(self) -> None:
        """The safe direction. 'probably stated' is not a quotation."""
        outcome = action_service._from_output(
            uuid4(),
            {
                "items": [{"description": "Do the thing", "owner": "user", "source": "probably"}],
                "follow_up_needed": False,
            },
            resolver=self.resolver(),
        )
        assert outcome.items[0].source == "inferred"

    def test_an_unknown_owner_becomes_unclear_not_the_user(self) -> None:
        outcome = action_service._from_output(
            uuid4(),
            {
                "items": [
                    {"description": "Do the thing", "owner": "everyone", "source": "inferred"}
                ],
                "follow_up_needed": False,
            },
            resolver=self.resolver(),
        )
        assert outcome.items[0].owner == "unclear"


class TestTheDatabaseRefusesWhatTheCodeRefuses:
    """The constraints, checked against a real Postgres.

    Enforced twice on purpose: a future caller that bypasses the service
    still cannot write a resolved deadline with no date or a stated item
    with no span.
    """

    @pytest.mark.integration
    async def test_a_resolved_deadline_must_carry_a_date(
        self, app_engine: object, seeded_tenants: tuple[object, object]
    ) -> None:
        from sqlalchemy.exc import IntegrityError

        async with tenant_session(USER_A) as session:
            ids = await _seed_thread(session, USER_A)
            if ids is None:
                pytest.skip("no connected account fixture to hang a thread from")
            thread_id, message_id = ids

            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        """
                        INSERT INTO deadlines
                            (user_id, thread_id, message_id, raw_phrase, normalized_date,
                             date_type, resolution_status, confidence_band, created_by)
                        VALUES (:u, :t, :m, 'by Friday', NULL,
                                'explicit_relative', 'resolved', 'high', 'agent')
                        """
                    ),
                    {"u": str(USER_A), "t": str(thread_id), "m": str(message_id)},
                )

    @pytest.mark.integration
    async def test_an_agent_stated_action_must_carry_a_span(
        self, app_engine: object, seeded_tenants: tuple[object, object]
    ) -> None:
        from sqlalchemy.exc import IntegrityError

        async with tenant_session(USER_A) as session:
            ids = await _seed_thread(session, USER_A)
            if ids is None:
                pytest.skip("no connected account fixture to hang a thread from")
            thread_id, _ = ids

            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        """
                        INSERT INTO action_items
                            (user_id, thread_id, description, owner, source, created_by)
                        VALUES (:u, :t, 'Pay the invoice', 'user', 'stated', 'agent')
                        """
                    ),
                    {"u": str(USER_A), "t": str(thread_id)},
                )


async def _seed_thread(session: Any, user_id: UUID) -> tuple[UUID, UUID] | None:
    """One thread and one message, hung off whatever account exists."""
    account_id = await session.scalar(text("SELECT id FROM connected_accounts LIMIT 1"))
    if account_id is None:
        account_id = await session.scalar(
            text(
                """
                INSERT INTO connected_accounts
                    (user_id, provider, provider_account_email, status, granted_scopes)
                VALUES (:u, 'gmail', :pid, 'active',
                        ARRAY['https://www.googleapis.com/auth/gmail.readonly'])
                RETURNING id
                """
            ),
            {"u": str(user_id), "pid": f"gates-{uuid4()}@example.test"},
        )
        if account_id is None:
            return None

    thread_id = await session.scalar(
        text(
            """
            INSERT INTO email_threads
                (user_id, account_id, provider_thread_id, subject, message_count,
                 content_version, latest_message_at)
            VALUES (:u, :a, :pid, 'Gate fixture', 1, 1, now())
            RETURNING id
            """
        ),
        {"u": str(user_id), "a": str(account_id), "pid": f"t-{uuid4()}"},
    )
    message_id = await session.scalar(
        text(
            """
            INSERT INTO email_messages
                (user_id, account_id, thread_id, provider_message_id, from_email,
                 sent_at, body_text_stripped)
            VALUES (:u, :a, :t, :pid, 'sender@example.test', :sent, :body)
            RETURNING id
            """
        ),
        {
            "u": str(user_id),
            "a": str(account_id),
            "t": str(thread_id),
            "pid": f"m-{uuid4()}",
            "sent": datetime.now(timezone.utc) - timedelta(hours=1),
            "body": BODY,
        },
    )
    return UUID(str(thread_id)), UUID(str(message_id))


class TestTheThreadIsDelimited:
    """The prompt says where other people's writing stops.

    Two things rest on the closing tag. A model reading the thread can
    tell the email apart from the instruction that follows it, which is
    the cheap half of injection resistance. And anything parsing the
    blocks back out stops at the right place -- without it, the final
    body ran to the end of the prompt and the agent's own question came
    back as one of the email's action items. It did, on screen.
    """

    def test_the_question_after_the_thread_is_not_part_of_it(self) -> None:
        from app.modules.harness.context_builder import (
            BODY_MARKER,
            THREAD_CLOSE,
            THREAD_OPEN,
        )
        from app.modules.providers.llm.extractive import parse_blocks

        message_id = uuid4()
        rendered = (
            "You read one email thread.\n\n"
            f"{THREAD_OPEN}\n"
            "Subject: CI pipeline failed\n\n"
            f"Message: {message_id}\n"
            "From: priya@example.test\n"
            "Date: 2026-11-08 09:00\n"
            f"{BODY_MARKER}\n"
            f"{BODY}\n"
            f"{THREAD_CLOSE}\n\n"
            "user_id: 00000000-0000-4000-8000-00000000000a\n"
            "What needs to happen next in this thread?"
        )

        blocks = parse_blocks(rendered)
        assert len(blocks) == 1
        assert blocks[0].body == BODY
        assert "What needs to happen next" not in blocks[0].body
        assert "user_id" not in blocks[0].body

    def test_the_extractor_does_not_turn_the_question_into_an_action(self) -> None:
        from app.modules.harness.context_builder import (
            BODY_MARKER,
            THREAD_CLOSE,
            THREAD_OPEN,
        )
        from app.modules.providers.llm.extractive import answer

        message_id = uuid4()
        rendered = (
            f"{THREAD_OPEN}\n"
            f"Message: {message_id}\n"
            "From: priya@example.test\n"
            "Date: 2026-11-08 09:00\n"
            f"{BODY_MARKER}\n"
            f"{BODY}\n"
            f"{THREAD_CLOSE}\n\n"
            "Please confirm what needs to happen next in this thread?"
        )
        output = answer(rendered, {"properties": {"items": {}, "follow_up_needed": {}}})
        assert output is not None
        for item in output["items"]:
            assert "next in this thread" not in item["description"]
