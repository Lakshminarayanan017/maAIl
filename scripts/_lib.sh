#!/usr/bin/env bash
# Shared helpers. Sourced by the four scripts; not executable on its own.

set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$REPO_ROOT/backend"
FRONTEND="$REPO_ROOT/frontend"

if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
  YELLOW=$'\033[33m'; VIOLET=$'\033[35m'; RESET=$'\033[0m'
else
  BOLD=''; DIM=''; RED=''; GREEN=''; YELLOW=''; VIOLET=''; RESET=''
fi

say()  { printf '%s\n' "${VIOLET}maail${RESET} $*"; }
step() { printf '\n%s\n' "${BOLD}› $*${RESET}"; }
ok()   { printf '%s %s\n' "${GREEN}ok${RESET}" "$*"; }
warn() { printf '%s %s\n' "${YELLOW}warn${RESET}" "$*" >&2; }
die()  { printf '%s %s\n' "${RED}error${RESET}" "$*" >&2; exit 1; }
hint() { printf '%s\n' "${DIM}  $*${RESET}"; }

have() { command -v "$1" >/dev/null 2>&1; }

# --- python -----------------------------------------------------------------
# A virtualenv at backend/.venv if one exists, otherwise whatever python is on
# PATH. Windows puts the interpreter in Scripts/, POSIX in bin/.
venv_python() {
  local candidates=(
    "$BACKEND/.venv/bin/python"
    "$BACKEND/.venv/Scripts/python.exe"
    "$REPO_ROOT/.venv/bin/python"
    "$REPO_ROOT/.venv/Scripts/python.exe"
  )
  local c
  for c in "${candidates[@]}"; do
    [[ -x "$c" ]] && { printf '%s' "$c"; return 0; }
  done
  if have python3; then printf '%s' "$(command -v python3)"; return 0; fi
  if have python;  then printf '%s' "$(command -v python)";  return 0; fi
  return 1
}

PY="$(venv_python || true)"
py() { [[ -n "$PY" ]] || die "no python found; run ./scripts/dev.sh doctor"; "$PY" "$@"; }
pym() { py -m "$@"; }

ensure_env_file() {
  if [[ ! -f "$REPO_ROOT/.env" ]]; then
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
    warn "created .env from .env.example — placeholder secrets, development only"
  fi
}

load_env() {
  ensure_env_file
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
}

compose() {
  if have docker && docker compose version >/dev/null 2>&1; then
    docker compose -f "$REPO_ROOT/docker-compose.yml" "$@"
  elif have docker-compose; then
    docker-compose -f "$REPO_ROOT/docker-compose.yml" "$@"
  else
    die "Docker Compose not found. Install Docker Desktop, then ./scripts/dev.sh doctor"
  fi
}

usage_and_exit() {
  printf '%s\n' "$1" >&2
  exit 2
}
