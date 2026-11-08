# Maail

**Your inbox deserves a brain.** Understand more. Manage less.

Maail connects your Gmail, keeps a thread-first normalised copy, and runs specialised AI
agents over it to produce classification, priority, summaries, deadlines, action items and
reply drafts. Every outward action is gated behind human approval.

- [AGENTS.md](AGENTS.md) — read this first if you are writing code
- [ARCHITECTURE.md](ARCHITECTURE.md) — the whole system on one page
- [docs/architecture/09-execution-plan.md](docs/architecture/09-execution-plan.md) — the 16 phases
- [docs/architecture/08-ui-spec.md](docs/architecture/08-ui-spec.md) — the locked UI

## Status

**Phases 0 to 7 complete.** Latest: the Command Center (screen 03).

| Delivered | Where |
|---|---|
| Monorepo, Docker Compose, Postgres 16 | [docker-compose.yml](docker-compose.yml) |
| RLS **enabled + FORCEd**, non-owner application role | [migrations](backend/migrations/versions) · [infra](infra/postgres/init) |
| `SET LOCAL app.user_id` through one dependency | [tenancy.py](backend/app/core/tenancy.py) |
| Deterministic clock | [clock.py](backend/app/core/clock.py) |
| Architecture-lint: 11 import rules + 3 audits | [tests/arch](backend/tests/arch) |
| Design tokens, both themes, three regions, base states | [frontend/src](frontend/src) |
| **Google OAuth 2.0 with PKCE, `gmail.readonly` only** | [google.py](backend/app/modules/providers/oauth/google.py) |
| **Envelope encryption with a rotatable `key_version`** | [crypto.py](backend/app/core/crypto.py) |
| **Sessions, CSRF double-submit, signed OAuth flow cookie** | [security.py](backend/app/core/security.py) |
| **`reauth_required` as a first-class state** | [service.py](backend/app/modules/accounts/service.py) |
| **Screens 01, 02 and the scope explanation page** | [pages/onboarding](frontend/src/pages/onboarding) |
| **Reconnect banner, connected-account card** | [ReconnectBanner](frontend/src/components/common/ReconnectBanner.tsx) · [AccountCard](frontend/src/components/settings/AccountCard.tsx) |
| **Two-pass Gmail sync, resumable, quota-limited** | [engine.py](backend/app/modules/sync/engine.py) · [quota.py](backend/app/modules/sync/quota.py) |
| **Bounded reconciliation on a dead cursor** | [reconcile.py](backend/app/modules/sync/reconcile.py) |
| **Thread linking and merge handling** | [store.py](backend/app/modules/threads/store.py) |
| **Screen 04: three panes, virtualised list, live progress** | [pages/inbox](frontend/src/pages/inbox) · [components/inbox](frontend/src/components/inbox) |
| **Quote stripping — the largest cost lever, no AI** | [quote_stripper.py](backend/app/modules/ingest/quote_stripper.py) |
| **HTML sanitiser, image blocking, link-mismatch badges** | [sanitizer.py](backend/app/modules/ingest/sanitizer.py) |
| **Deterministic date candidates with spans** | [date_parser.py](backend/app/modules/ingest/date_parser.py) |
| **Screen 05 left: reader, sandboxed iframe, quoted collapse** | [components/thread](frontend/src/components/thread) |
| **Postgres job queue: atomic claim, leases, dedupe, reaper** | [queue.py](backend/app/jobs/queue.py) |
| **`AiValue` — no AI value renders without its provenance** | [AiValue.tsx](frontend/src/components/intelligence/AiValue.tsx) |
| **Harness: planner, context builder, budgets, 9-part cache key** | [harness](backend/app/modules/harness) |
| **MCP host: plane filtering, schema pinning, in-process servers** | [mcp](backend/app/modules/mcp) |
| **Agent runtime: manifests in Git, bounded loop, traces** | [runtime](backend/app/modules/agents/runtime) |
| **Triage agent, user rules, asymmetric bypass** | [triage.py](backend/app/modules/agents/defs/triage.py) · [bypass.py](backend/app/modules/rules/bypass.py) |
| **Screen 04 complete: badges, 8 filters, corrections** | [components/inbox](frontend/src/components/inbox) |
| **Screen 03: Command Center, facts kept apart from judgements** | [OverviewPage](frontend/src/pages/overview/OverviewPage.tsx) |

Phase 8 is the intelligence panel — screen 05's right half.

### Connecting a real Gmail account

Create an OAuth client at [console.cloud.google.com](https://console.cloud.google.com):
type **Web application**, authorised redirect URI
`http://localhost:8000/api/v1/auth/google/callback`. Put the id and secret in `.env`.

The app stays in Google's **Testing** mode: at most 100 test users, and a refresh token
that expires after about seven days. That is designed for rather than worked around —
`reauth_required` is a state, the banner is persistent, and reconnecting keeps the account
id and everything derived from it.

## Running it

```bash
cp .env.example .env
./scripts/dev.sh doctor      # what is missing, before anything starts
./scripts/dev.sh up          # Postgres, migrate, seed, verify, API, web
```

Without Docker, any Postgres 16 or newer that `.env` points at will do. Create an owner
role and a **non-owner** application role — the split is half of the tenancy boundary, so
`db.sh verify` fails without it — then:

```bash
./scripts/db.sh migrate && ./scripts/db.sh seed && ./scripts/db.sh verify
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload
```

| Command | Does |
|---|---|
| `./scripts/check.sh` | format, types, lint, architecture boundaries |
| `./scripts/test.sh unit` | also `integration`, `security`, `arch`, `frontend`, `all` |
| `./scripts/db.sh verify` | also `reset`, `migrate`, `seed`, `revision`, `psql` |
| `./scripts/dev.sh up` | also `down`, `restart`, `logs`, `doctor`, `bootstrap` |

Without Docker, `./scripts/dev.sh bootstrap` installs both toolchains and `doctor` tells you
what is still missing. `arch` and `unit` run with nothing but Python; `integration` and
`security` need Postgres and skip with a stated reason when it is not up.

## The shape of it

```
backend/app/
  core/       settings, logging, tenancy, crypto, the clock
  api/        HTTP surface; identity resolves through api/deps.py and nowhere else
  modules/    ingest · sync · threads · harness · agents · mcp · memory · executor · ...
  database/   engine, models, migrations, schema audit
frontend/src/
  styles/     the locked design tokens
  components/ layout (three regions) · common (base states) · ui (primitives)
agent_definitions/ procedures/ prompts/ tool_contracts/
  procedural memory — Git is the store, read at deploy, never written at runtime
```

## The four invariants

1. **The thread is the unit of meaning.** Messages are storage; threads are what agents reason about.
2. **No model ever performs an external side effect.** Models read and propose. Code executes, after approval.
3. **Intelligence is demand-driven.** A cheap agent decides what an expensive agent looks at.
4. **The LLM is the last necessary step, not the first default.** Code → cache → small model → large.

## Three planes

| Plane | May hold | May do |
|---|---|---|
| **U** | raw email, attachment text, GitHub text, web content | read-only, user-scoped, no network, no side effects |
| **C** | validated structured data only | may **propose** an action; cannot execute |
| **X** | **no model at all** | executes an approved proposal, idempotently, audited |

CI rejects a violation rather than a reviewer catching it. See
[.github/workflows/ci.yml](.github/workflows/ci.yml).
