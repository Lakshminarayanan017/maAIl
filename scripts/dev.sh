#!/usr/bin/env bash
# ./scripts/dev.sh [up|down|doctor|logs|restart|bootstrap]
#
# `up` must work from a clean clone. That is a phase 0 blocking gate, so it
# creates .env, starts Postgres, waits for it, migrates, seeds and verifies
# before claiming anything is running.

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

CMD="${1:-up}"
shift || true

# --- doctor -----------------------------------------------------------------
doctor() {
  local problems=0
  step "environment"

  # Docker is the supported way to run the stack, but what actually matters
  # is a Postgres the application can reach. A locally installed server
  # counts; it is `dev.sh up` that needs Compose.
  local db_reachable=0
  if [[ -n "$PY" ]] && "$PY" -c "
import os, socket, sys
host = os.environ.get('POSTGRES_HOST', 'localhost')
port = int(os.environ.get('POSTGRES_PORT', '5432'))
try:
    socket.create_connection((host, port), timeout=2).close()
except OSError:
    sys.exit(1)
" >/dev/null 2>&1; then
    db_reachable=1
    ok "Postgres reachable at ${POSTGRES_HOST:-localhost}:${POSTGRES_PORT:-5432}"
  fi

  if have docker && docker info >/dev/null 2>&1; then
    ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo running)"
    if docker compose version >/dev/null 2>&1; then
      ok "docker compose $(docker compose version --short 2>/dev/null)"
    elif have docker-compose; then
      ok "docker-compose (v1) — works, but v2 is what the file is written for"
    else
      printf '%s docker compose not found
' "${RED}fail${RESET}"
      problems=$((problems + 1))
    fi
  elif (( db_reachable )); then
    warn "docker not available — ./scripts/dev.sh up cannot start the stack"
    hint "migrations and tests work against the Postgres already running"
    hint "serve the API with: cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload"
  else
    printf '%s no database, and no docker to start one
' "${RED}fail${RESET}"
    hint "install Docker Desktop (https://docs.docker.com/get-docker/), or"
    hint "install Postgres 16+ locally and point .env at it"
    problems=$((problems + 1))
  fi

  if [[ -n "$PY" ]]; then
    local pyver; pyver="$("$PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
    if "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
      ok "python $pyver  ($PY)"
    else
      printf '%s python %s is below the 3.10 minimum\n' "${RED}fail${RESET}" "$pyver"
      problems=$((problems + 1))
    fi
    if "$PY" -c 'import fastapi, sqlalchemy, alembic' >/dev/null 2>&1; then
      ok "backend dependencies importable"
    else
      warn "backend dependencies not installed in $PY"
      hint "./scripts/dev.sh bootstrap   (creates backend/.venv and installs)"
    fi
  else
    printf '%s python not found\n' "${RED}fail${RESET}"
    problems=$((problems + 1))
  fi

  if have node; then
    local nodever; nodever="$(node --version)"
    if node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)'; then
      ok "node $nodever"
    else
      printf '%s node %s is below the v20 minimum\n' "${RED}fail${RESET}" "$nodever"
      problems=$((problems + 1))
    fi
  else
    printf '%s node not found\n' "${RED}fail${RESET}"
    problems=$((problems + 1))
  fi

  [[ -d "$FRONTEND/node_modules" ]] && ok "frontend dependencies installed" \
    || warn "frontend/node_modules missing — cd frontend && npm install"

  step "configuration"
  if [[ -f "$REPO_ROOT/.env" ]]; then
    ok ".env present"
    if grep -q 'change_me' "$REPO_ROOT/.env"; then
      warn ".env still has placeholder secrets — fine for development, fatal in production"
    fi

    # shellcheck disable=SC1091
    set -a; source "$REPO_ROOT/.env"; set +a

    if [[ -n "${DATA_ENCRYPTION_KEYS:-}" ]]; then
      ok "credential encryption key present"
    else
      printf '%s DATA_ENCRYPTION_KEYS is unset; credentials cannot be sealed
' "${RED}fail${RESET}"
      hint "generate one with: cd backend && python -m app.core.crypto"
      problems=$((problems + 1))
    fi

    if [[ -n "${GOOGLE_CLIENT_ID:-}" && -n "${GOOGLE_CLIENT_SECRET:-}" ]]; then
      ok "Google OAuth configured"
    else
      warn "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET unset — the app runs, but Get started returns 503"
      hint "console.cloud.google.com → OAuth client → Web application"
      hint "authorised redirect URI: ${GOOGLE_REDIRECT_URI:-http://localhost:8000/api/v1/auth/google/callback}"
    fi
  else
    warn ".env missing — ./scripts/dev.sh up creates it from .env.example"
  fi

  step "architecture"
  if [[ -n "$PY" ]]; then
    (cd "$BACKEND" && "$PY" -m tests.arch.boundaries) && ok "boundaries clean" \
      || { printf '%s architecture violations above\n' "${RED}fail${RESET}"; problems=$((problems + 1)); }
  fi

  printf '\n'
  if ((problems > 0)); then
    die "$problems problem(s) — fix the failures above, warnings are optional"
  fi
  say "${GREEN}ready${RESET}"
}

# --- bootstrap --------------------------------------------------------------
bootstrap() {
  step "backend virtualenv"
  if [[ ! -d "$BACKEND/.venv" ]]; then
    "${PY:-python}" -m venv "$BACKEND/.venv" || die "could not create backend/.venv"
  fi
  PY="$(venv_python)" || die "virtualenv created but no interpreter in it"
  ok "$PY"
  pym pip install --quiet --upgrade pip
  step "backend dependencies"
  (cd "$BACKEND" && "$PY" -m pip install --quiet -e ".[dev]") || die "pip install failed"
  ok "installed"

  if have node; then
    step "frontend dependencies"
    (cd "$FRONTEND" && npm install --no-fund --no-audit) || die "npm install failed"
    ok "installed"
  fi
  say "bootstrap complete — ./scripts/dev.sh up"
}

wait_for_db() {
  step "waiting for Postgres"
  local tries=60
  until compose exec -T db pg_isready -U "${POSTGRES_OWNER_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; do
    ((tries--)) || die "Postgres did not become ready — ./scripts/dev.sh logs db"
    printf '.'
    sleep 1
  done
  printf '\n'; ok "Postgres accepting connections"
}

case "$CMD" in
  up)
    ensure_env_file
    load_env
    have docker || { warn "Docker is not installed; running doctor instead"; doctor; exit $?; }
    step "starting services"
    compose up -d "$@"
    wait_for_db
    "$REPO_ROOT/scripts/db.sh" migrate
    "$REPO_ROOT/scripts/db.sh" seed
    "$REPO_ROOT/scripts/db.sh" verify
    printf '\n'
    say "API   ${BOLD}http://localhost:8000/docs${RESET}"
    say "Web   ${BOLD}http://localhost:5173${RESET}"
    ;;

  down)
    load_env
    step "stopping services"
    if [[ "${1:-}" == "--volumes" ]]; then
      warn "removing the database volume — every row goes with it"
      compose down --volumes
    else
      compose down
      hint "add --volumes to delete the database too"
    fi
    ;;

  restart)
    "$0" down && "$0" up
    ;;

  logs)
    load_env
    compose logs -f --tail=200 "$@"
    ;;

  doctor)    doctor ;;
  bootstrap) bootstrap ;;

  -h|--help|help)
    usage_and_exit "usage: dev.sh [up|down|restart|logs [service]|doctor|bootstrap]"
    ;;
  *) usage_and_exit "unknown command: $CMD" ;;
esac
