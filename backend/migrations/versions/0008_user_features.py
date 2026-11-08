"""Feature toggles and their per-feature configuration.

Revision ID: 0008
Revises: 0007
Create Date: phase 11

One row per feature the user has *touched*. Absence means "the default",
which is deliberate: the defaults live in Git (``features/registry.py``)
where they are reviewable in a diff, and a user who never opened settings
has no rows at all. Writing seventeen rows per signup to say "yes, the
defaults" would make the defaults unchangeable in practice -- every
existing user would be pinned to whatever they were on the day they
registered.

``updated_at`` is load-bearing beyond auditing. The API and the worker are
separate processes with separate caches, and a disabled feature that keeps
running in the worker for thirty seconds is the gate failing quietly. So a
cached config carries the watermark it was loaded at, and one index-only
probe of ``max(updated_at)`` tells a second process that its copy is
stale. See ``features/service.py``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

APP_ROLE = "maail_app"


def upgrade() -> None:
    op.create_table(
        "user_features",
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("feature_id", sa.Text(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        # Validated against the feature's own schema before it is written.
        # Unknown keys are dropped rather than stored, so a config blob
        # cannot accumulate settings nothing reads.
        sa.Column("config", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # The staleness probe reads this and nothing else, so it stays an
    # index-only scan however many features a user has set.
    op.create_index(
        "ix_user_features_watermark", "user_features", ["user_id", "updated_at"]
    )

    op.execute("ALTER TABLE user_features ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_features FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON user_features
          USING (user_id = app_current_user())
          WITH CHECK (user_id = app_current_user())
        """
    )
    op.execute(
        """
        DO $owner_policy$
        BEGIN
          EXECUTE 'CREATE POLICY owner_bootstrap ON user_features TO ' ||
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
            GRANT SELECT, INSERT, UPDATE, DELETE ON user_features TO {APP_ROLE};
          END IF;
        END
        $grants$
        """
    )


def downgrade() -> None:
    op.drop_table("user_features")
