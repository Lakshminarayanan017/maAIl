# Maail LLD — Harness Engineering

> **Build around intelligence, not inference.**
> The LLM is the last necessary step, not the first default.

Two harnesses, one philosophy: the **development harness** controls how Maail is built; the
**runtime harness** controls how Maail's agents execute. Both exist to make a model
unnecessary wherever code, cache or data suffices.

## 1. The twelve principles

| # | Principle | Applied as |
|---|---|---|
| 1 | Deterministic first | Tier 0, user rules, date parsing, dedupe — no model |
| 2 | Context minimisation | Context Builder with a declared token budget |
| 3 | Progressive disclosure | Per-agent MCP tool filtering; context loaders for coding agents |
| 4 | Reuse | Intelligence cache keyed on content + agent + prompt version |
| 5 | Contract enforcement | Pydantic in, Pydantic out, JSON Schema at MCP boundaries |
| 6 | Explicit execution | Plane X only, behind approval |
| 7 | Bounded autonomy | Steps, tokens, wall clock, tool calls — runtime-enforced |
| 8 | Observability | `agent_runs` + `agent_steps` with cost per step |
| 9 | Feedback loops | Three evaluation levels (§7) |
| 10 | Architectural enforcement | Import-boundary tests in CI |
| 11 | Self-service engineering | `AGENTS.md`, four scripts, task contracts |
| 12 | Continuous cleanup | Stale-doc and unused-capability checks (H4) |

## 2. The runtime harness — three components, not three layers

The source material names a "Memory Management Layer", an "Intelligence Efficiency
Controller" and a context harness. Collapsed into **three named components** sitting above
the agent runtime:

### Execution Planner — decides whether a model runs

```python
async def plan(req: IntelligenceRequest) -> Plan:
    if rule := match_user_rules(req):          # deterministic override
        return Plan.deterministic(rule)
    if not feature_enabled(req.user_id, req.feature):
        return Plan.skip("disabled")
    if cached := lookup_cache(req.cache_key):  # §4
        return Plan.cached(cached)
    if bypass := deterministic_bypass(req):    # §3 — asymmetric, see warning
        return Plan.deterministic(bypass)
    if not await budget_ok(req.user_id, req.tier):
        return Plan.skip("budget")
    return Plan.invoke(tier=route_tier(req))
```

Five of six paths cost nothing. That is the point.

### Context Builder — decides what the model sees

Specified in `05-memory.md` §4. Returns a package with a declared `token_estimate` **before**
the call, so the Budget Manager can decline rather than discover the cost afterwards.

### Budget Manager — decides whether it is affordable

Per-user monthly caps with soft and hard thresholds, plus per-run caps from the agent
manifest. Checked before the call, never reconciled after.

## 3. Deterministic bypass — the one genuinely risky optimisation

The source material proposes a rule-first Triage fast path and flags the danger in passing.
It deserves a hard rule, because this is the one harness optimisation that can lose a user's
important email.

> **A bypass may only ever reduce work. It may never suppress a thread from view, and it
> requires positive evidence of unimportance — never the absence of evidence of importance.**

| Signal | Bypass permitted? |
|---|---|
| Explicit `user_rule` match | Yes — the user asked for it |
| Sender with ≥N prior threads, all low priority, none ever replied to | Yes — downgrade only |
| `List-Unsubscribe` header present **and** sender has history | Yes — downgrade only |
| Unknown sender | **No** — run Triage |
| Unknown sender with marketing-looking content | **No** — looks-like is not evidence |
| Sender previously overridden upward by the user | **No** — never bypass again |

A false negative on an unknown sender costs trust permanently. A Triage call costs a
fraction of a cent. The asymmetry is not close, and the metric must reflect it: **bypass rate
is tracked, never targeted.** Phase 6's gate is classification quality maintained, with call
reduction as a secondary observation.

## 4. The four caches, which are four different things

Routinely conflated. They are not interchangeable.

| # | Mechanism | Prevents | Keyed on |
|---|---|---|---|
| 1 | **Result cache** | Recomputing finished analysis | the composite key below |
| 2 | **Job dedupe** | Two workers doing the same work concurrently | `dedupe_key` |
| 3 | **API/query cache** | Repeated database and HTTP round trips | request shape |
| 4 | **Provider prompt cache** | Re-billing a stable prompt prefix | prompt layout |

### The result cache key

```
sha256(
  user_id, thread_id, content_version,
  feature_id, agent_id, agent_version,
  prompt_version, model_id, config_hash
)
```

Every component is load-bearing. Drop `prompt_version` and a prompt change silently reuses
incompatible results. Drop `config_hash` and two users with different summary-length
settings share a summary. Drop `content_version` and a new message is ignored.

```sql
CREATE TABLE intelligence_cache (
  cache_key      text PRIMARY KEY,
  user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  thread_id      uuid REFERENCES email_threads(id) ON DELETE CASCADE,
  agent_id       text NOT NULL,
  result_ref     jsonb NOT NULL,     -- pointer to the real row, not a copy
  hit_count      int NOT NULL DEFAULT 0,
  created_at     timestamptz NOT NULL DEFAULT now(),
  last_hit_at    timestamptz
);
```

`result_ref` is a pointer. Copying results into the cache would create a second source of
truth for intelligence, which `02-lld-data-model.md` already refuses for episodic memory and
refuses here for the same reason.

### Prompt layout for cache 4

| Section | Content | Position |
|---|---|---|
| Stable | System policy (Git), output schema, tool schemas | First, versioned |
| Semi-stable | Agent config, feature instructions | Middle, cached by version |
| Dynamic | Thread content, memory blocks | **Last** |

Volatile content last, or the provider's prefix cache never hits.

## 5. Per-agent harness profile

Every agent declares its own resource and context policy in Git, and the runtime enforces it
without the model needing to be told.

```yaml
# agent_definitions/summarizer.yaml
id: summarizer
version: "1.0.0"
plane: U
execution:
  model_tier: mid
  max_steps: 3
  max_tokens: 4000
  max_wall_clock_s: 20
context:
  retrievers: [procedural]
  source: current_thread
  max_messages: 10
  use_stripped_content: true        # B1 — never raw
  include_quoted_history: false
mcp:
  servers: [mail]
  allowed_tools: [mail/get_thread]
  max_tool_calls: 2
  max_result_bytes: 16000
caching:
  enabled: true
  key: standard                      # the §4 composite
validation:
  output_schema: ThreadSummary
  require_evidence: true
fallback:
  use_cached_result: true
  fail_without_guessing: true        # never fabricate to satisfy the schema
```

`fail_without_guessing` matters more than it looks: a schema-constrained model will invent a
value to produce valid output. An agent that cannot answer must be able to say so — which is
why `deadlines.resolution_status` has an `ambiguous` value and why `require_evidence` can
fail a run.

Limits in this file are starting points to be set by measurement, not asserted constants.

## 6. Zero-LLM zones

Declared, and enforced by import-boundary tests:

| Module | Model calls |
|---|---|
| `auth`, OAuth, sessions, tokens | **Zero** |
| `sync`, thread reconstruction, reconciliation | **Zero** |
| `ingest` — parse, strip, normalise, dedupe, date candidates | **Zero** |
| `jobs` — claim, lease, retry, dead-letter | **Zero** |
| `features`, `rules` — gating and dependency resolution | **Zero** |
| Inbox list, filter, sort, paginate, open | **Zero** |
| `approvals` — validation and staleness detection | **Zero** |
| `executor` — Plane X | **Zero** |

Thread reconstruction deserves emphasis: deciding whether two messages belong to the same
thread is an RFC-822 header problem with a correct answer. A model would be slower, costlier
and wrong sometimes.

## 7. Evaluation — three levels, and only some of them gate

| Level | Runs | Checks | Gates CI? |
|---|---|---|---|
| **1 — Deterministic** | every change | schemas, rules, planes, RLS, retries, cache keys, idempotency | **Yes** |
| **2 — Behavioural** | agent changes | tool selection, retrieval, abstention, citations, budgets, routing | Partly |
| **3 — End-to-end** | before release | journeys, quality, latency, cost | No — reviewed |

### What blocks and what is merely tracked

This distinction is the thing that keeps the harness from becoming a reason not to ship.

**Blocking — correctness and security, always fail CI:**

- an unauthorised action, ever
- a plane violation or a tool discovered outside an agent's manifest
- cross-tenant data access
- an approval replayed, or honoured after the content changed
- a duplicate external side effect
- any injection-corpus case producing a side effect
- a behavioural fact reaching `semantic_facts`
- a runtime write to `procedures/`

**Tracked — efficiency and quality, recorded and reviewed, never fail CI:**

- cache hit rate, bypass rate, tokens per thread
- cost per successful task
- summary factuality spot checks
- routing precision drift within tolerance

A valid alternative tool sequence must not fail the build; an unauthorised action must always
fail it. Level 2 is split along exactly that line.

### Cost regression gating has a chicken-and-egg problem

You cannot gate on cost regression without a baseline, and the baseline costs real model
calls. So: **record** cost per eval run from phase 6; **gate** on regression from phase 9,
when three agents exist to compare and the baseline has stabilised.

## 8. The development harness

### Maturity ladder, bound to phases

The source material proposes H0–H4 but does not bind them, so everything reads as required
immediately. Binding them is the fine-tune:

| Level | Content | Required by |
|---|---|---|
| **H0** | `AGENTS.md`, Docker, four scripts, architecture-lint tests, seeded fixtures | **Phase 0** |
| **H1** | Deterministic ingest, caches, job policies, DB constraints, RLS tests | **Phase 4** |
| **H2** | Model routing, context budgets, MCP filtering, traces, output validation | **Phase 5** |
| **H3** | Behavioural evals, golden traces, injection corpus, security gates | **Phase 6** |
| **H4** | Cost regression detection, stale-doc checks, dead-code detection, dashboards | After v1 |

**H0 and H1 only before the first agent ships.** Everything else has a phase trigger. A
harness built ahead of the thing it constrains is speculative work.

### Four scripts, not nine

```
scripts/
├── check.sh      # format, types, lint, architecture boundaries
├── test.sh       # unit | integration | security | arch  (subcommand)
├── db.sh         # reset | migrate | verify | seed
└── dev.sh        # up | down | doctor | logs
```

Nine scripts is nine things to keep working. Four with subcommands covers the same ground.
A `maail` CLI is H4, if ever.

### `AGENTS.md` — a map, not a manual

At most ~100 lines. It states what Maail is, where the authoritative documents are, the
commands, the security boundaries, the forbidden dependencies, and how to run a task. It
does **not** contain the HLD. A coding agent follows links; an agent handed 2,000 lines of
architecture spends its context rediscovering what a link would have told it.

### Progressive context disclosure

A task should not require reading the repository:

```
TASK: Gmail incremental sync retry
Modules:   providers/email/gmail.py · modules/sync/{engine,reconcile}.py · jobs/queue.py
Docs:      01-hld §9 phase 2 · 04-lld §3 · 07-harness §6
Contracts: EmailProvider · SyncCursor · BackgroundJob
Tests:     tests/sync/test_delta_sync.py · tests/sync/test_reconciliation.py
Forbidden: no LLM in sync; no direct Gmail calls from agents
```

### Architecture rules as executable checks

| Rule | Check |
|---|---|
| `executor/**` imports no LLM client | import-graph test |
| `agents/**` never imports `providers/**` or `mcp_servers/**` | import-graph test |
| `mcp_servers/**` never imports `executor/**` or `agents/**` | import-graph test |
| Plane U agents hold no side-effect or egress tool | registry validator |
| Every user-scoped table has an RLS policy | schema audit |
| Every agent declares budgets and an output schema | registry validator |
| Every MCP tool has Maail-owned plane and capability metadata | catalog validator |
| Every external MCP tool schema is pinned in Git | catalog validator |
| No migration without a downgrade or a documented recovery | migration check |

Do not tell coding agents to respect architecture. Make CI reject violations.

### Task contract

```
Task ID · Goal · Affected modules · Relevant ADRs · Allowed dependencies
Expected behaviour · Acceptance criteria · Required tests
Security implications · Out of scope
```

`Out of scope` is the field that stops an ambiguous task becoming a subsystem redesign.

### Reproducible environment

Isolated Git worktree per task · seeded Postgres fixtures · stubbed Gmail, GitHub and LLM ·
**deterministic clock** for deadline tests · test secrets separate from real credentials ·
captured logs and traces.

The deterministic clock is not optional. Half of `deadlines` is relative-date resolution, and
a test suite whose answers change on Friday is not a test suite.

### UI harness

Playwright with seeded inbox data, DOM snapshots, console and network error capture,
accessibility checks. A UI task is done when the interaction works, not when the component
compiles. Visual regression is H4.

## 9. Measurement

A SQL view set in v1, not a dashboard. A dashboard UI is H4.

```sql
CREATE VIEW v_cost_per_thread AS
  SELECT user_id, subject_id AS thread_id,
         count(*) FILTER (WHERE status='succeeded') AS runs,
         sum(cost_micros) AS cost_micros,
         sum(input_tokens) AS input_tokens
    FROM agent_runs WHERE subject_type='thread' GROUP BY 1,2;

CREATE VIEW v_execution_path AS
  SELECT date_trunc('day', created_at) AS day, agent_id, trigger,
         count(*) AS n, avg(cost_micros) AS avg_cost
    FROM agent_runs GROUP BY 1,2,3;

CREATE VIEW v_strip_effectiveness AS
  SELECT date_trunc('day', created_at) AS day,
         avg(stripped_ratio) AS avg_ratio, count(*) AS messages
    FROM email_messages WHERE body_text_stripped IS NOT NULL GROUP BY 1;
```

### Cost per successful task, not cost per call

| Execution | Calls | Outcome |
|---|---|---|
| Search existing mail | 0 | success |
| Cached summary returned | 0 | success |
| New summary generated | 1 | success |
| Complex investigation | 4 | success |
| Same investigation repeated | 12 | **inefficient** |

Minimising calls is the wrong target; the last row is the failure mode worth catching, and
only a per-task denominator reveals it.

## 10. The eight invariants

1. No LLM invocation without a registered capability, a budget and a recorded reason.
2. No model call where deterministic code or a valid cached result suffices.
3. No agent receives the full MCP tool catalog.
4. No agent reprocesses unchanged content without a recorded reason.
5. No AI output enters persistent storage without schema validation.
6. No external side effect through a model or an MCP-exposed tool.
7. Every agent run is bounded, traced and costed.
8. Every change passes the relevant architectural and behavioural checks.

Added in v3.1, from the memory and MCP work:

9. Procedural memory is read from Git and never written at runtime.
10. MCP tool plane and capability metadata is Maail-owned, never read from a server.

## 11. The standing gate

> No new agent, MCP tool, AI feature or backend module enters Maail without documenting its
> execution boundaries, context requirements, resource budget, **deterministic alternative**
> and verification method.

The deterministic-alternative field is the one that does the work. Being made to write down
why code cannot do the job is usually enough to discover that it can.
