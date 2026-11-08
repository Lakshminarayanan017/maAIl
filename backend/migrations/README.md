# migrations

Alembic. Connects as the **owner** role; the application never does.

- `./scripts/db.sh migrate` applies everything
- `./scripts/db.sh verify` asserts the schema matches the model metadata **and** that
  every user-scoped table has RLS enabled, FORCEd, and a policy
- `./scripts/db.sh reset` drops and rebuilds — development only

Every migration needs a `downgrade()` or a recovery procedure written in its docstring.
CI rejects one with neither.
