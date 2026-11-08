"""Connected accounts, encrypted credentials, sessions and OAuth state.

Revision ID: 0002
Revises: 0001
Create Date: phase 1

Three things here are load-bearing and easy to get subtly wrong:

1. ``oauth_credentials`` stores ciphertext and a wrapped data key, never a
   token. ``key_version`` is what makes the key rotatable (gap D8); a column
   added later is a migration over encrypted data nobody wants to run.

2. ``refresh_expires_at`` exists because Google expires a Testing-mode refresh
   token after about seven days (gap A3). Storing it lets the UI warn before
   the token dies instead of after a sync fails.

3. ``sessions`` carries ``user_id`` so RLS covers it, but a session lookup
   happens *before* a tenant is known, and RLS would return nothing. The
   lookup therefore goes through ``app_resolve_session``, a SECURITY DEFINER
   function the application may execute but cannot rewrite -- the same shape
   as ``app_create_user`` in 0001.

``oauth_states`` deliberately has no ``user_id`` and no ``account_id``. It is
a single-use nonce ledger and nothing more; which account a reconnect is for
travels in the signed, httpOnly flow cookie, where it cannot be read or
tampered with, and is re-checked against the session at callback.

Downgrade drops all of it. Phase 1 holds credentials rather than mail, and a
dropped credential costs one re-authorisation, so the destructive downgrade is
still the honest one. From phase 2, when mail lands, it will not be.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APP_ROLE = "maail_app"

RLS_TABLES = ("connected_accounts", "oauth_credentials", "sessions")


def upgrade() -> None:
    # create_type=False matters: the type is created once, explicitly, just
    # below. Leaving it True makes create_table try again inside the same
    # transaction and fail with DuplicateObject.
    account_status = pg.ENUM(
        "connecting",
        "active",
        "reauth_required",
        "disconnected",
        "error",
        name="account_status",
        create_type=False,
    )
    account_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "connected_accounts",
        sa.Column(
            "id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_email", pg.CITEXT(), nullable=False),
        sa.Column("status", account_status, nullable=False, server_default=sa.text("'connecting'")),
        sa.Column(
            "granted_scopes",
            pg.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        # Sync cursors. Written from phase 2; the columns exist now so that
        # phase is a code change rather than a migration over live mail.
        sa.Column("history_cursor", sa.Text()),
        sa.Column("history_cursor_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("initial_sync_total", sa.Integer()),
        sa.Column("initial_sync_done", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_delta_sync_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("disconnected_at", sa.TIMESTAMP(timezone=True)),
        # 30-day soft delete, or immediate on request (open decision O5).
        sa.Column("purge_after", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint("provider IN ('gmail')", name="provider_supported"),
        sa.UniqueConstraint(
            "user_id", "provider", "provider_account_email", name="uq_connected_accounts_identity"
        ),
    )
    op.create_index(
        "ix_connected_accounts_user_status", "connected_accounts", ["user_id", "status"]
    )
    op.create_index(
        "ix_connected_accounts_purge",
        "connected_accounts",
        ["purge_after"],
        postgresql_where=sa.text("purge_after IS NOT NULL"),
    )

    op.create_table(
        "oauth_credentials",
        sa.Column(
            "account_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("connected_accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Ciphertext, not tokens. A SELECT * in a support session shows bytes.
        sa.Column("access_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("dek_wrapped", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("access_expires_at", sa.TIMESTAMP(timezone=True)),
        # Gap A3: about seven days while the OAuth app is in Testing mode.
        sa.Column("refresh_expires_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index("ix_oauth_credentials_user", "oauth_credentials", ["user_id"])
    op.create_index(
        "ix_oauth_credentials_refresh_expiry",
        "oauth_credentials",
        ["refresh_expires_at"],
        postgresql_where=sa.text("refresh_expires_at IS NOT NULL"),
    )

    op.create_table(
        "sessions",
        sa.Column(
            "id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # sha256 of the cookie value. The cookie itself is never stored, so a
        # database dump does not hand anyone a working session.
        sa.Column("token_hash", sa.LargeBinary(32), nullable=False, unique=True),
        sa.Column("user_agent", sa.Text()),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "last_seen_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index("ix_sessions_user", "sessions", ["user_id"])
    op.create_index("ix_sessions_expiry", "sessions", ["expires_at"])

    # A single-use nonce ledger. No user_id, no account_id: it is written
    # before anyone is authenticated, and holding identity here would mean
    # either an unprotected user-scoped table or a policy that cannot be
    # satisfied. What the flow is for travels in the signed cookie instead.
    op.create_table(
        "oauth_states",
        sa.Column("state_hash", sa.LargeBinary(32), primary_key=True),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint("purpose IN ('signin', 'reconnect')", name="purpose_known"),
    )
    op.create_index("ix_oauth_states_expiry", "oauth_states", ["expires_at"])

    # --- row level security ----------------------------------------------
    #
    # Two policies per table, and the distinction matters.
    #
    # `tenant_isolation` is the one that protects anything: the application
    # connects as a non-owner role, matches only this policy, and cannot see
    # or write another tenant's row.
    #
    # `owner_bootstrap` exists because FORCE applies policies to the table
    # owner as well. The owner is the maintenance role -- it runs migrations,
    # re-wraps data keys during a key rotation, and purges disconnected
    # accounts, all of which are cross-tenant by nature. Without this the
    # owner would silently match zero rows, which is worse than having no
    # policy at all: a maintenance job would appear to succeed having done
    # nothing. It is role-scoped, so it does not widen what the application
    # can reach.
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

    # --- session resolution, before a tenant exists -----------------------
    # Returns the owner of a live session and stamps last_seen_at. Takes the
    # hash, never the cookie, so the caller has already thrown the secret away.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_resolve_session(p_token_hash bytea)
        RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $fn$
        DECLARE resolved uuid;
        BEGIN
          UPDATE sessions
             SET last_seen_at = now()
           WHERE token_hash = p_token_hash
             AND revoked_at IS NULL
             AND expires_at > now()
          RETURNING user_id INTO resolved;
          RETURN resolved;
        END
        $fn$
        """
    )

    # Creating a session is the same chicken and egg: the row must exist
    # before the policy it would have to satisfy can be armed.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_create_session(
          p_user_id uuid, p_token_hash bytea, p_user_agent text, p_ttl interval
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $fn$
        DECLARE new_id uuid;
        BEGIN
          INSERT INTO sessions (user_id, token_hash, user_agent, expires_at)
          VALUES (p_user_id, p_token_hash, left(coalesce(p_user_agent, ''), 300),
                  now() + p_ttl)
          RETURNING id INTO new_id;
          RETURN new_id;
        END
        $fn$
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_revoke_session(p_token_hash bytea)
        RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $fn$
        DECLARE hit uuid;
        BEGIN
          UPDATE sessions SET revoked_at = now()
           WHERE token_hash = p_token_hash AND revoked_at IS NULL
          RETURNING id INTO hit;
          RETURN hit IS NOT NULL;
        END
        $fn$
        """
    )

    # --- privileges -------------------------------------------------------
    op.execute(
        f"""
        DO $grants$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON
              connected_accounts, oauth_credentials, sessions, oauth_states
              TO {APP_ROLE};
            GRANT EXECUTE ON FUNCTION app_resolve_session(bytea) TO {APP_ROLE};
            GRANT EXECUTE ON FUNCTION app_create_session(uuid, bytea, text, interval)
              TO {APP_ROLE};
            GRANT EXECUTE ON FUNCTION app_revoke_session(bytea) TO {APP_ROLE};
          END IF;
        END
        $grants$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_revoke_session(bytea)")
    op.execute("DROP FUNCTION IF EXISTS app_create_session(uuid, bytea, text, interval)")
    op.execute("DROP FUNCTION IF EXISTS app_resolve_session(bytea)")
    op.drop_table("oauth_states")
    op.drop_table("sessions")
    op.drop_table("oauth_credentials")
    op.drop_table("connected_accounts")
    op.execute("DROP TYPE IF EXISTS account_status")
