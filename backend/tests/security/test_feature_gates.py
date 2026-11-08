"""The phase 11 blocking gates. Short.

A disabled feature **never executes** · disabling does not delete stored
results · **no model call** to evaluate whether a toggle is on.

Plus the two the registry has to hold on its own: every FEATURE_ID in the
codebase is a feature the registry knows, and the locked list in
08-ui-spec.md §10 is the list that is actually shipped.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.core.tenancy import tenant_session
from app.database.seed import USER_A, USER_B
from app.modules.features import registry
from app.modules.features import service as features

pytestmark = pytest.mark.security

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
async def _clean_toggles() -> Any:
    """Every test starts from the defaults.

    These tests write real rows, and a toggle left off by one of
    them would make the next one assert against a state it did not
    set up -- which is how an order-dependent suite starts passing
    for the wrong reason.
    """

    async def wipe() -> None:
        for user in (USER_A, USER_B):
            try:
                async with tenant_session(user) as session:
                    await session.execute(text("DELETE FROM user_features"))
            except Exception:  # no database in this run; nothing to clean
                return
            features.invalidate(user)

    await wipe()
    yield
    await wipe()


class TestTheLockedListIsTheShippedList:
    """08-ui-spec.md §10 is locked, so the registry is checked against it."""

    def test_there_are_seventeen_toggles(self) -> None:
        assert len(registry.FEATURES) == 17

    def test_ten_are_on_by_default(self) -> None:
        """ "Ten enabled by default, as specified"."""
        assert len(registry.default_enabled()) == 10

    def test_the_four_groups_are_the_spec_s_four(self) -> None:
        assert [label for _, label in registry.GROUPS.items()] == [
            "Email intelligence",
            "Developer intelligence",
            "Productivity",
            "Writing & communication",
        ]

    @pytest.mark.parametrize(
        ("feature_id", "description"),
        [
            (
                "priority_detection",
                "Identify urgent, important and time-sensitive emails.",
            ),
            (
                "smart_categorization",
                "Automatically classify emails into meaningful categories.",
            ),
            ("instant_summaries", "Generate concise summaries of lengthy emails."),
            (
                "deadline_detection",
                "Identify deadlines and important dates from emails.",
            ),
            (
                "github_linking",
                "Connect relevant emails with GitHub issues, pull requests and repositories.",
            ),
        ],
        ids=range(5),
    )
    def test_the_wording_is_the_spec_s_wording(self, feature_id: str, description: str) -> None:
        """A description is a promise, so it is not paraphrased."""
        assert registry.get(feature_id).description == description

    def test_the_priority_drawer_says_exactly_what_the_spec_says(self) -> None:
        """Verbatim: the three sensitivity options and their explanations."""
        field = registry.get("priority_detection").config[0]
        assert field.options == (
            ("strict", "Strict", "only genuinely urgent emails"),
            ("balanced", "Balanced", "important and time-sensitive emails"),
            ("sensitive", "Sensitive", "include potentially important emails"),
        )

    def test_the_three_presets_contain_what_the_spec_lists(self) -> None:
        by_id = {preset.id: preset for preset in registry.PRESETS}

        assert by_id["minimal"].enabled == {
            "priority_detection",
            "instant_summaries",
            "smart_categorization",
        }
        # Each preset is the previous one plus its own additions.
        assert by_id["minimal"].enabled < by_id["productivity"].enabled
        assert by_id["productivity"].enabled < by_id["developer"].enabled
        assert by_id["developer"].enabled - by_id["productivity"].enabled == {
            "technical_detection",
            "error_context",
            "github_linking",
            "technical_memory",
        }
        assert [p.label for p in registry.PRESETS] == [
            "Lightweight",
            "Recommended",
            "Developer-first",
        ]

    def test_eight_features_carry_their_own_configuration(self) -> None:
        """The spec's per-feature configuration table, by count."""
        configurable = {f.id for f in registry.FEATURES if f.config}
        assert configurable == {
            "priority_detection",
            "smart_categorization",
            "instant_summaries",
            "deadline_detection",
            "opportunity_discovery",
            "personalized_replies",
            "followup_reminders",
            "technical_detection",
        }


class TestAnUnknownFeatureIsNeverEnabled:
    """A typo must not read as "on"."""

    def test_the_registry_refuses_an_id_it_does_not_know(self) -> None:
        with pytest.raises(registry.UnknownFeature):
            registry.get("priority_detektion")

    def test_a_config_refuses_it_too(self) -> None:
        config = features.FeatureConfig(user_id=uuid4(), enabled=frozenset())
        with pytest.raises(registry.UnknownFeature):
            config.is_on("summaries_but_misspelled")

    def test_every_feature_id_in_the_codebase_is_known(self) -> None:
        """The gate that keeps the two in step.

        A service whose ``FEATURE_ID`` the registry has never heard of is
        a service nothing can turn off, and the failure is silent --
        which is exactly what this looks for.
        """
        known = {f.id for f in registry.FEATURES} | registry.ALWAYS_ON
        offenders: list[str] = []

        for path in sorted((ROOT / "backend" / "app").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if "FEATURE_ID" not in names:
                    continue
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    if node.value.value not in known:
                        offenders.append(f"{path.name}: {node.value.value}")

        assert offenders == [], f"feature ids nothing can toggle: {offenders}"


class TestDependenciesMoveTogether:
    def test_enabling_pulls_in_what_it_needs(self) -> None:
        enabled = registry.resolve_enable(frozenset(), "error_context")
        assert "technical_detection" in enabled

    def test_disabling_pushes_out_what_needed_it(self) -> None:
        start = frozenset(
            {"technical_detection", "error_context", "github_linking", "technical_memory"}
        )
        after = registry.resolve_disable(start, "technical_detection")
        assert after == frozenset()

    def test_a_feature_with_no_dependents_takes_nothing_with_it(self) -> None:
        start = frozenset({"instant_summaries", "priority_detection"})
        after = registry.resolve_disable(start, "instant_summaries")
        assert after == frozenset({"priority_detection"})

    def test_the_graph_is_acyclic(self) -> None:
        """Otherwise resolving a toggle never terminates."""
        for feature in registry.FEATURES:
            assert feature.id not in registry.requirements(feature.id)
            assert feature.id not in registry.dependents(feature.id)


class TestConfigIsValidatedNotStored:
    def test_an_unknown_key_is_dropped(self) -> None:
        kept = registry.validate_config(
            "priority_detection", {"sensitivity": "strict", "evil": "payload"}
        )
        assert kept == {"sensitivity": "strict"}

    def test_a_choice_outside_the_options_falls_back(self) -> None:
        kept = registry.validate_config("priority_detection", {"sensitivity": "paranoid"})
        assert kept == {"sensitivity": "balanced"}

    def test_a_number_is_clamped(self) -> None:
        kept = registry.validate_config("deadline_detection", {"remind_days_before": 9999})
        assert kept == {"remind_days_before": 30}

    def test_rubbish_becomes_the_default(self) -> None:
        kept = registry.validate_config("followup_reminders", {"days_before_reminder": "soon"})
        assert kept == {"days_before_reminder": 3}


class TestNoModelDecidesAToggle:
    """Gate: no model call to evaluate whether a toggle is on."""

    MODEL_WORDS: ClassVar[tuple[str, ...]] = (
        "LLMProvider",
        "StubProvider",
        "run_agent",
        "complete(",
        "providers.llm",
    )

    def test_the_registry_and_service_hold_no_model(self) -> None:
        for name in ("registry.py", "service.py"):
            source = (ROOT / "backend" / "app" / "modules" / "features" / name).read_text(
                encoding="utf-8"
            )
            for word in self.MODEL_WORDS:
                assert word not in source, f"{name} reaches for {word}"

    def test_the_settings_endpoint_cannot_import_one(self) -> None:
        """Enforced by the import graph, not by reading the file.

        ``the-http-layer-never-calls-a-model`` covers ``app/api``, so a
        settings handler that reached for a provider fails the build.
        """
        from tests.arch.boundaries import RULES, check_imports

        rule = next(r for r in RULES if r.name == "the-http-layer-never-calls-a-model")
        assert not [v for v in check_imports() if v.rule == rule.name]


@pytest.mark.integration
class TestADisabledFeatureNeverExecutes:
    """The gate, end to end against a real database."""

    async def test_the_planner_refuses_before_the_cache_or_the_budget(
        self, app_engine: object, seeded_tenants: tuple[object, object]
    ) -> None:
        """Order matters: a disabled feature must not even serve a cached
        answer. Serving one would be the feature running, slightly
        cheaper."""
        from app.modules.harness.planner import Decision, IntelligenceRequest, Tier, plan

        async with tenant_session(USER_A) as session:
            request = IntelligenceRequest(
                user_id=USER_A,
                feature_id="instant_summaries",
                agent_id="summarizer",
                agent_version="1",
                prompt_version="1",
                model_id="stub",
                config_hash="x",
                thread_id=uuid4(),
                content_version=1,
                tier=Tier.small,
            )
            decided = await plan(session, request, feature_enabled=False)

        assert decided.decision is Decision.skip
        assert decided.reason == "feature_disabled"
        assert decided.costs_a_model_call is False

    async def test_turning_a_feature_off_stops_its_agent_running(
        self, app_engine: object, seeded_tenants: tuple[object, object]
    ) -> None:
        """Through the service an endpoint actually calls."""
        from app.modules.agents.defs import summarizer
        from app.modules.mcp import bootstrap
        from app.modules.providers.llm.stub import StubProvider

        runtime = bootstrap.build(strict=False)
        spec = runtime.agents["summarizer"]

        async with tenant_session(USER_A) as session:
            ids = await _seed_thread(session, USER_A)
            if ids is None:
                pytest.skip("no account fixture to hang a thread from")
            thread_id, _ = ids

            await features.set_feature(session, USER_A, "instant_summaries", enabled=False)
            before = await _run_count(session)

            outcome = await summarizer.summarize_thread(
                session,
                spec=spec,
                provider=StubProvider(),
                host=runtime.host,
                user_id=USER_A,
                thread_id=thread_id,
            )

            assert outcome is None
            # Not merely "no result" -- no run at all. A run row would
            # mean the agent started and was stopped afterwards.
            assert await _run_count(session) == before

            status = await session.scalar(
                text("SELECT status_summary::text FROM thread_intelligence  WHERE thread_id = :t"),
                {"t": str(thread_id)},
            )
            # Honest about why, rather than silently blank.
            assert status in (None, "skipped_disabled")

    async def test_disabling_does_not_delete_what_is_already_stored(
        self, app_engine: object, seeded_tenants: tuple[object, object]
    ) -> None:
        """A toggle is not a delete button.

        > Disabling stops future processing and retains existing results.
        """
        from app.modules.agents.defs import summarizer
        from app.modules.mcp import bootstrap
        from app.modules.providers.llm.stub import StubProvider

        runtime = bootstrap.build(strict=False)
        spec = runtime.agents["summarizer"]

        async with tenant_session(USER_A) as session:
            ids = await _seed_thread(session, USER_A)
            if ids is None:
                pytest.skip("no account fixture to hang a thread from")
            thread_id, _ = ids

            await features.set_feature(session, USER_A, "instant_summaries", enabled=True)
            produced = await summarizer.summarize_thread(
                session,
                spec=spec,
                provider=StubProvider(),
                host=runtime.host,
                user_id=USER_A,
                thread_id=thread_id,
            )
            assert produced is not None and produced.summary

            await features.set_feature(session, USER_A, "instant_summaries", enabled=False)

            kept = await session.scalar(
                text("SELECT summary FROM thread_summaries WHERE thread_id = :t"),
                {"t": str(thread_id)},
            )
            assert kept == produced.summary

    async def test_triage_withholds_only_the_output_whose_toggle_is_off(
        self, app_engine: object, seeded_tenants: tuple[object, object]
    ) -> None:
        """One agent, three toggles, and they are honoured separately."""
        from app.modules.agents.defs import triage
        from app.modules.mcp import bootstrap
        from app.modules.providers.llm.stub import StubProvider

        runtime = bootstrap.build(strict=False)
        spec = runtime.agents["triage"]

        async with tenant_session(USER_A) as session:
            ids = await _seed_thread(session, USER_A)
            if ids is None:
                pytest.skip("no account fixture to hang a thread from")
            thread_id, _ = ids

            await features.set_feature(session, USER_A, "priority_detection", enabled=False)
            await features.set_feature(session, USER_A, "smart_categorization", enabled=True)

            await triage.triage_thread(
                session,
                spec=spec,
                provider=StubProvider(),
                host=runtime.host,
                user_id=USER_A,
                thread_id=thread_id,
                user_initiated=True,
            )

            row = (
                await session.execute(
                    text(
                        "SELECT category::text, priority FROM thread_intelligence "
                        " WHERE thread_id = :t"
                    ),
                    {"t": str(thread_id)},
                )
            ).first()

        assert row is not None
        assert row[0] is not None, "categorization was on and should have been written"
        assert row[1] is None, "priority was off and should not have been written"


@pytest.mark.integration
class TestTheCacheIsNeverStale:
    """Two processes, one truth.

    The API and the worker hold separate caches. A toggle change that
    reached only one of them would let a disabled feature keep running,
    which is the gate failing quietly rather than loudly.
    """

    async def test_a_second_reader_sees_a_change_it_did_not_make(
        self, app_engine: object, seeded_tenants: tuple[object, object]
    ) -> None:
        async with tenant_session(USER_A) as session:
            first = await features.load(session, USER_A)
            assert first.is_on("instant_summaries") is True  # the default

        # Another process writes. Simulated by dropping the local copy
        # *after* the write, which is the state a second process is in:
        # it holds a config loaded before the change.
        async with tenant_session(USER_A) as session:
            await features.set_feature(session, USER_A, "instant_summaries", enabled=False)

        features._CACHE[USER_A] = first  # the stale copy a worker would hold

        async with tenant_session(USER_A) as session:
            again = await features.load(session, USER_A)

        assert again.is_on("instant_summaries") is False
        assert again.watermark != first.watermark

    async def test_an_unchanged_config_is_served_from_memory(
        self, app_engine: object, seeded_tenants: tuple[object, object]
    ) -> None:
        async with tenant_session(USER_A) as session:
            first = await features.load(session, USER_A)
            second = await features.load(session, USER_A)
        # Identity, not equality: the point is that nothing was rebuilt.
        assert first is second

    async def test_one_users_toggles_are_invisible_to_another(
        self, app_engine: object, seeded_tenants: tuple[object, object]
    ) -> None:
        async with tenant_session(USER_A) as session:
            await features.set_feature(session, USER_A, "opportunity_discovery", enabled=True)

        async with tenant_session(USER_B) as session:
            other = await features.load(session, USER_B)

        assert other.is_on("opportunity_discovery") is False


@pytest.mark.integration
class TestPresetsMoveTheTogglesTogether:
    async def test_applying_developer_turns_on_its_whole_set(
        self, app_engine: object, seeded_tenants: tuple[object, object]
    ) -> None:
        async with tenant_session(USER_A) as session:
            after = await features.apply_preset(session, USER_A, "developer")

        expected = next(p for p in registry.PRESETS if p.id == "developer").resolved()
        assert after.enabled == expected

    async def test_a_preset_does_not_wipe_per_feature_configuration(
        self, app_engine: object, seeded_tenants: tuple[object, object]
    ) -> None:
        """A preset says which features run, not how they run."""
        async with tenant_session(USER_A) as session:
            await features.set_feature(
                session,
                USER_A,
                "priority_detection",
                enabled=True,
                config={"sensitivity": "strict"},
            )
            after = await features.apply_preset(session, USER_A, "minimal")

        assert after.config("priority_detection")["sensitivity"] == "strict"


async def _run_count(session: Any) -> int:
    return int(await session.scalar(text("SELECT count(*) FROM agent_runs")) or 0)


async def _seed_thread(session: Any, user_id: UUID) -> tuple[UUID, UUID] | None:
    """One thread with a message, for the gates to act on."""
    account_id = await session.scalar(text("SELECT id FROM connected_accounts LIMIT 1"))
    if account_id is None:
        account_id = await session.scalar(
            text(
                """
                INSERT INTO connected_accounts
                    (user_id, provider, provider_account_email, status, granted_scopes)
                VALUES (:u, 'gmail', :e, 'active',
                        ARRAY['https://www.googleapis.com/auth/gmail.readonly'])
                RETURNING id
                """
            ),
            {"u": str(user_id), "e": f"flag-{uuid4()}@example.test"},
        )
        if account_id is None:
            return None

    thread_id = await session.scalar(
        text(
            """
            INSERT INTO email_threads
                (user_id, account_id, provider_thread_id, subject, message_count,
                 content_version, latest_message_at)
            VALUES (:u, :a, :pid, 'Feature gate fixture', 1, 1, now())
            RETURNING id
            """
        ),
        {"u": str(user_id), "a": str(account_id), "pid": f"ft-{uuid4()}"},
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
            "pid": f"fm-{uuid4()}",
            "sent": datetime.now(timezone.utc),
            "body": (
                "The staging deploy failed overnight. Could you review the logs "
                "and confirm by Friday whether we should roll back?"
            ),
        },
    )
    return UUID(str(thread_id)), UUID(str(message_id))
