"""Identity and the tenancy boundary.

Revision ID: 0001
Revises:
Create Date: phase 0

Creates ``users``, the ``app_current_user()`` accessor, and row-level security
on ``users`` with FORCE. ``users`` is the one user-scoped table with no
``user_id`` column, so its policy compares ``id``; every later table gets the
``tenant_isolation`` policy from 02-lld-data-model.md §8 instead.

Downgrade drops all of it, which is safe only because phase 0 holds no data
worth keeping. From phase 1 on, a downgrade that loses mail is a documented
recovery procedure, not a DROP.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE_PLACEHOLDER = "maail_app"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")
    # pgvector deliberately absent — see 00-gap-analysis.md §1 gap 6.

    op.create_table(
        "users",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", pg.CITEXT(), nullable=False, unique=True),
        sa.Column("name", sa.Text()),
        sa.Column("timezone", sa.Text(), nullable=False, server_default=sa.text("'UTC'")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index("ix_users_active", "users", ["email"], postgresql_where=sa.text(
        "deleted_at IS NULL"
    ))

    # --- the tenant accessor ---------------------------------------------
    # STABLE, not IMMUTABLE: it reads a session setting. Marking it IMMUTABLE
    # would let the planner cache it across a changed setting.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_current_user() RETURNS uuid
        LANGUAGE sql STABLE AS $fn$
          SELECT nullif(current_setting('app.user_id', true), '')::uuid
        $fn$
        """
    )

    # --- row level security ----------------------------------------------
    # FORCE matters: without it the table owner is exempt from its own policy,
    # and migrations run as the owner.
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON users
          USING (id = app_current_user())
          WITH CHECK (id = app_current_user())
        """
    )

    # FORCE applies the policy to the table owner as well, which is the whole
    # point -- and it means the owner cannot insert a user either. Signup,
    # session resolution and the development seed all have to write a row
    # before any tenant exists, so the owner gets its own permissive policy.
    #
    # This does not loosen anything for the application. Policies are
    # additive but role-scoped: `maail_app` does not match `TO maail_owner`,
    # so tenant_isolation is still the only policy it is judged against. The
    # owner is the migration role and was already trusted with the schema.
    op.execute(
        """
        DO $owner_policy$
        BEGIN
          EXECUTE 'CREATE POLICY owner_bootstrap ON users TO ' ||
                  quote_ident(current_user) || ' USING (true) WITH CHECK (true)';
        END
        $owner_policy$
        """
    )

    # Row creation happens before a session exists, so signup is the one write
    # that cannot satisfy the policy. It runs as the owner, through a function
    # the application role may execute but whose body it cannot change.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_create_user(
          p_email citext, p_name text, p_timezone text DEFAULT 'UTC'
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $fn$
        DECLARE new_id uuid;
        BEGIN
          INSERT INTO users (email, name, timezone)
          VALUES (p_email, p_name, coalesce(p_timezone, 'UTC'))
          ON CONFLICT (email) DO UPDATE SET name = coalesce(excluded.name, users.name)
          RETURNING id INTO new_id;
          RETURN new_id;
        END
        $fn$
        """
    )

    # --- privileges -------------------------------------------------------
    # The init script sets default privileges for future tables; this makes the
    # migration self-sufficient for a database created some other way.
    op.execute(
        f"""
        DO $grants$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE_PLACEHOLDER}') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON users TO {APP_ROLE_PLACEHOLDER};
            GRANT EXECUTE ON FUNCTION app_current_user() TO {APP_ROLE_PLACEHOLDER};
            GRANT EXECUTE ON FUNCTION app_create_user(citext, text, text)
              TO {APP_ROLE_PLACEHOLDER};
          END IF;
        END
        $grants$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_create_user(citext, text, text)")
    op.execute("DROP POLICY IF EXISTS owner_bootstrap ON users")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON users")
    op.drop_index("ix_users_active", table_name="users")
    op.drop_table("users")
    op.execute("DROP FUNCTION IF EXISTS app_current_user()")
