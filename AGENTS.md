# AGENTS.md — working on Maail

Read this, then follow links. **Do not read the whole architecture set for every task.**

## What Maail is

A multi-tenant web app that connects a user's Gmail, keeps a thread-first normalised copy,
and runs specialised AI agents over it to produce classification, priority, summaries,
deadlines, action items and reply drafts. Every outward action is gated behind human approval.

## The four invariants — do not violate these

1. **The thread is the unit of meaning.** Messages are storage; threads are what agents reason about.
2. **No model ever performs an external side effect.** Models read and propose. Code executes, after approval.
3. **Intelligence is demand-driven.** A cheap agent decides what an expensive agent looks at.
4. **The LLM is the last necessary step, not the first default.** Code → cache → small model → large.

## Authoritative documents

| Need | Read |
|---|---|
| Whole-system overview | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Why a decision was made | [docs/architecture/00-gap-analysis.md](docs/architecture/00-gap-analysis.md) |
| Layers, cost model, build phases | [01-hld.md](docs/architecture/01-hld.md) |
| Schema, RLS, indexes | [02-lld-data-model.md](docs/architecture/02-lld-data-model.md) |
| Agents, planes, tools, eval | [03-lld-agent-runtime.md](docs/architecture/03-lld-agent-runtime.md) |
| API, sync, jobs, layout | [04-lld-api-sync-modules.md](docs/architecture/04-lld-api-sync-modules.md) |
| Memory | [05-memory.md](docs/architecture/05-memory.md) |
| MCP | [06-mcp.md](docs/architecture/06-mcp.md) |
| Harness, caching, CI gates | [07-harness.md](docs/architecture/07-harness.md) |

These documents are the source of truth. If code disagrees with them, that is a bug in one of
the two — say which, do not silently pick.

## Commands

```bash
./scripts/check.sh              # format, types, lint, architecture boundaries
./scripts/test.sh unit          # also: integration | security | arch
./scripts/db.sh verify          # also: reset | migrate | seed
./scripts/dev.sh up             # also: down | doctor | logs
```

## Security boundaries — the three planes

| Plane | May hold | May do |
|---|---|---|
| **U** | raw email, attachment text, GitHub text, web content | read-only, user-scoped, **no network, no side effects** |
| **C** | validated structured data only | may **propose** an action; cannot execute |
| **X** | **no model at all** | executes an approved proposal, idempotently, audited |

If you are writing code that reads email content, it is Plane U and it gets no tool that acts.

## Forbidden dependencies — CI rejects these

- `executor/**` must not import any LLM client.
- `agents/**` must not import `providers/**` or `mcp_servers/**`. Tools come via `mcp/**` only.
- `mcp_servers/**` must not import `executor/**` or `agents/**`.
- No user-scoped table without an RLS policy.
- No agent without declared budgets and an output schema.
- No MCP tool without Maail-owned plane and capability metadata.
- No external MCP tool whose schema hash is not pinned in Git.

## Zero-LLM zones

Auth, sync, thread reconstruction, ingest, job lifecycle, feature gating, inbox
list/filter/sort, approval validation, and execution. If you are about to add a model call in
any of these, you are solving the wrong problem. See [07-harness.md §6](docs/architecture/07-harness.md).

## Where things live

Two phase-0 facts that are load-bearing for almost any task:

- **Tenancy.** `app/core/tenancy.py` is the only code that sets `app.user_id`. Reach a
  user-scoped table through `api/deps.py:tenant_session_dep` on a request, or
  `tenancy.tenant_session()` in a worker. The app connects as a **non-owner** role; the owner
  URL is for migrations only, and a test fails the build if anything else touches it.
- **Design tokens.** `frontend/src/styles/tokens.css` holds the locked palette. Use the
  semantic tokens (`bg-surface`, `text-fg-muted`, `bg-ai`), never a hex. Soft lavender is
  reserved for AI-derived values.
- **Credentials.** Provider tokens are sealed by `app/core/crypto.py` before they are
  written and only ever opened there. Never add a column, a log line or a response field
  that could carry one; `tests/security/test_no_plaintext_tokens.py` sweeps every column in
  the schema for them.

```
backend/app/modules/
  accounts/    connect · reconnect · refresh · disconnect. Zero-LLM zone.
  providers/   outbound integrations behind Protocols (oauth · email · vcs · llm)
  ingest/      Tier 0 — parse, strip quotes, normalise, date candidates. No model.
  sync/        two-pass Gmail sync, quota limiter, bounded reconciliation
  threads/     thread + message store, merge handling, content versioning
  harness/     Execution Planner, Context Builder, Budget Manager
  agents/      runtime + the ten agents (manifests in agent_definitions/)
  mcp/         client host, catalog, schema pinning, per-agent filtering
  mcp_servers/ mail · search · memory · productivity · github
  memory/      working · episodic · semantic · procedural retrievers
  executor/    Plane X. No LLM. Ever.
agent_definitions/  agent manifests (Git = procedural memory)
procedures/         agent procedures — never written at runtime
tool_contracts/     pinned MCP tool schemas
```

## Task contract

Every substantial task declares:

```
Task ID · Goal · Affected modules · Allowed dependencies
Expected behaviour · Acceptance criteria · Required tests
Security implications · Out of scope
```

`Out of scope` is what stops an ambiguous task becoming a subsystem redesign. Fill it in.

## Before you finish

- `./scripts/check.sh` and the relevant `test.sh` target pass.
- New AI behaviour has an eval fixture, not just a unit test.
- New agent, tool, feature or module documents its execution boundaries, context
  requirements, resource budget, **deterministic alternative** and verification method.

The deterministic-alternative field does the real work. Writing down why code cannot do the
job is usually enough to discover that it can.

## Build order and UI

- **[docs/architecture/09-execution-plan.md](docs/architecture/09-execution-plan.md)** — the
  16 phases. Each pairs a backend track with a UI track and ends demoable.
- **[docs/architecture/08-ui-spec.md](docs/architecture/08-ui-spec.md)** — the locked UI.
  Palette, typography, component style, three-region layout, all 11 screens, every feature
  toggle. **Do not change any of it.** If a screen seems to need something not listed, check
  §11 first — it may already be covered.

Three rules while building:

1. **No fake data in the running app.** A screen ships when its real data source exists.
   Mocks belong in Storybook and tests.
2. **Every AI-derived value renders through `AiValue`**, with its evidence span. Never a bare
   value, never without provenance.
3. **Every phase ends demoable.** If you cannot show it to someone, it is not done.
