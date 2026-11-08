# Maail LLD — API, Sync Engine, Jobs and Module Layout

## 1. Repository layout

```
maail/
├── AGENTS.md                     # coding-agent entry point (H0)
├── ARCHITECTURE.md               # whole-system sketch
├── docker-compose.yml
├── docs/architecture/            # these documents
│
├── agent_definitions/            # PROCEDURAL MEMORY — Git, read at deploy
│   └── <agent>.yaml              #   manifests: plane, tier, tools, budgets, context
├── procedures/                   #   never written at runtime (05-memory §1)
├── prompts/                      #   <agent>/<version>.md
├── tool_contracts/               #   pinned MCP schemas (06-mcp §3)
│
├── scripts/                      # four, not nine (07-harness §8)
│   ├── check.sh  test.sh  db.sh  dev.sh
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── security.py          # sessions, CSRF
│   │   │   ├── crypto.py            # envelope encryption, key_version (D8)
│   │   │   ├── tenancy.py           # SET LOCAL app.user_id  (D1)
│   │   │   └── logging.py           # structured, run_id-aware
│   │   │
│   │   ├── api/
│   │   │   ├── deps.py              # auth + tenancy dependency
│   │   │   └── v1/
│   │   │       ├── auth.py  accounts.py  threads.py  messages.py
│   │   │       ├── intelligence.py  companion.py  approvals.py
│   │   │       ├── features.py  rules.py  search.py  sync.py
│   │   │
│   │   ├── modules/
│   │   │   ├── threads/             # thread + message store, merge logic (A5)
│   │   │   ├── ingest/              # Tier 0: normalize, strip, dedupe
│   │   │   │   ├── normalizer.py
│   │   │   │   ├── quote_stripper.py      # B1 — the cost lever
│   │   │   │   ├── html_to_text.py
│   │   │   │   └── date_parser.py         # deterministic candidates
│   │   │   ├── sync/
│   │   │   │   ├── engine.py              # state machine (§3)
│   │   │   │   ├── reconcile.py           # bounded recovery (A2)
│   │   │   │   └── quota.py               # per-account token bucket (A1)
│   │   │   ├── features/            # registry + gating
│   │   │   ├── rules/               # deterministic pre-pass (E4)
│   │   │   ├── retrieval/           # FTS + filters, query parsing
│   │   │   ├── style/               # derived profile, not a stored fact
│   │   │   │
│   │   │   ├── harness/             # v3.1 — ABOVE the runtime (07-harness §2)
│   │   │   │   ├── planner.py             # Execution Planner: does a model run?
│   │   │   │   ├── context_builder.py     # minimal context under a token budget
│   │   │   │   ├── budget.py              # per-user and per-run caps
│   │   │   │   └── cache.py               # the 9-part result cache key
│   │   │   │
│   │   │   ├── memory/              # v3.1 — retrievers, not a datastore (05-memory)
│   │   │   │   ├── router.py              # which retriever for which agent
│   │   │   │   ├── working.py             # conversation, capped — not persisted
│   │   │   │   ├── episodic.py            # VIEW over existing tables, no new store
│   │   │   │   ├── semantic.py            # semantic_facts + proposal promotion
│   │   │   │   ├── procedural.py          # immutable Git registry, load at startup
│   │   │   │   ├── lifecycle.py           # expiry, conflict, user control
│   │   │   │   └── consolidation.py       # deterministic dedupe + prune
│   │   │   │
│   │   │   ├── agents/
│   │   │   │   ├── runtime/         # loop, planes, traces (manifests from Git)
│   │   │   │   └── defs/            # agent implementations
│   │   │   │
│   │   │   ├── mcp/                 # v3.1 — client host (06-mcp §6)
│   │   │   │   ├── client_manager.py
│   │   │   │   ├── transports/      # inprocess.py (v1) · stdio.py · http.py
│   │   │   │   ├── catalog.py              # CatalogEntry, discovery, schema pinning
│   │   │   │   ├── filter.py               # per-agent tool filtering
│   │   │   │   └── invoke.py               # the invocation lifecycle
│   │   │   │
│   │   │   ├── mcp_servers/         # v3.1 — in-process servers
│   │   │   │   ├── mail/  search/  memory/  productivity/  github/
│   │   │   │
│   │   │   ├── approvals/           # proposals, binding, tokens
│   │   │   ├── executor/            # PLANE X — no LLM imports, enforced by test
│   │   │   ├── providers/
│   │   │   │   ├── email/   base.py  gmail.py
│   │   │   │   ├── vcs/     base.py  github.py
│   │   │   │   └── llm/     base.py  <provider>.py
│   │   │   └── audit/
│   │   │
│   │   ├── jobs/                    # queue client, claim, lease, dead-letter
│   │   ├── workers/                 # entrypoints: sync, intelligence, scheduled
│   │   └── database/
│   ├── migrations/                  # alembic
│   ├── evals/
│   │   ├── fixtures/                # ~60 threads
│   │   ├── traces/                  # golden traces
│   │   ├── injection/               # the 6-case corpus
│   │   └── run_eval.py
│   └── tests/
│
└── frontend/
    └── src/
        ├── components/{common,layout,inbox,thread,intelligence,companion,settings}/
        │   └── intelligence/AiValue.tsx    # F3 — the one AI-vs-fact component
        ├── pages/{onboarding,inbox,thread,companion,settings}/
        ├── hooks/  services/  stores/  types/
```

Layout rules enforced in CI (v3.1 — see `06-mcp.md` §6 and `AGENTS.md`):

- `modules/executor/` must not import any LLM client.
- `modules/agents/**` must not import `providers/**` or `mcp_servers/**` — tools reach agents
  only through `modules/mcp/**`. This is the loose coupling, made mechanical.
- `modules/mcp_servers/**` must not import `executor/**` or `agents/**`.
- Nothing writes `procedures/`, `agent_definitions/` or `tool_contracts/` at runtime. These
  are procedural memory; a runtime write is a poisoning vector, not a feature.

## 2. API

Session cookie auth, CSRF on mutations. Every handler resolves `user_id` through one
dependency that also issues `SET LOCAL app.user_id`.

### Accounts and sync

```
POST   /api/v1/auth/google/start              → {authorize_url, state}
GET    /api/v1/auth/google/callback           → session; creates connected_account
GET    /api/v1/accounts                       → [{id, email, status, sync_progress,
                                                  refresh_expires_at}]
POST   /api/v1/accounts/{id}/reconnect        → re-auth URL  (A3)
DELETE /api/v1/accounts/{id}                  → ?purge=now|30d  (O5)
GET    /api/v1/sync/status                    → SSE: {phase, done, total, eta_s}
POST   /api/v1/sync/trigger                   → enqueue delta sync (rate limited)
```

`refresh_expires_at` is returned so the client can warn *before* the 7-day Testing-mode
expiry bites, rather than after a sync fails.

### Threads

```
GET /api/v1/threads
    ?cursor=<opaque>&limit=50
    &filter=all|unread|priority|needs_reply|category:<enum>|label:<name>
    &q=<fts query>
→ { items: [ThreadListItem], next_cursor }
```

`cursor` encodes `(latest_message_at, id)` (E5). `ThreadListItem` carries
`intelligence_status` per capability so the list can render "analysing" honestly (F2) rather
than showing a blank or a fabricated value.

```
GET  /api/v1/threads/{id}                 → thread + messages (stripped text)
GET  /api/v1/threads/{id}/messages/{mid}/body
     → sanitised HTML; remote images proxied or blocked  (D3)
POST /api/v1/threads/{id}/read            → {is_read}
POST /api/v1/threads/{id}/override        → {field, value} → user_overrides (F4)
```

The body endpoint is separate and on-demand precisely because raw HTML is not stored (E6).

### Intelligence

```
GET  /api/v1/threads/{id}/intelligence
→ { category, category_source, priority, priority_reason, priority_age_s,
    needs_reply, statuses: {...},
    summary: {text, bullets, evidence[]} | null,
    deadlines: [...], action_items: [...],
    dev_findings: [...] | null,
    pipeline_version, content_version }

POST /api/v1/threads/{id}/intelligence/request   → {capability} enqueues on-demand run
GET  /api/v1/runs/{run_id}                       → status + trace summary
POST /api/v1/deadlines/{id}/resolve              → user confirms or corrects an ambiguity
```

Every AI-derived field in that payload ships with its evidence. A field with no evidence
renders as "not determined" — never as a bare value (F3).

### Companion

```
POST /api/v1/companion/conversations          → {thread_id?} 
POST /api/v1/companion/conversations/{id}/messages
     body: {content}
→ SSE stream:
     event: token        data: {"text": "..."}
     event: tool         data: {"name": "search_threads", "summary": "..."}
     event: citation     data: {"thread_id","message_id","char_start","char_end"}
     event: proposal     data: {"proposed_action_id","target_summary"}
     event: done         data: {"run_id","cost_micros"}
```

SSE rather than WebSockets: simpler, survives proxies, and nothing here needs a duplex
channel. Tool events are surfaced so the user can see what the agent did — the visible half
of the trace that `agent_steps` records in full.

### Approvals — the only path to a side effect

```
GET  /api/v1/approvals                   → pending proposals
GET  /api/v1/approvals/{id}              → full params + evidence + target_summary
POST /api/v1/approvals/{id}/approve      body: {content_hash, edited_params?}
POST /api/v1/approvals/{id}/reject
```

The client **must** echo the `content_hash` it displayed. A mismatch returns `409
superseded` with the current version — this is what makes "approve a draft, then the thread
changes" safe (D5). Editing params recomputes the hash and requires a fresh approval.

### Features and rules

```
GET   /api/v1/features                   → [{feature_id, enabled, config, schema}]
PUT   /api/v1/features/{feature_id}      → {enabled, config}
POST  /api/v1/features/preset            → {preset: minimal|productivity|developer}
GET   /api/v1/rules  POST /api/v1/rules  PUT/DELETE /api/v1/rules/{id}
```

Disabling a feature changes future execution only; stored results are retained and the
response says so explicitly.

### Error envelope

```json
{ "error": { "code": "reauth_required",
             "message": "Reconnect your Gmail account to resume syncing.",
             "detail": {"account_id": "..."} } }
```

Codes that matter: `reauth_required`, `budget_exceeded`, `superseded`,
`capability_not_granted`, `sync_in_progress`, `rate_limited`.

## 3. Sync engine

### States

```
disconnected → connecting → initial_metadata → initial_bodies → active
                                                                  │
                      ┌───────────────────────────────────────────┤
                      ▼                        ▼                  ▼
              reauth_required          reconciling            error
                   (A3)                   (A2)
```

### Initial sync — two passes (A1)

```
Pass 1  messages.list (paged)  +  messages.get format=METADATA   20 units each
        → threads, participants, dates, labels, snippets
        → newest 500 threads first, then backfill
        → serve the inbox as soon as pass 1 covers page 1  (F1)

Pass 2  messages.get format=FULL                               60 units each
        → bodies, newest-first, only for threads not yet fetched
        → Tier 0 runs per message: html→text, quote strip, date candidates
```

Budget: 6,000 units/min/user means ~300 metadata fetches or ~100 full fetches per minute.
`quota.py` holds a token bucket per account and the worker blocks on it rather than
discovering `userRateLimitExceeded` the hard way. `initial_sync_done / initial_sync_total`
drives the progress UI.

### Delta sync

```
users.history.list(startHistoryId = account.history_cursor)
  ├─ 404 / stale cursor ──► reconcile()                           (A2)
  └─ events:
       messagesAdded    → upsert message, bump content_version,
                          significance gate → maybe enqueue triage   (C5)
       messagesDeleted  → soft-delete locally
       labelsAdded      → update provider_labels, recompute unread
       labelsRemoved    → same                                      (A8)
  └─ store new historyId + history_cursor_at
```

### Bounded reconciliation (A2)

Never a blind full resync.

```python
async def reconcile(account, window_days=30):
    remote = await gmail.list_message_ids(account, after=now() - window_days)
    local  = await store.message_ids(account, after=now() - window_days)
    for mid in remote - local:  await enqueue_fetch(account, mid)
    for mid in local - remote:  await soft_delete(account, mid)
    await store.set_cursor(account, await gmail.current_history_id(account))
```

### Thread merge handling (A5)

When a message's `References` chain points into a different local thread, or Gmail reports a
new `threadId` for a message we already hold: pick the survivor by `first_message_at`, set
`merged_into_thread_id` on the other, move messages, union participants, and re-derive
intelligence on the survivor. Old intelligence rows are kept against the merged thread — the
audit trail survives the merge.

### Per-message failure tolerance (A7)

A 404 or parse failure on one message records a miss and continues. One bad message never
fails a batch, and misses are retried on the next pass with a bounded attempt count.

## 4. Job queue

### Claiming — atomic, leased

```sql
WITH claimed AS (
  SELECT id FROM background_jobs
   WHERE status = 'pending' AND available_at <= now()
   ORDER BY priority, available_at, id
   FOR UPDATE SKIP LOCKED
   LIMIT 1
)
UPDATE background_jobs j
   SET status = 'running',
       locked_by = $worker_id,
       lease_expires_at = now() + interval '5 minutes',
       attempts = attempts + 1,
       updated_at = now()
  FROM claimed
 WHERE j.id = claimed.id
RETURNING j.*;
```

One statement, so a crash between select and update is impossible.

### Lease recovery

```sql
UPDATE background_jobs
   SET status = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'pending' END,
       available_at = now() + (interval '30 seconds' * power(2, attempts)),
       locked_by = NULL, lease_expires_at = NULL
 WHERE status = 'running' AND lease_expires_at < now();
```

A reaper runs this periodically. Long-running jobs renew their lease. Exponential backoff;
`dead` is terminal and alertable. Phase 4 is not done until killing a worker mid-job
provably results in exactly-once completion.

### Job types

| Type | Dedupe key | Priority |
|---|---|---|
| `sync.initial_metadata` | `sync:meta:{account}` | 10 |
| `sync.initial_bodies` | `sync:body:{account}` | 40 |
| `sync.delta` | `sync:delta:{account}` | 20 |
| `sync.reconcile` | `sync:recon:{account}` | 30 |
| `ingest.message` | `ingest:{message}` | 50 |
| `agent.triage` | `triage:{thread}` | 60 |
| `agent.specialist` | `agent:{agent_id}:{thread}` | 80 |
| `scheduled.briefing` | `brief:{user}:{date}` | 120 |
| `maintenance.purge` | `purge:{account}` | 200 |

Scheduling uses `available_at`; no cron daemon in v1.

## 5. Provider adapters

```python
class EmailProvider(Protocol):
    async def exchange_code(self, code: str) -> OAuthTokens: ...
    async def refresh(self, refresh_token: str) -> OAuthTokens: ...
    async def list_message_ids(self, acct, *, after=None,
                               page_token=None) -> tuple[list[str], str | None]: ...
    async def get_messages(self, acct, ids: list[str], *,
                           fmt: Literal["metadata", "full"]) -> list[RawMessage]: ...
    async def history(self, acct, since: str) -> HistoryPage: ...
    async def current_history_id(self, acct) -> str: ...
    async def create_draft(self, acct, draft: DraftSpec) -> ProviderRef: ...
    async def send(self, acct, draft_id: str) -> ProviderRef: ...
```

`create_draft` and `send` exist on the adapter but are callable **only** from
`modules/executor`. No agent tool reaches them.

```python
class LLMProvider(Protocol):
    async def call(self, *, tier: ModelTier, messages, tools=None,
                   response_model=None) -> LLMResponse: ...
```

`LLMResponse` always carries `input_tokens`, `output_tokens`, `cached_input_tokens` and
`model`, because `agent_steps` requires them (B4).

## 6. Frontend notes

- **Three regions**, with the AI panel in option C's three states: collapsed affordance,
  contextual panel, full-screen companion (F5). One store holds the panel state; it is not
  per-page.
- **`AiValue.tsx` is the only component that renders an AI-derived value.** It takes
  `{value, evidence, status, source}` and renders the value, a source affordance that opens
  the evidence span in the message, and the status when not `ready`. Enforcing this in one
  component is what makes F3 real rather than aspirational.
- **Email body** renders in a sandboxed iframe: `sandbox="allow-same-origin"`, strict CSP,
  remote images blocked by default with a "load images" control, `javascript:` and `data:`
  URIs stripped, link-text-vs-href mismatch badged (D3).
- **Virtualised list** over cursor pages; optimistic read-state with reconciliation against
  Gmail as source of truth.
- **Mobile** is single-pane, inbox-first, with the companion as its own route. The three
  desktop regions are never compressed into one narrow view.

## 7. Security checklist for phase 12

| Control | Verified by |
|---|---|
| RLS enforced for the app role | Test: user A reads zero of user B's rows |
| No LLM in the executor | Import-graph test |
| Plane invariants | Registry validation test |
| Injection corpus | 6/6 pass, zero side effects |
| Approval replay | Same token twice → 409 |
| Stale approval | Thread change → `superseded` |
| Idempotency | Duplicate execute → one provider call |
| Token encryption | No plaintext token in DB or logs |
| Budget enforcement | Hard cap blocks before the model call |
| Attachment handling | No parsing path exists in v1 |
| HTML rendering | Injection corpus renders inert |
| Audit coverage | Every Plane X execution has an `audit_logs` row |

## 8. v3.1 — memory API and new job types

### Memory endpoints

```
GET    /api/v1/memory/facts              ?type=preference|interest|relationship|project_fact
→ [{id, fact_type, content, source, evidence, confirmation_status, expires_at}]

POST   /api/v1/memory/facts/{id}/confirm → confirmation_status = user_confirmed (permanent)
POST   /api/v1/memory/facts/{id}/reject  → user_rejected; never re-proposed
DELETE /api/v1/memory/facts/{id}
DELETE /api/v1/memory/facts              ?type=<t>  — or all
GET    /api/v1/memory/proposals          pending proposals awaiting promotion
GET    /api/v1/memory/conflicts          two live facts, same subject — user resolves
```

Every fact is returned with its `source` and `evidence` span. A fact the user cannot trace to
the message that produced it is a fact they cannot trust, so the settings UI renders both.

There is deliberately **no** `POST /api/v1/memory/facts`. Facts are created only by promotion
from `memory_proposals`, and only the deterministic validator promotes.

### Procedural memory has no API

`agent_definitions/`, `procedures/`, `prompts/` and `tool_contracts/` are read from Git into
an immutable registry at startup. There is no endpoint, no table and no agent tool that writes
them. Changing agent behaviour is a reviewed commit and a deploy — which is the point.

### New job types

Added to §4:

| Type | Dedupe key | Priority | Model? |
|---|---|---|---|
| `memory.promote` | `mempromote:{proposal}` | 90 | No |
| `memory.consolidate` | `consolidate:{user}:{date}` | 150 | No (except summarisation) |
| `memory.expire` | `memexpire:{date}` | 180 | No |
| `cache.sweep` | `cachesweep:{date}` | 200 | No |

All deterministic. A nightly job that runs a model over every user's facts would bill forever;
consolidation is normalised dedupe, date-based expiry and prune-by-observation-count, and a
genuine conflict asks the user rather than being resolved by a model (`05-memory.md` §5).

### MCP server lifecycle

In-process servers are constructed at application startup, after the Git registry loads and
before the first worker claims a job:

```
load Git registry (manifests, procedures, prompts, tool pins)
   → construct in-process MCP servers
   → discover tools, verify every schema hash against its pin   ← fails closed on drift
   → build per-agent filtered schema sets, cache by (agent_id, agent_version, catalog_version)
   → validate_registry()                                        ← plane invariants
   → serve
```

Startup **fails** on schema drift or a plane violation rather than degrading. An agent whose
manifest references a tool it may not hold is a deployment error, not a runtime surprise.

### Security checklist additions to §7

| Control | Verified by |
|---|---|
| Behavioural fact rejected | Injection corpus case: enum refuses the row |
| Procedures immutable at runtime | Import-graph + filesystem-write test |
| Memory tenant isolation | User A reads zero of user B's facts under RLS |
| Plane U cannot discover C tools | Filtered schema set contains no C or X entry |
| MCP schema pinned | Startup fails on an unpinned or drifted schema |
| External MCP result treated as Plane U | Trace shows the extract hop before any plan hop |
| No direct fact write path | Route table has no `POST /memory/facts` |
