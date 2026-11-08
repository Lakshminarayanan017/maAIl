#!/usr/bin/env bash
# Format, types, lint, architecture boundaries. One command before you push.
#
#   ./scripts/check.sh            everything
#   ./scripts/check.sh --fix      format and autofix first
#   ./scripts/check.sh backend    backend only
#   ./scripts/check.sh frontend   frontend only

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

FIX=0
TARGET="all"
for arg in "$@"; do
  case "$arg" in
    --fix) FIX=1 ;;
    backend|frontend|all) TARGET="$arg" ;;
    -h|--help) usage_and_exit "usage: check.sh [--fix] [backend|frontend|all]" ;;
    *) usage_and_exit "unknown argument: $arg" ;;
  esac
done

FAILURES=()
run() {
  local label="$1"; shift
  step "$label"
  if "$@"; then ok "$label"; else FAILURES+=("$label"); printf '%s\n' "${RED}fail${RESET} $label"; fi
}

if [[ "$TARGET" == "all" || "$TARGET" == "backend" ]]; then
  cd "$BACKEND"
  if [[ $FIX -eq 1 ]]; then
    run "ruff format"      pym ruff format .
    run "ruff --fix"       pym ruff check --fix .
  fi
  run "ruff format --check" pym ruff format --check .
  run "ruff lint"           pym ruff check .
  run "mypy"                pym mypy app
  # The architecture rules are the point of this script. They need no database.
  run "architecture"        pym pytest -q -m arch -p no:cacheprovider --no-header \
                                       --deselect tests/arch/test_schema_audit.py
fi

if [[ "$TARGET" == "all" || "$TARGET" == "frontend" ]]; then
  if [[ -d "$FRONTEND/node_modules" ]]; then
    cd "$FRONTEND"
    if [[ $FIX -eq 1 ]]; then
      run "prettier --write" npm run --silent format
      run "eslint --fix"     npm run --silent lint:fix
    fi
    run "prettier --check" npm run --silent format:check
    run "eslint"           npm run --silent lint
    run "tsc"              npm run --silent typecheck
  else
    warn "frontend/node_modules missing — skipping frontend checks"
    hint "cd frontend && npm install"
  fi
fi

printf '\n'
if (( ${#FAILURES[@]} )); then
  die "failed: ${FAILURES[*]}"
fi
say "${GREEN}all checks passed${RESET}"
