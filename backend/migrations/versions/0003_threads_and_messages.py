"""Threads, messages and attachment metadata.

Revision ID: 0003
Revises: 0002
Create Date: phase 2

The thread is the unit of meaning, so ``email_threads.id`` is the anchor and
``provider_thread_id`` is a mutable attribute. Gmail splits threads on a
subject change and above a size cap, and regroups messages retroactively, so
anything keyed on the provider's id would be rebuilt every time it changed
its mind (gap A5).

Three columns are not in 02-lld-data-model.md and are added because §3 of
04-lld-api-sync-modules.md needs them:

``email_messages.deleted_at``            delta sync soft-deletes locally
``email_messages.body_fetch_attempts``   bounded retries, so one bad message
``email_messages.last_fetch_error``      never fails a batch (gap A7)

Raw HTML is deliberately not a column (gap E6): it is the largest single item
in both the database and the breach surface, and bodies render from an
on-demand fetch instead.

Downgrade drops the mail. From here on that is a data-loss operation, so it
is development-only: in production, restore from a backup and re-sync rather
than downgrading.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

APP_ROLE = "maail_app"
RLS_TABLES = ("email_threads", "email_messages", "message_attachments")


def upgrade() -> None:
    op.create_table(
        "email_threads",
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
            "account_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("connected_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_thread_id", sa.Text(), nullable=False),
        # Set when Gmail merges this thread into another. The row stays, so
        # intelligence already derived against it keeps its audit trail.
        sa.Column(
            "merged_into_thread_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("email_threads.id"),
        ),
        sa.Column("subject", sa.Text()),
        # re:/fwd: stripped, for merge detection.
        sa.Column("subject_normalized", sa.Text()),
        sa.Column(
            "participant_emails",
            pg.ARRAY(pg.CITEXT()),
            nullable=False,
            server_default=sa.text("'{}'::citext[]"),
        ),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("unread_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "has_attachments", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "provider_labels",
            pg.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("first_message_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("latest_message_at", sa.TIMESTAMP(timezone=True)),
        # Bumped on every ingested message. Everything derived from the
        # thread carries the version it was derived at, so a stale summary
        # is detectable rather than merely old.
        sa.Column("content_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("search_tsv", pg.TSVECTOR()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("account_id", "provider_thread_id", name="uq_threads_provider"),
    )

    op.create_table(
        "email_messages",
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
            "account_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("connected_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "thread_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("email_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_message_id", sa.Text(), nullable=False),
        # The RFC-822 id survives provider re-threading; the provider's own
        # id does not (gap A5).
        sa.Column("rfc822_message_id", sa.Text()),
        sa.Column("in_reply_to", sa.Text()),
        sa.Column("references_ids", pg.ARRAY(sa.Text())),
        sa.Column("from_email", pg.CITEXT()),
        sa.Column("from_name", sa.Text()),
        sa.Column(
            "to_emails",
            pg.ARRAY(pg.CITEXT()),
            nullable=False,
            server_default=sa.text("'{}'::citext[]"),
        ),
        sa.Column(
            "cc_emails",
            pg.ARRAY(pg.CITEXT()),
            nullable=False,
            server_default=sa.text("'{}'::citext[]"),
        ),
        sa.Column("subject", sa.Text()),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=False),
        # From the Date header. A deadline of "tomorrow" means the sender's
        # tomorrow, not the server's (gap E2).
        sa.Column("sender_tz_offset_min", sa.Integer()),
        sa.Column("snippet", sa.Text()),
        sa.Column("body_text", sa.Text()),
        # Filled by the quote stripper in phase 3. The largest single lever
        # on token cost, so it gets its own column and its own measurement.
        sa.Column("body_text_stripped", sa.Text()),
        sa.Column("stripped_ratio", sa.REAL()),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column(
            "is_from_user", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "provider_labels",
            pg.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        # NULL means metadata-only: pass 1 has seen it, pass 2 has not.
        sa.Column("body_fetched_at", sa.TIMESTAMP(timezone=True)),
        # Gap A7: one unfetchable message must not fail a batch for ever.
        sa.Column(
            "body_fetch_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("last_fetch_error", sa.Text()),
        # Delta sync soft-deletes; Gmail's delete may be a user mistake, and
        # a local row is cheap next to re-syncing a mailbox.
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Dedupe in the database, not in code. Two workers racing the same
        # message resolve here rather than writing it twice.
        sa.UniqueConstraint("account_id", "provider_message_id", name="uq_messages_provider"),
    )

    op.create_table(
        "message_attachments",
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
            "message_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("email_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.Text()),
        sa.Column("mime_type", sa.Text()),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("provider_attachment_id", sa.Text()),
        # Gap D6: metadata only. No content, no parsing, in v1.
        sa.UniqueConstraint("message_id", "provider_attachment_id", name="uq_attachment_provider"),
    )

    # --- indexes ----------------------------------------------------------
    # Cursor pagination for the inbox: (latest_message_at DESC, id DESC) is
    # the sort, so it is also the index (gap E5).
    op.create_index(
        "ix_threads_inbox",
        "email_threads",
        ["user_id", sa.text("latest_message_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_threads_account",
        "email_threads",
        ["account_id", sa.text("latest_message_at DESC")],
    )
    op.create_index("ix_threads_tsv", "email_threads", ["search_tsv"], postgresql_using="gin")
    op.create_index(
        "ix_threads_participants",
        "email_threads",
        ["participant_emails"],
        postgresql_using="gin",
    )
    op.create_index("ix_messages_thread", "email_messages", ["thread_id", "sent_at"])
    op.create_index(
        "ix_messages_from", "email_messages", ["user_id", "from_email", sa.text("sent_at DESC")]
    )
    # Pass 2 asks this exactly once per batch: what still needs a body?
    op.create_index(
        "ix_messages_needs_body",
        "email_messages",
        ["account_id", sa.text("sent_at DESC")],
        postgresql_where=sa.text("body_fetched_at IS NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_messages_rfc822",
        "email_messages",
        ["account_id", "rfc822_message_id"],
        postgresql_where=sa.text("rfc822_message_id IS NOT NULL"),
    )
    op.create_index("ix_attachments_message", "message_attachments", ["message_id"])

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

    # --- search vector -----------------------------------------------------
    # Subject outranks body, body outranks participants. Built from the
    # stripped text, so a quoted chain does not pollute relevance -- the
    # column that saves tokens also improves search.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION refresh_thread_tsv(p_thread_id uuid) RETURNS void
        LANGUAGE sql AS $fn$
          UPDATE email_threads t SET search_tsv =
              setweight(to_tsvector('english', coalesce(t.subject, '')), 'A')
           || setweight(to_tsvector('english',
                coalesce((SELECT string_agg(
                            coalesce(m.body_text_stripped, m.body_text, m.snippet), ' ')
                            FROM email_messages m
                           WHERE m.thread_id = t.id AND m.deleted_at IS NULL), '')), 'B')
           || setweight(to_tsvector('simple',
                array_to_string(t.participant_emails::text[], ' ')), 'C')
          WHERE t.id = p_thread_id;
        $fn$
        """
    )

    op.execute(
        f"""
        DO $grants$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON
              email_threads, email_messages, message_attachments TO {APP_ROLE};
            GRANT EXECUTE ON FUNCTION refresh_thread_tsv(uuid) TO {APP_ROLE};
          END IF;
        END
        $grants$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS refresh_thread_tsv(uuid)")
    op.drop_table("message_attachments")
    op.drop_table("email_messages")
    op.drop_table("email_threads")
