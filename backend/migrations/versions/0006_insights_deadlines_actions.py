"""Intelligence detail: insights, deadlines, action items, tasks.

Revision ID: 0006
Revises: 0005
Create Date: phases 8 and 9

Four tables, and one of them is the reason this migration is interesting.

``deadlines`` is the table most likely to make Maail look either
trustworthy or stupid (02-lld-data-model §4). It stores the sender's words
in ``raw_phrase`` **always**, alongside whatever the agent resolved, so the
interface can show what was actually written rather than asserting a date
from nowhere. ``resolution_status = 'ambiguous'`` is a first-class state:
"by Friday" with two candidate Fridays renders as a question, and nothing
is invented to fill ``normalized_date``.

``action_items`` separates ``stated`` from ``inferred`` in a column rather
than in a convention, because the two are different kinds of claim and the
interface has to be able to tell them apart without guessing.

``tasks`` carries ``origin`` and ``confirmed_at``: an AI suggestion is not
a task until a person confirms it. A suggestion that silently became a
commitment would be the system deciding what the user owes someone.

``thread_insights`` holds intent and extracted entities, keyed by
``content_version`` exactly like ``thread_summaries`` -- so the key *is*
the cache, and a thread whose content has not changed is never re-read.

Related context deliberately gets **no table**. It is a live query over
the existing search vector; storing it would create a second copy that
goes stale on every new message and would need invalidating by hand.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

APP_ROLE = "maail_app"
RLS_TABLES = ("thread_insights", "deadlines", "action_items", "tasks")


def upgrade() -> None:
    # ----------------------------------------------------------------- enums
    op.execute(
        """
        CREATE TYPE date_type AS ENUM (
          'explicit_absolute',
          'explicit_relative',
          'soft_request',
          'vague',
          'recurring'
        )
        """
    )
    op.execute(
        """
        CREATE TYPE date_resolution AS ENUM (
          'resolved','ambiguous','unresolved','user_confirmed','user_corrected'
        )
        """
    )

    # ------------------------------------------------------- thread_insights
    op.create_table(
        "thread_insights",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "thread_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("email_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # What does the sender expect from the user? A closed set, so it is
        # evaluable; "other" exists so the agent is never forced to pick a
        # wrong one.
        sa.Column("intent", sa.Text()),
        sa.Column("intent_reason", sa.Text()),
        sa.Column("intent_confidence", sa.Text()),
        # [{message_id, char_start, char_end}] -- the panel's source
        # affordance resolves these to real words or shows nothing.
        sa.Column("intent_evidence", pg.JSONB()),
        # [{kind, value, message_id, char_start, char_end, provenance}]
        # provenance is one of stated | interpreted | retrieved, which is
        # what the three visual classes on screen 05 render from.
        sa.Column(
            "entities", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("model", sa.Text()),
        sa.Column("agent_run_id", pg.UUID(as_uuid=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "intent IS NULL OR intent IN ('reply_requested','action_requested',"
            "'information_only','deadline_set','approval_requested','scheduling','other')",
            name="insight_intent_known",
        ),
        sa.CheckConstraint(
            "intent_confidence IS NULL OR intent_confidence IN ('high','medium','low')",
            name="insight_confidence_band",
        ),
        # The cache key, as a constraint. Same content, same answer, no
        # second model call -- enforced by the database rather than by
        # everyone remembering to check first.
        sa.UniqueConstraint("thread_id", "content_version", name="uq_insight_per_version"),
    )

    # ------------------------------------------------------------- deadlines
    op.create_table(
        "deadlines",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "thread_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("email_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("email_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Always shown to the user (gap E2). Not nullable on purpose: a
        # deadline with no quotable phrase has no business existing.
        sa.Column("raw_phrase", sa.Text(), nullable=False),
        sa.Column("normalized_date", sa.Date()),
        sa.Column("normalized_time", sa.Time()),
        sa.Column("timezone", sa.Text()),
        sa.Column(
            "date_type",
            pg.ENUM(name="date_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "resolution_status",
            pg.ENUM(name="date_resolution", create_type=False),
            nullable=False,
        ),
        # A band, not a fabricated float (gap E1).
        sa.Column("confidence_band", sa.Text(), nullable=False),
        sa.Column("evidence_char_start", sa.Integer()),
        sa.Column("evidence_char_end", sa.Integer()),
        sa.Column(
            "is_for_user", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "superseded_by", pg.UUID(as_uuid=True), sa.ForeignKey("deadlines.id")
        ),
        sa.Column("content_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("agent_run_id", pg.UUID(as_uuid=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "confidence_band IN ('high','medium','low')", name="deadline_confidence_band"
        ),
        sa.CheckConstraint(
            "created_by IN ('agent','user','rule')", name="deadline_created_by"
        ),
        # The honesty constraint. A row that claims to be resolved must
        # carry a date; a row with no date may not claim to be resolved.
        # Without this, "resolved" degrades into a label nobody can trust.
        sa.CheckConstraint(
            "(resolution_status IN ('resolved','user_confirmed','user_corrected')) "
            "= (normalized_date IS NOT NULL)",
            name="deadline_resolved_has_a_date",
        ),
    )
    op.create_index(
        "ix_deadlines_live",
        "deadlines",
        ["user_id", "normalized_date"],
        postgresql_where=sa.text("superseded_by IS NULL AND is_for_user"),
    )
    op.create_index("ix_deadlines_thread", "deadlines", ["thread_id"])

    # ---------------------------------------------------------- action_items
    op.create_table(
        "action_items",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "thread_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("email_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id", pg.UUID(as_uuid=True), sa.ForeignKey("email_messages.id")
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        # Never conflated. The interface renders the two differently and
        # the eval scores them separately.
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("evidence_char_start", sa.Integer()),
        sa.Column("evidence_char_end", sa.Integer()),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("agent_run_id", pg.UUID(as_uuid=True)),
        sa.Column("content_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "owner IN ('user','sender','other','unclear')", name="action_owner_known"
        ),
        sa.CheckConstraint("source IN ('stated','inferred')", name="action_source_known"),
        sa.CheckConstraint(
            "status IN ('open','done','dismissed')", name="action_status_known"
        ),
        sa.CheckConstraint("created_by IN ('agent','user')", name="action_created_by"),
        # A stated item is one the email actually contains, so it must be
        # able to point at the words. An inferred one is honest about
        # having none.
        sa.CheckConstraint(
            "source <> 'stated' OR created_by <> 'agent' "
            "OR (evidence_char_start IS NOT NULL AND evidence_char_end IS NOT NULL)",
            name="action_stated_has_evidence",
        ),
    )
    op.create_index(
        "ix_actions_open",
        "action_items",
        ["user_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index("ix_actions_thread", "action_items", ["thread_id"])

    # ----------------------------------------------------------------- tasks
    op.create_table(
        "tasks",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "thread_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("email_threads.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "action_item_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("action_items.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "deadline_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("deadlines.id", ondelete="SET NULL"),
        ),
        sa.Column("due_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column("remind_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("origin", sa.Text(), nullable=False),
        # An AI suggestion is not a task until confirmed.
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "origin IN ('user','ai_suggestion','sender_request')", name="task_origin_known"
        ),
        sa.CheckConstraint(
            "status IN ('pending','done','dismissed')", name="task_status_known"
        ),
        # A task the user created is confirmed by the act of creating it.
        sa.CheckConstraint(
            "origin <> 'user' OR confirmed_at IS NOT NULL", name="task_user_origin_confirmed"
        ),
        # One task per suggestion, so re-running an agent cannot produce a
        # second copy of the same commitment.
        sa.UniqueConstraint("action_item_id", name="uq_task_per_action_item"),
    )
    op.create_index(
        "ix_tasks_due",
        "tasks",
        ["user_id", "due_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # ------------------------------------------------------------------- RLS
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
        # FORCE applies to the table owner too, so migrations and the seed
        # need a role-scoped way through. Discovered the hard way in 0001.
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
              thread_insights, deadlines, action_items, tasks TO {APP_ROLE};
          END IF;
        END
        $grants$
        """
    )


def downgrade() -> None:
    op.drop_table("tasks")
    op.drop_table("action_items")
    op.drop_table("deadlines")
    op.drop_table("thread_insights")
    op.execute("DROP TYPE IF EXISTS date_resolution")
    op.execute("DROP TYPE IF EXISTS date_type")
