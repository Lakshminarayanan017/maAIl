# Maail — High-Level Design

**Version** 3.1 · agent-first · MCP-bounded · memory-aware · harness-engineered
**Prerequisite reading** `00-gap-analysis.md` · whole-system sketch in `../../ARCHITECTURE.md`

> **v3.1 additions:** a cross-cutting harness layer above the agent runtime (§3, §7), MCP as
> a contract boundary for all tools (`06-mcp.md`), and a four-type memory architecture whose
> procedural tier lives in Git (`05-memory.md`). The four invariants, the cost cascade and
> the agent roster are unchanged; invariant 4 is new.

## 1. What the system is

A multi-tenant web application that connects a user's Gmail account, keeps a normalised
thread-first copy of their mail, and runs a roster of **specialised AI agents** over it to
produce classification, priority, summaries, deadlines, action items, opportunity records,
technical findings and reply drafts — with every outward action gated behind explicit human
approval.

Four invariants shape everything:

1. **The thread is the unit of meaning.** Messages are storage; threads are what agents
   reason about and what users read.
2. **No model ever performs an external side effect.** Models read and propose. Code
   executes, after a human approves.
3. **Intelligence is demand-driven.** A cheap agent decides what, if anything, an expensive
   agent should look at.
4. **The LLM is the last necessary step, not the first default.** Deterministic code, then
   cache, then small model, then large. This is the organising principle of the harness
   layer (§3, `07-harness.md`).

## 2. Context diagram

```
                      ┌──────────────────────────────┐
                      │   Browser — React SPA        │
                      │   REST + SSE                 │
                      └───────────────┬──────────────┘
                                      │ HTTPS
                      ┌───────────────▼──────────────┐
                      │   FastAPI application        │
                      │   auth · API · SSE · RLS ctx │
                      └──┬────────────┬──────────────┘
                         │            │
         ┌───────────────▼──┐   ┌─────▼────────────────┐
         │  PostgreSQL      │   │  Agent Runtime       │
         │  data + FTS      │◄──┤  registry · planes   │
         │  + job queue     │   │  budget · traces     │
         └───────▲──────────┘   └─────┬────────────────┘
                 │                    │
         ┌───────┴──────────┐   ┌─────▼────────────────┐
         │  Workers (N)     │   │  Provider Adapters   │
         │  claim jobs      │   │  Gmail · GitHub · LLM│
         └──────────────────┘   └─────┬────────────────┘
                                      │
                          Gmail API · GitHub API · LLM APIs
```

One deployable application plus N identical worker processes. One database. No Redis, no
Celery, no vector store, no microservices — see `00-gap-analysis.md` and §8 below for the
conditions under which each gets added.

## 3. Layers

| # | Layer | Responsibility | Key modules |
|---|---|---|---|
| 1 | Client | SPA, three-region workspace, SSE streaming | `frontend/src` |
| 2 | API | REST, SSE, session auth, tenant context | `modules/api` |
| 3 | **Harness** | Execution Planner, Context Builder, Budget Manager, Trace Manager | `modules/harness` |
| 4 | **Agent runtime** | Agent registry, plane enforcement, bounded run loop | `modules/agents/runtime` |
| 5 | Agents | The ten specialised agents | `modules/agents/defs` + Git manifests |
| 6 | **MCP client host** | Tool catalog, schema pinning, per-agent filtering | `modules/mcp` |
| 7 | **Memory router** | Working, episodic, semantic, procedural retrievers | `modules/memory` |
| 8 | **MCP servers** | `mail`, `search`, `memory`, `productivity`, `github` | `modules/mcp_servers` |
| 9 | Domain services | Threads, ingest, sync, features, rules, retrieval, style, approvals | `modules/*` |
| 10 | Executor (Plane X) | Approved actions, no LLM | `modules/executor` |
| 11 | Provider adapters | Gmail, GitHub, LLM behind one interface each | `modules/providers` |
| 12 | Data | Postgres + FTS + job queue under RLS · **Git for procedural memory** | `database` · repo |
| 13 | Workers | Job claim loop, sync, scheduled agents, consolidation | `workers` |

Layer 3 is new in v3.1 and sits **above** the runtime, not beside it, because its job is to
decide whether an agent runs at all. Layer 4 remains the policy enforcement point: MCP
servers never decide which agent may use a tool.

Layer 12 is the one place a second store appears, and it is Git, not a database. Procedural
memory is read at deploy time and never written at runtime, which is what makes procedure
poisoning structurally impossible rather than merely defended against (`05-memory.md` §1).

## 4. The cost architecture — how "agents everywhere" stays affordable

Running every agent over every email is what makes agent architectures expensive. The fix
is a tiered cascade where the **router itself is a cheap agent**.

### Tier 0 — deterministic, no model, 100% of mail

Parse, normalise, dedupe, thread-link, **strip quoted chains and signatures**, extract date
*candidates* with a date parser, apply `user_rules`. Zero marginal cost. This tier alone
removes 60–80% of the tokens a naive design would spend.

v3.1 adds the **Execution Planner** in front of every tier: six paths, of which five cost
nothing — user rule match, feature disabled, cache hit, deterministic bypass, budget
exceeded, or invoke. See `07-harness.md` §2.

One guard rail on the bypass path, because it is the only harness optimisation that can lose
a user's mail: **a bypass may only reduce work, never suppress a thread from view, and it
requires positive evidence of unimportance — never the absence of evidence of importance.**
An unknown sender is always triaged. Bypass rate is tracked, never targeted
(`07-harness.md` §3).

### Tier 1 — Triage Agent, cheap model, 100% of new threads

One call. Input is subject, sender, headers and the first ~500 tokens of *stripped* body —
not the whole thread. Output is category, priority, `needs_reply`, and a **routing
decision**: which specialist agents, if any, should run.

### Tier 2 — specialist agents, mid or strong model, routed only

Runs only when Triage routes to it **and** the feature is enabled **and** (for the expensive
ones) the user opens the thread or priority crosses a threshold. This is where the
demand-driven principle lives.

### Tier 3 — Companion, strong model, user-initiated

Always allowed, always budget-checked.

### The arithmetic

For the planning document's own example — 60 emails/day, roughly 1,800 threads/month:

| Tier | Volume/month | Input tokens each | Model class | Monthly input |
|---|---|---|---|---|
| 0 | 1,800 | — | none | 0 |
| 1 | 1,800 | ~700 | small | ~1.3 M |
| 2 | ~250 (≈14% routed) | ~3,000 | mid/strong | ~0.75 M |
| 3 | ~100 turns | ~4,000 | strong | ~0.4 M |

Against the naive design — a full intelligence pass on every email with unstripped
bodies — that is roughly an order of magnitude less spend on strong models, and the bulk of
remaining volume sits on the cheapest tier. The two levers doing the work are **quote
stripping** (Tier 0) and **routing** (Tier 1), not model choice.

Every number above is a planning estimate. `agent_runs.cost_micros` makes the real figure
observable per agent from day one, which is the point.

## 5. The agent roster

Ten agents. Each one earns its place by holding tools, making a routing decision, or owning
a distinct output contract — not by being a renamed function call.

| Agent | Trigger | Plane | Model | Tools | Writes |
|---|---|---|---|---|---|
| **Triage** | new or significantly-changed thread | U | small | `sender_history` | `thread_intelligence`, routes |
| **Summarizer** | thread opened, or priority ≥ high | U | mid | `get_thread` | `thread_summaries` |
| **Deadline** | routed | U | mid | `get_thread`, `date_candidates` | `deadlines` |
| **ActionItem** | routed | U | mid | `get_thread` | `action_items` |
| **Opportunity** | routed + feature on | U | mid | `get_thread`, `search_threads` | `opportunities` |
| **Developer** | routed (technical) | U↔C | strong | `get_thread`, `search_threads`, `github_*` | `dev_findings`, proposals |
| **Response** | user request, or Triage suggestion | U→C | strong | `get_thread`, `style_profile`, `search_threads` | `proposed_actions` |
| **Organizer** | routed | U | small | `get_thread` | `proposed_actions` (label/archive) |
| **Briefing** | daily schedule | **C** | mid | stored-intelligence queries only | `briefings` |
| **Companion** | user message | U→C | strong | all read tools, `delegate` | `chat_messages`, proposals |

Two details that make this a real architecture rather than a costume:

- **Agents share services through tools.** `get_thread`, `search_threads` and
  `date_candidates` are one implementation each. Agents are thin: a policy, a tool subset,
  an output schema, a budget. Logic lives in services beneath the tool layer.
- **Briefing runs in Plane C and never sees raw email.** It composes from stored
  intelligence rows. That is both cheaper and the only safe way to run a scheduled,
  unattended agent.

### Orchestration

```
Gmail delta ─► Sync ─► Normalize ─► Tier 0 ─► Triage Agent
                                                   │
                                      routes (0..n specialists)
                                                   │
             ┌────────────┬────────────┬───────────┼───────────┬─────────────┐
             ▼            ▼            ▼           ▼           ▼             ▼
         Summarizer   Deadline    ActionItem  Opportunity  Developer    Organizer
             │            │            │           │           │             │
             └────────────┴────────────┴─────┬─────┴───────────┴─────────────┘
                                             ▼
                                  thread_intelligence (+ per-capability status)
                                             │
      user ──► Companion Agent ──delegate──► Response / Developer
                                             │
                                      proposed_actions
                                             │
                                   human approval (UI)
                                             ▼
                                   Plane X executor (no LLM)
                                             ▼
                                  Gmail / GitHub / tasks + audit_logs
```

Supervisor pattern: Triage is the automated supervisor, Companion is the interactive one.
The call graph is a declared DAG with maximum delegation depth 2.

## 6. v1 scope

**In:**

1. Google sign-in and Gmail connection, with the `reauth_required` path built from the start
2. Two-pass sync — metadata skeleton, then bodies, resumable with progress
3. Tier 0 pipeline including quote stripping and `user_rules`
4. Triage Agent — category, priority, `needs_reply`, routing
5. Smart Inbox — cursor pagination, FTS search, filters, thread grouping
6. Thread detail with safe HTML rendering and an evidence-linked intelligence panel
7. Summarizer, Deadline and ActionItem agents
8. Companion Agent scoped to the open thread, with citations
9. Feature controls that genuinely gate agent execution
10. Approval flow and Plane X executor for exactly one action type: `create_gmail_draft`

**Deferred, with the gate that unlocks each:**

| Deferred | Unlocks when |
|---|---|
| Developer agent + GitHub | v1 agents pass eval; GitHub read scope designed |
| Opportunity, Organizer, Briefing | Triage routing accuracy measured |
| Insights dashboard | There is enough history to be worth charting |
| Tasks module | Action items prove useful in practice |
| Embeddings / pgvector | FTS recall measured and found wanting |
| Redis / Celery | Job queue depth or scheduling needs justify it |
| Outlook | Second provider actually requested |
| Persistent memory | Something is needed that cannot be derived on demand |

## 7. Cross-cutting concerns

**Tenancy.** Every user-scoped table carries `user_id` with a Postgres RLS policy.
`SET LOCAL app.user_id` is applied by one dependency on the request path and one wrapper on
the job path. Code-level filtering is defence in depth, not the boundary.

**Trust.** The three planes from `00-gap-analysis.md` §D2 are enforced by the runtime: a
Plane U agent declaring a side-effect tool fails at startup, and a unit test asserts the
invariant across the whole registry.

**Observability.** Every agent run and every step is persisted with tokens, cost, latency
and a result digest. Structured logs carry `run_id`, `user_id` and `thread_id`. Cost per
agent per user is a SQL query, not a guess.

**Failure.** Per-capability status on threads, bounded retries with exponential backoff and
a dead-letter state on jobs, soft-fail into `reauth_required` on OAuth loss, and bounded
reconciliation rather than full resync on a dead history cursor.

**Budget.** Monthly per-user token ceiling with a soft and a hard cap, checked before the
model call.

## 8. Technology, and what would change it

| Concern | Choice | Replace when |
|---|---|---|
| Frontend | React + TypeScript + Tailwind + shadcn/ui | — |
| Backend | Python + FastAPI | — |
| Database | PostgreSQL 16 + RLS + `tsvector` | — |
| Jobs | Postgres queue, `FOR UPDATE SKIP LOCKED` | Sustained depth, or cron needs beyond `available_at` |
| Search | Postgres FTS + structured filters | Measured recall below target on a paraphrase set |
| Agents | Direct tool-calling loop in the runtime | A workflow needs durable pause/resume → LangGraph |
| **Tools** | **MCP contracts, in-process transport** | Third-party server, or external exposure → `06-mcp.md` §8 |
| **Procedural memory** | **Git, read at deploy** | Never — this is a security property, not a convenience |
| **Semantic memory** | **Postgres, validated proposals** | — |
| **Working memory** | **Assembled per run, not persisted** | Measured need for cross-process session affinity → Redis |
| **Episodic memory** | **Retrieval view over existing tables** | Recall@10 below target with FTS → pgvector |
| LLM | Provider abstraction, three size tiers | — |
| Streaming | SSE | Server-push beyond sync status is needed |
| Deploy | Docker, managed Postgres | — |

**Still no Redis, Firestore, vector store or object storage.** The reference memory
architecture proposes four datastores; v3.1 uses one database plus the Git repository. Each
deferred technology has a named trigger above, and none of them fires in v1.

**On LangGraph:** not in v1. The agents here are single-purpose tool-calling loops with
runtime-enforced caps, which is a few hundred lines. The moment a workflow needs durable
state across a human approval pause with resumption days later — the Developer agent's
investigate-then-act cycle is the likely first — adopt it for that workflow only.

## 9. Implementation sequence

| Phase | Build | Harness | Done when |
|---|---|---|---|
| 0 | Repo, Docker, Postgres + RLS, migrations, CI | **H0** | A test proves user A cannot read user B's rows |
| 1 | Auth, Gmail OAuth, `reauth_required` path | — | Reconnect after a forced token expiry works |
| 2 | Two-pass sync, thread model, quota limiter | — | 10k-message mailbox syncs, resumable, progress visible |
| 3 | Tier 0 pipeline, quote stripping, `user_rules` | — | Stripping measured at ≥50% token reduction on reply threads |
| 4 | Job queue, worker loop, dedupe, leases | **H1** | Kill a worker mid-job; it recovers exactly once |
| 5 | Agent runtime + harness + MCP client host | **H2** | Plane invariant passes; Plane U agent cannot *discover* a C tool |
| 6 | Triage Agent + eval suite + ~60-thread fixtures | **H3** | Baseline category, priority and routing numbers recorded |
| 7 | Smart Inbox: pagination, FTS, filters | — | 50k threads, page 40 under 200 ms |
| 8 | Thread detail, safe rendering, evidence panel | — | Injection corpus renders inert |
| 9 | Summarizer, Deadline, ActionItem agents | — | Each passes its eval slice; cost regression gate switches on |
| 10 | Companion + Context Builder + Memory Router | — | Every claim resolves to a real evidence span |
| 11 | Feature controls gating real execution | — | Disabling a feature provably stops the agent running |
| 12 | Approvals + Plane X executor + audit | — | Approval cannot be replayed; stale approval is superseded |

Phase 6 is where the eval suite is born, and it grows every phase after.

**Harness levels are bound to phases rather than required upfront.** H0 and H1 only before
the first agent ships; H2 lands with the runtime, H3 with the first agent, H4 after v1. A
harness built ahead of the thing it constrains is speculative work (`07-harness.md` §8).

**Semantic memory and MCP externalisation are not in this sequence.** Semantic facts arrive
with phase 10 (the Companion is the first agent with a reason to propose one); moving an MCP
server out of process has its own trigger table in `06-mcp.md` §8 and is expected not to
fire during v1.

## 10. Primary user journey, mapped to components

A developer opens Maail in the morning.

| Step | Components |
|---|---|
| Overnight mail already synced | Worker → Gmail adapter → Tier 0 → Triage |
| Inbox shows priority and category | `thread_intelligence` → inbox query |
| A CI failure sits at the top | Triage routed it technical + high |
| They open it | Summarizer runs on demand; evidence panel renders |
| They ask the Companion to investigate | Companion delegates to Developer (Plane U extract → Plane C plan → GitHub read → back to U) |
| Maail proposes a reply | Response Agent emits a `proposed_action`, never sends |
| They edit and approve | Approval binds `content_hash` + `context_version` |
| It sends | Plane X executor, idempotent, audited |

No model holds the send capability at any point in that chain.
