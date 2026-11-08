"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Checklist before committing this migration:
  - downgrade() is implemented, or a recovery procedure is documented here
  - every new user-scoped table has ENABLE + FORCE ROW LEVEL SECURITY and a
    tenant_isolation policy  (tests/arch/test_schema_audit.py enforces this)
  - indexes exist for the access patterns the LLD names
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
