"""The job queue, intelligence state, agent traces, budgets and the cache.

Revision ID: 0004
Revises: 0003
Create Date: phases 4 and 5

Four ideas in one migration, because they only make sense together:

``background_jobs`` is the queue. The partial unique index on ``dedupe_key``
is what collapses a reprocessing storm into one job: a burst of five
messages on one thread enqueues one triage, not five (gap C5).

``thread_intelligence`` carries **a status per capability**, never one
global boolean. A thread whose summary is ready and whose deadline
extraction failed has to be able to say exactly that, or the interface has
to lie in one direction or the other (gap C4).

``agent_runs`` and ``agent_steps`` are the trace. Without a per-step record
of tokens and cost, an agent bug is unreproducible and an expensive agent is
unidentifiable (gaps C1, B4). ``tool_result_digest`` stores a hash, never the
tool output: a trace holding raw email text is a second copy of the mailbox
in a table nobody thinks of as sensitive (gap D8).

``intelligence_cache`` holds a pointer to the real row, never a copy, keyed
on all nine things that can change an answer.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

APP_ROLE = "maail_app"

RLS_TABLES = (
    "thread_intelligence",
    "thread_intelligence_versions",
    "thread_summaries",
    "agent_runs",
    "agent_steps",
    "usage_budgets",
    "intelligence_cache",
)

CAPABILITY_STATES = (
    "not_applicable",
    "pending",
    "running",
    "ready",
    "failed",
    "skipped_disabled",
    "skipped_budget",
)


def upgrade() -> None:
    thread_category = pg.ENUM(
        "technical", "opportunity", "academic", "administrative",
        "personal", "promotional", "notification", "other",
        name="thread_category", create_type=False,
    )
    capability_status = pg.ENUM(*CAPABILITY_STATES, name="capability_status", create_type=False)
    agent_run_status = pg.ENUM(
        "queued", "running", "awaiting_approval", "succeeded",
        "failed", "cancelled", "budget_denied", "cap_exceeded",
        name="agent_run_status", create_type=False,
    )
    for enum in (thread_category, capability_status, agent_run_status):
        enum.create(op.get_bind(), checkfirst=True)

    # --- the queue --------------------------------------------------------
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        # One live job per key. The partial index below is the mechanism.
        sa.Column("dedupe_key", sa.Text()),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default=sa.text("100")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column(
            "available_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("locked_by", sa.Text()),
        sa.Column("lease_expires_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed','dead')", name="status_known"
        ),
    )
    # A second event for the same subject finds this index and updates the
    # existing job instead of queueing another.
    op.create_index(
        "uq_jobs_dedupe_live",
        "background_jobs",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL AND status IN ('pending','running')"),
    )
    op.create_index(
        "ix_jobs_claim",
        "background_jobs",
        ["priority", "available_at", "id"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_jobs_reap",
        "background_jobs",
        ["lease_expires_at"],
        postgresql_where=sa.text("status = 'running'"),
    )

    # --- intelligence -----------------------------------------------------
    op.create_table(
        "thread_intelligence",
        sa.Column(
            "thread_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("email_threads.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("category", thread_category),
        sa.Column("category_source", sa.Text()),
        sa.Column("priority", sa.SmallInteger()),
        sa.Column("priority_reason", sa.Text()),
        # Decay is applied at query time. Rewriting the stored judgement
        # would destroy the audit trail (gap E3).
        sa.Column("priority_computed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("needs_reply", sa.Boolean()),
        sa.Column("is_technical", sa.Boolean()),
        sa.Column(
            "routed_agents", pg.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")
        ),
        # One status per capability, never one global boolean (gap C4).
        sa.Column("status_summary", capability_status, nullable=False, server_default="pending"),
        sa.Column("status_deadline", capability_status, nullable=False, server_default="pending"),
        sa.Column("status_actions", capability_status, nullable=False, server_default="pending"),
        sa.Column(
            "status_developer", capability_status, nullable=False, server_default="not_applicable"
        ),
        sa.Column(
            "status_opportunity", capability_status, nullable=False, server_default="not_applicable"
        ),
        sa.Column("computed_from_content_version", sa.Integer(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(
            "category_source IS NULL OR category_source IN ('user_rule','agent','user_override')",
            name="category_source_known",
        ),
        sa.CheckConstraint("priority IS NULL OR priority BETWEEN 0 AND 3", name="priority_range"),
    )

    op.create_table(
        "thread_intelligence_versions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "thread_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("email_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("snapshot", pg.JSONB(), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column(
            "trigger_message_id", pg.UUID(as_uuid=True), sa.ForeignKey("email_messages.id")
        ),
        sa.Column("agent_run_id", pg.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index(
        "ix_ti_versions_thread", "thread_intelligence_versions", ["thread_id", sa.text("created_at DESC")]
    )

    op.create_table(
        "thread_summaries",
        sa.Column(
            "id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "thread_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("email_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("bullet_points", pg.JSONB()),
        # [{message_id, char_start, char_end}] -- every claim points at the
        # words it came from, or it does not render (gap F3).
        sa.Column("evidence", pg.JSONB()),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("model", sa.Text()),
        sa.Column("agent_run_id", pg.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint("kind IN ('short','detailed')", name="kind_known"),
        # The cheapest cache there is: never summarise one version twice.
        sa.UniqueConstraint("thread_id", "kind", "content_version", name="uq_summary_version"),
    )

    # --- traces -----------------------------------------------------------
    op.create_table(
        "agent_runs",
        sa.Column(
            "id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("agent_version", sa.Text(), nullable=False),
        sa.Column("plane", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text()),
        sa.Column("subject_id", pg.UUID(as_uuid=True)),
        # A run that spawned this one. Depth plus parent is how a cycle is
        # detected rather than discovered on the bill (gap C3).
        sa.Column("parent_run_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id")),
        sa.Column("depth", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", agent_run_status, nullable=False, server_default="queued"),
        sa.Column("output", pg.JSONB()),
        sa.Column("error", pg.JSONB()),
        sa.Column("model", sa.Text()),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cost_micros", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("step_count", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint("plane IN ('U','C')", name="plane_known"),
    )
    op.create_index("ix_runs_cost", "agent_runs", ["user_id", "agent_id", sa.text("created_at DESC")])
    op.create_index("ix_runs_subject", "agent_runs", ["subject_id", sa.text("created_at DESC")])

    op.create_table(
        "agent_steps",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "run_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("seq", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text()),
        sa.Column("tool_args", pg.JSONB()),
        # A digest, never the output. A trace holding raw email text is a
        # second copy of the mailbox somewhere nobody guards (gap D8).
        sa.Column("tool_result_digest", sa.Text()),
        sa.Column("tool_result_bytes", sa.Integer()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint("kind IN ('llm','tool')", name="step_kind_known"),
        sa.UniqueConstraint("run_id", "seq", name="uq_step_seq"),
    )

    # --- budgets and cache -------------------------------------------------
    op.create_table(
        "usage_budgets",
        sa.Column(
            "user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("period_month", sa.Date(), primary_key=True),
        sa.Column("soft_cap_micros", sa.BigInteger(), nullable=False),
        sa.Column("hard_cap_micros", sa.BigInteger(), nullable=False),
        sa.Column("spent_micros", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )

    op.create_table(
        "intelligence_cache",
        # sha256 of the nine things that can change the answer.
        sa.Column("cache_key", sa.Text(), primary_key=True),
        sa.Column(
            "user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "thread_id", pg.UUID(as_uuid=True), sa.ForeignKey("email_threads.id", ondelete="CASCADE")
        ),
        sa.Column("agent_id", sa.Text(), nullable=False),
        # A pointer to the real row, never a copy of it.
        sa.Column("result_ref", pg.JSONB(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("last_hit_at", sa.TIMESTAMP(timezone=True)),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text()),
        sa.Column("subject_id", pg.UUID(as_uuid=True)),
        sa.Column("detail", pg.JSONB()),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index("ix_audit_user", "audit_logs", ["user_id", sa.text("created_at DESC")])

    # --- row level security ------------------------------------------------
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
              USING (user_id = app_current_user())
              WITH CHECK (user_id = app_current_user())
            """
        )
        op.execute(
            f"""
            DO $owner_policy$
            BEGIN
              EXECUTE 'CREATE POLICY owner_bootstrap ON {table} TO ' ||
                      quote_ident(current_user) || ' USING (true) WITH CHECK (true)';
            END
            $owner_policy$
            """
        )

    # `background_jobs` and `audit_logs` carry a nullable user_id: a purge
    # job and a system audit line belong to no tenant. The schema audit
    # knows them by name rather than inferring it from the column.
    for table in ("background_jobs", "audit_logs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
              USING (user_id IS NULL OR user_id = app_current_user())
              WITH CHECK (user_id IS NULL OR user_id = app_current_user())
            """
        )
        op.execute(
            f"""
            DO $owner_policy$
            BEGIN
              EXECUTE 'CREATE POLICY owner_bootstrap ON {table} TO ' ||
                      quote_ident(current_user) || ' USING (true) WITH CHECK (true)';
            END
            $owner_policy$
            """
        )

    op.execute(
        f"""
        DO $grants$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON
              background_jobs, thread_intelligence, thread_intelligence_versions,
              thread_summaries, agent_runs, agent_steps, usage_budgets,
              intelligence_cache, audit_logs
              TO {APP_ROLE};
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE};
          END IF;
        END
        $grants$
        """
    )


def downgrade() -> None:
    for table in (
        "audit_logs", "intelligence_cache", "usage_budgets", "agent_steps", "agent_runs",
        "thread_summaries", "thread_intelligence_versions", "thread_intelligence",
        "background_jobs",
    ):
        op.drop_table(table)
    for enum in ("agent_run_status", "capability_status", "thread_category"):
        op.execute(f"DROP TYPE IF EXISTS {enum}")
