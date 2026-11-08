"""User rules and user corrections.

Revision ID: 0005
Revises: 0004
Create Date: phase 6

``user_rules`` runs **before** the agent. A rule is the user having already
answered the question, and asking a model to second-guess an explicit
instruction is both expensive and rude (gap E4).

``user_overrides`` records every correction. Two reasons, and the second
one is the point: it is the audit trail for why a thread is filed where it
is, and it is the raw material for suggesting a rule. "You have moved three
emails from this sender to Promotions -- always do that?" is only possible
if the corrections were kept.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

APP_ROLE = "maail_app"
RLS_TABLES = ("user_rules", "user_overrides")


def upgrade() -> None:
    op.create_table(
        "user_rules",
        sa.Column(
            "id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("100")),
        # {from_domain, from_email, subject_contains, body_contains, has_label}
        sa.Column("match", pg.JSONB(), nullable=False),
        # {set_category, set_priority, add_label, skip_intelligence}
        sa.Column("action", pg.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        # Born from a correction, so the suggestion can point at the thing
        # the person actually did.
        sa.Column("derived_from_override_id", pg.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index(
        "ix_rules_active", "user_rules", ["user_id", "priority"], postgresql_where=sa.text("enabled")
    )

    op.create_table(
        "user_overrides",
        sa.Column(
            "id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "thread_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("email_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("old_value", pg.JSONB()),
        sa.Column("new_value", pg.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(
            "field IN ('category','priority','needs_reply','deadline')", name="override_field_known"
        ),
    )
    op.create_index(
        "ix_overrides_user", "user_overrides", ["user_id", sa.text("created_at DESC")]
    )

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

    op.execute(
        f"""
        DO $grants$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON user_rules, user_overrides TO {APP_ROLE};
          END IF;
        END
        $grants$
        """
    )


def downgrade() -> None:
    op.drop_table("user_overrides")
    op.drop_table("user_rules")
