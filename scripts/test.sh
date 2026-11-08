#!/usr/bin/env bash
# ./scripts/test.sh [unit|integration|security|arch|frontend|all] [-- pytest args]
#
# arch and unit need nothing but Python. integration and security need Postgres,
# and skip with a stated reason when it is not up rather than failing opaquely.

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

TARGET="${1:-unit}"
shift || true
[[ "${1:-}" == "--" ]] && shift

load_env

run_pytest() {
  cd "$BACKEND"
  step "pytest $*"
  pym pytest -q --no-header "$@"
}

case "$TARGET" in
  unit)        run_pytest -m "not integration and not arch" "$@" ;;
  arch)        run_pytest -m arch --deselect tests/arch/test_schema_audit.py "$@" ;;
  integration) run_pytest -m integration "$@" ;;
  security)    run_pytest -m security "$@" ;;
  frontend)
    [[ -d "$FRONTEND/node_modules" ]] || die "frontend/node_modules missing — cd frontend && npm install"
    cd "$FRONTEND" && step "vitest" && npm run --silent test
    ;;
  all)
    cd "$BACKEND"
    step "pytest (everything)"
    pym pytest -q --no-header "$@"
    if [[ -d "$FRONTEND/node_modules" ]]; then
      cd "$FRONTEND" && step "vitest" && npm run --silent test
    else
      warn "frontend/node_modules missing — skipping frontend tests"
    fi
    ;;
  -h|--help|help)
    usage_and_exit "usage: test.sh [unit|integration|security|arch|frontend|all] [-- pytest args]"
    ;;
  *) usage_and_exit "unknown target: $TARGET" ;;
esac
