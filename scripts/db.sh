#!/usr/bin/env bash
# ./scripts/db.sh [migrate|verify|seed|reset|revision|psql|shell]
#
# Everything here connects as the OWNER role. The application never does — that
# split is what makes FORCE ROW LEVEL SECURITY inescapable.

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

load_env
CMD="${1:-verify}"
shift || true

in_db() { compose exec -T db "$@"; }

wait_for_db() {
  local tries=40
  until in_db pg_isready -U "${POSTGRES_OWNER_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; do
    ((tries--)) || die "Postgres did not become ready. ./scripts/dev.sh logs db"
    sleep 1
  done
}

alembic() { cd "$BACKEND" && pym alembic "$@"; }

case "$CMD" in
  migrate)
    step "alembic upgrade head"
    alembic upgrade head
    ok "schema at head"
    ;;

  verify)
    step "schema audit"
    cd "$BACKEND"
    pym app.database.audit
    ok "every user-scoped table has RLS enabled, FORCEd and a policy"
    ;;

  seed)
    step "seeding development fixtures"
    cd "$BACKEND"
    pym app.database.seed
    ;;

  reset)
    printf '%s\n' "${YELLOW}This drops the ${POSTGRES_DB} schema and every row in it.${RESET}"
    read -r -p "Type the database name to confirm: " answer
    [[ "$answer" == "${POSTGRES_DB}" ]] || die "aborted"
    step "downgrade to base"
    alembic downgrade base || warn "downgrade failed; dropping schema instead"
    in_db psql -U "${POSTGRES_OWNER_USER}" -d "${POSTGRES_DB}" \
      -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;' >/dev/null
    in_db psql -U "${POSTGRES_OWNER_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 \
      -c "GRANT USAGE ON SCHEMA public TO ${POSTGRES_APP_USER};
          ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${POSTGRES_APP_USER};
          ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT USAGE, SELECT ON SEQUENCES TO ${POSTGRES_APP_USER};
          ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT EXECUTE ON FUNCTIONS TO ${POSTGRES_APP_USER};" >/dev/null
    "$0" migrate
    "$0" seed
    "$0" verify
    ;;

  revision)
    [[ $# -gt 0 ]] || usage_and_exit 'usage: db.sh revision "what this migration does"'
    step "alembic revision --autogenerate"
    alembic revision --autogenerate -m "$*"
    warn "read the generated file before committing it"
    hint "every new user-scoped table needs ENABLE + FORCE RLS and a tenant_isolation policy"
    ;;

  psql|shell)
    wait_for_db
    compose exec db psql -U "${POSTGRES_OWNER_USER}" -d "${POSTGRES_DB}"
    ;;

  -h|--help|help)
    usage_and_exit "usage: db.sh [migrate|verify|seed|reset|revision <msg>|psql]"
    ;;
  *) usage_and_exit "unknown command: $CMD" ;;
esac
