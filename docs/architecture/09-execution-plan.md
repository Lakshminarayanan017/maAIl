# Maail — Phase-by-Phase Execution Plan

Sixteen phases. Each one pairs a **backend track** with a **UI track** and ends in something
you can show a person. UI is built alongside the data that feeds it, never ahead of it.

**UI reference:** [08-ui-spec.md](08-ui-spec.md) — locked, unchanged.
**Architecture:** [01-hld.md](01-hld.md) · [02](02-lld-data-model.md) · [03](03-lld-agent-runtime.md) · [04](04-lld-api-sync-modules.md) · [05](05-memory.md) · [06](06-mcp.md) · [07](07-harness.md)

## Three rules that hold for every phase

1. **No fake data in the application.** A screen ships when its real data source exists.
   Mocks live in Storybook and tests, never in the running app.
2. **Every phase ends demoable.** If you cannot show it to someone, the phase is not done.
3. **Blocking gates fail CI. Tracked gates get recorded.** Correctness and security block;
   efficiency and quality are measured and reviewed ([07-harness.md](07-harness.md) §7).

## Phase map

| # | Phase | Screens delivered | Harness |
|---|---|---|---|
| 0 | Foundations & design system | App shell, theming | **H0** |
| 1 | Auth & Gmail connection | 01, 02 | — |
| 2 | Sync & inbox shell | 04 (shell) | — |
| 3 | Tier 0 ingest & thread reading | 05 (left) | — |
| 4 | Job queue & AI status primitives | status components | **H1** |
| 5 | Agent runtime, harness, MCP | AI panel 3 states | **H2** |
| 6 | Triage agent & inbox intelligence | 04 (complete) | **H3** |
| 7 | Overview / Command Center | 03 | — |
| 8 | Intelligence panel | 05 (complete) | — |
| 9 | Summarizer · Deadline · ActionItem | 09 | — |
| 10 | Companion & memory | 06 | — |
| 11 | Feature controls & settings | 11 + onboarding step 3 | — |
| 12 | Approvals & Plane X executor | approval surfaces | — |
| 13 | Developer Hub & Developer agent | 07 | — |
| 14 | Agent Workspace & remaining agents | 08 | — |
| 15 | Insights & Memory | 10 | **H4** |

Phases 0–12 are v1. 13–15 are the P1/P2 screens. The public website is a separate track
([08-ui-spec.md](08-ui-spec.md) §12).

---

## Phase 0 — Foundations & design system

**Backend.** Monorepo layout per [04](04-lld-api-sync-modules.md) §1. Docker Compose with
Postgres 16. Alembic. `users` table. **RLS with `FORCE ROW LEVEL SECURITY` and a non-owner app
role.** `SET LOCAL app.user_id` dependency. Four scripts: `check.sh`, `test.sh`, `db.sh`,
`dev.sh`. `AGENTS.md`. Architecture-lint import tests. Seeded fixtures. Deterministic clock in
the test harness.

**UI.** The design system, as the first code written — not retrofitted.

- Tailwind config carrying the six palette tokens as CSS variables on `:root`, redefined for
  dark under `@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])`
  and again under `:root[data-theme="dark"]`
- Plus Jakarta Sans, Inter, JetBrains Mono loaded; type scale
- 8px spacing scale · radius tokens 10–14px · subtle-border utilities, no heavy shadows
- shadcn/ui installed and themed to the palette; Lucide icon set
- Framer Motion with a 150–200ms default transition
- **AppShell**: three regions — sidebar, centre, right panel — with the sidebar groups from
  [08-ui-spec](08-ui-spec.md) §7, routes stubbed
- Theme switcher: light / dark / system
- Base states: skeleton, empty, error, offline
- Storybook for the component gallery

**Demo.** The shell renders in light, dark and system, at desktop and phone width, with real
tokens and real fonts. Navigation moves between empty routes.

**Blocking gates.** A test proves user A's query returns zero of user B's rows *using the
application's own connection*. Import-lint rejects a forbidden dependency. `dev.sh up` works
from a clean clone.

> Dark mode is designed here, not inverted later. Retrofitting a second theme after fifteen
> phases of components is the expensive version of this work.

---

## Phase 1 — Auth & Gmail connection

**Backend.** Google OAuth 2.0 with `gmail.readonly` only. `connected_accounts`,
`oauth_credentials` with envelope encryption and `key_version`. Token refresh.
**`reauth_required` as a first-class status** — Testing-mode refresh tokens expire in 7 days
([00-gap-analysis.md](00-gap-analysis.md) §2 A3). Scope validator comparing granted against
required. Sessions, CSRF. Disconnect with `purge_after`. Zero LLM.

**UI.** Screens **01** and **02**, exactly as specified.

- Screen 01: hero wordmark, *Your inbox deserves a brain.*, *Understand more. Manage less.*,
  the two-line subhead, `[ Get started → ]`, *Privacy-first · You stay in control*, Sign in
  top-right, product-preview slot
- Screen 02: `Step 1 of 3`, *Let's connect your inbox.*, the Google Gmail card, the three
  `✓` capability lines, `Permissions and privacy →`
- Scope explanation page naming every requested permission in plain words
- **Reconnect banner** — persistent, non-dismissable while `reauth_required`
- Connected-account card in a minimal settings stub: address, status, disconnect

**Demo.** Sign in, connect a real Gmail account, see it connected. Force token expiry; the
banner appears and reconnect works.

**Blocking gates.** Invalid OAuth state rejected. No plaintext token in the database or logs.
Cross-tenant account access rejected. Zero LLM calls in the auth path.

---

## Phase 2 — Sync & inbox shell

**Backend.** Two-pass sync ([04](04-lld-api-sync-modules.md) §3): pass 1 `messages.list` +
`format=METADATA` (20 units), pass 2 `format=FULL` (60 units), newest-first, resumable.
Per-account token-bucket limiter against 6,000 units/min/user. `email_threads` and
`email_messages` with `content_version`. Dedupe by `(account_id, provider_message_id)`. Thread
linking via `Message-ID` / `In-Reply-To` / `References`, plus merge handling. Delta sync on
`historyId` with all four event types. **Bounded reconciliation** on a 404 cursor — never a
blind full resync. Cursor-paginated thread list endpoint. Zero LLM.

**UI.** Screen **04** shell, with real mail and no intelligence yet.

- Three-pane inbox: list centre, preview right, sidebar left
- Email rows showing sender avatar and name, subject, preview, timestamp, attachment indicator
  — the AI category and priority slots are **present but empty**, not faked
- Virtualised list over cursor pages
- **Sync progress**: newest 500 first then backfill, with visible progress — the cold-start
  rule, so the inbox is never blank while syncing
- Skeleton loaders during sync; empty, error and offline states
- Optimistic read-state with reconciliation against Gmail

**Demo.** Your real inbox, scrolling smoothly, syncing with visible progress. Kill the sync
mid-run; it resumes where it stopped.

**Blocking gates.** Repeated and interrupted sync produces identical local state. No duplicate
messages. Quota limiter prevents `userRateLimitExceeded`. A dead history cursor recovers via
bounded reconciliation.

---

## Phase 3 — Tier 0 ingest & thread reading

**Backend.** The deterministic pipeline, entirely model-free: HTML→text · **quote stripping**
and signature removal into `body_text_stripped` with `stripped_ratio` recorded · normaliser ·
date-candidate parser producing spans · `user_rules` deterministic pass · `search_tsv` built
from stripped text. On-demand sanitised body endpoint — raw HTML is **not** stored.

**UI.** Screen **05** left pane — the reading experience.

- Subject, From, Date, message body, `[Reply] [Forward] [Archive]`
- **Body in a sandboxed iframe**: strict CSP, `javascript:`/`data:` URIs stripped
- **Remote images blocked by default** with an explicit "load images" control
- Link-text-versus-href mismatch badged
- Quoted history collapsed by default, expandable
- Thread view: all messages in order, own messages marked
- Inter for email content, JetBrains Mono for code blocks and stack traces

**Demo.** Read your real mail inside Maail, safely, with quoted chains collapsed.

**Blocking gates.** Quote stripping measured at **≥50% token reduction** on reply threads with
**no loss of new content** and evidence offsets still resolvable. The injection corpus renders
inert. No tracking pixel loads without consent.

> This phase is the single largest cost saving in the project and it uses no AI at all.

---

## Phase 4 — Job queue & AI status primitives · H1

**Backend.** `background_jobs` with atomic claim (`FOR UPDATE SKIP LOCKED` in one statement),
leases, lease reaper, exponential backoff, `dead` terminal state, `dedupe_key` with a partial
unique index. Worker entrypoints. `intelligence_cache` with the nine-part key. The
**significance gate** ([03](03-lld-agent-runtime.md) §6). Zero LLM in job lifecycle.

**UI.** The status vocabulary every later screen depends on.

- **`AiValue`** — the one component through which every AI-derived value renders, taking
  `{value, evidence, status, source}` and exposing a source affordance that opens the evidence
  span. Soft lavender `#E8E2F5` marks AI-derived content; facts from the email do not carry it.
- Per-capability status chips: `analysing` · `ready` · `failed` · `disabled`
- Skeleton variants for summary, deadline and action-item blocks
- Error and retry affordances
- Storybook coverage of every state

**Demo.** A Storybook page showing every AI state, and an inbox row rendering real
`capability_status` values from the database.

**Blocking gates.** A worker killed mid-job recovers exactly once. A duplicate event reuses the
existing job rather than enqueuing a second. Cache key changes on any of its nine components.

> `AiValue` exists before any agent so that no screen ever renders an AI value without its
> provenance. Done later, this becomes a refactor of every screen.

---

## Phase 5 — Agent runtime, harness & MCP · H2

**Backend.** Agent registry loaded from `agent_definitions/*.yaml` in Git. Bounded run loop
with `max_steps`, `max_tokens`, `max_wall_clock_s`. **Plane enforcement** with startup
validation. `agent_runs` and `agent_steps` traces. Harness layer: Execution Planner, Context
Builder, Budget Manager. MCP client host: catalog, **schema pinning**, per-agent filtering,
in-process transport. `mail` and `search` MCP servers. LLM provider abstraction, three tiers.
`usage_budgets`.

**UI.** The AI panel's three states, plus internal observability.

- **Option C** implemented: collapsed floating affordance → contextual side panel →
  full-screen companion, with one store holding state across pages
- Panel is context-aware: it knows the selected thread
- Smooth 150–200ms transitions between states
- Mobile: the panel is a separate view, never a squeezed third pane
- **Internal traces view** (not a P0 screen, dev-only route): run list, step timeline, tokens,
  cost, tool calls, result digests

**Demo.** The AI panel opens, expands and goes full-screen across every page. A trace of a
hello-world agent run is inspectable end to end with its cost.

**Blocking gates.** A Plane U agent **cannot discover** a Plane C or X tool — the filtered
schema set contains zero such entries. Startup fails on schema drift or a plane violation. A
run exceeding a cap fails into a recorded terminal state. No agent holds a side-effect tool.

---

## Phase 6 — Triage agent & inbox intelligence · H3

**Backend.** Triage Agent: small model, `get_sender_history`, output `category`, `priority`,
`priority_reason`, `needs_reply`, `is_technical`, `route_to`. `thread_intelligence` with
per-capability status and `thread_intelligence_versions`. `user_rules` run **before** the agent.
Deterministic bypass under the **asymmetric rule** — may only reduce work, never hide a thread,
never on an unknown sender. Eval suite: ~60 thread fixtures split by thread, golden traces,
the six-case injection corpus. Cost per eval run recorded.

**UI.** Screen **04** complete.

- AI category chips and priority indicators now populated, through `AiValue`
- Badges exactly as specified: `High priority` · `Technical` · `AI classified`
- **Classification correction control** on every row, writing `user_overrides` and offering a
  suggested `user_rule`
- All eight filters live: All · Unread · Important · Technical · Opportunities · Team
  communication · Notifications · Archived
- Priority route as its own page
- `priority_reason` on hover or expand — never an unexplained badge

**Demo.** Your real inbox, classified and prioritised, with corrections that stick.

**Blocking gates.** Injection corpus 6/6, zero side effects. No thread hidden by a bypass. An
unknown sender is always triaged. Macro-F1 and priority precision recorded as the baseline.

**Tracked.** Routing precision and recall · bypass rate · cost per thread · model-call count.

> Routing precision is the most important number in the system — it sets the cost of every
> downstream phase. **Bypass rate is tracked, never targeted.**

---

## Phase 7 — Overview / Command Center

**Backend.** Aggregate endpoints over stored intelligence — counts, priority threads, upcoming
deadlines slot, developer-activity slot. No reprocessing of email. Inbox performance: indexes
verified, `(user_id, latest_message_at DESC, id DESC)` cursor paths, debounced search over FTS.

**UI.** Screen **03**, exactly as laid out.

- Time-aware greeting · *Your day, simplified.*
- Count cards (`24 Emails`, `5 Attention`) — **plain counts, visually distinct from AI
  classifications**, per the spec's warning against presenting estimated urgency as fact
- *Today's important items* with priority cards carrying category tags
- *Upcoming deadlines* (empty until phase 9, with a real empty state)
- Right panel: *Maail AI · Daily briefing* slot, `[ Explore → ]`, `Ask Maail...`
- **Clicking a priority card opens the email detail with the right panel already focused** —
  the specified interaction

**Demo.** The morning screen, on your real mail. Click a card, land on the email.

**Blocking gates.** 50k threads, page 40 under 200 ms. Zero model calls to open, filter, sort
or paginate the inbox.

---

## Phase 8 — Intelligence panel

**Backend.** `GET /threads/{id}/intelligence` returning every field with its evidence.
Summarizer agent on-demand, cached by `content_version`. Entity extraction. Intent detection.
Related-context retrieval over FTS.

**UI.** Screen **05** right pane — the product differentiator.

All six sections, in the specified order: **Summary** · **Intent detection** · **Extracted
entities** (projects, repositories, technologies, dates, error messages, people and
organizations) · **Action items** · **Related context** · **Suggested response** (slot, filled
in phase 12).

- Every value through `AiValue`, with a source affordance opening the exact evidence span
- **Three visually distinct provenance classes**, as the spec requires: stated in the email ·
  AI interpretation · retrieved from an integration
- `✧` markers and soft lavender on AI sections
- Suggested actions: `[Investigate]` `[Draft response]` `[Find related emails]`
- Per-section status — a failed deadline pass shows as failed while the summary shows ready

**Demo.** Open a real CI-failure email and see its meaning, with every claim traceable to the
text that produced it.

**Blocking gates.** Every AI value resolves to a real evidence span. A value with no evidence
renders as "not determined", never as a bare value. No model call to re-open a thread whose
summary is current.

---

## Phase 9 — Summarizer · Deadline · ActionItem

**Backend.** Deadline Agent over deterministic `date_candidates` — classification, not
arithmetic — writing `raw_phrase`, `date_type`, `resolution_status`, `confidence_band`,
timezone and evidence offsets. ActionItem Agent separating `stated` from `inferred`. `tasks`
with `origin` and `confirmed_at`. Follow-up detection.

**UI.** Screen **09**, plus the deadline resolver.

- `[All] [Today] [Upcoming] [Completed]`, TODAY / UPCOMING / COMPLETED sections
- Checkboxes, `From:`, `Due:`, link back to the source email
- Create task from an email · mark complete · change deadline · add notes · set reminders
- **Deadline ambiguity resolver**: an `ambiguous` row renders as a question with the raw
  phrase quoted — *"'by Friday' — which Friday?"* — never as an invented date
- **Stated versus inferred** visually distinguished on both deadlines and action items
- Correct-the-date control writing `user_corrected`

**Demo.** Your emails have become a task list, with the uncertain dates asking rather than
guessing.

**Blocking gates.** Exact-match on resolved dates **and ambiguity recall** — correctly saying
"unclear" is a pass, not a miss. `stated` and `inferred` never conflated. No repeated run for
identical content, config and agent version. **Cost-regression gate switches on here**, with
three agents to compare.

---

## Phase 10 — Companion & memory

**Backend.** Companion Agent, strong tier, MCP read tools plus `delegate`, depth cap 2.
Deterministic **intent router**: lookup → SQL/FTS, cached → stored intelligence, reasoning →
retrieval plus model. Memory Router with the four retrievers. Context Builder enforcing the
token budget with conversation summarisation on overflow. `semantic_facts` and
`memory_proposals`, **Plane C writes only**, closed `fact_type` enum. SSE streaming. Citation
validation.

**UI.** Screen **06**, plus the memory inspector.

- Conversations sidebar: `New chat`, recent chats
- *What would you like to understand today?* · suggested prompts · `Ask anything about
  emails... [↑]`
- Token streaming; visible tool events so the user sees what the agent did
- **Clickable citation chips** resolving to the exact message and span
- Follow-up questions · regenerate · edit
- Works in all three panel states — thread-scoped in the contextual panel, free in full-screen
- **Memory inspector** in settings: every fact with content, source, evidence span,
  confirmation status, expiry; confirm / reject / delete; conflict resolution prompts

**Demo.** Ask about your real mail and get a cited answer. A simple lookup returns with **zero
model calls**.

**Blocking gates.** Every claim about email content carries a citation resolving to a real
span. A behavioural "fact" in an email is **rejected at the enum**. User A's facts never
appear for user B. No code path writes `procedures/` at runtime.

**Tracked.** Share of turns resolved with zero model calls · context tokens before and after
the Context Builder · cache hit rate.

---

## Phase 11 — Feature controls & settings

**Backend.** Feature registry with the full toggle list, dependency resolver, per-feature
config schemas, the three presets, cached config with controlled invalidation. **Toggles gate
real execution** — the Execution Planner consults them before any agent runs. Disabling stops
future processing and **retains existing results**.

**UI.** Screen **11**, plus onboarding step 3 — the full locked list from
[08-ui-spec](08-ui-spec.md) §10.

- *Personalize your intelligence* · *"Choose what Maail should handle for you. You can change
  these anytime."*
- All four groups with every toggle and its exact description, ten on by default
- `N features enabled` · `Enable all` · `Save configuration`
- Per-feature config drawers — Priority detection showing **Strict / Balanced / Sensitive**
  with the specified wording
- Three presets: **Minimal** (Lightweight) · **Productivity** (Recommended) · **Developer**
  (Developer-first)
- **Entry point A**: onboarding step 3, presets offered so nobody configures seventeen toggles
- **Entry point B**: Settings → AI preferences
- **Entry point C**: contextual suggestions — *"Want Maail to automatically identify upcoming
  deadlines?"*
- All nine settings sections: Account · Email accounts · AI preferences · Memory · Agents ·
  Integrations · Privacy · Appearance · Notifications

**Demo.** Turn off Instant summaries; the summary stops being generated and the existing one is
still there. Apply the Developer preset; the toggles move together.

**Blocking gates.** A test proves a disabled feature **never executes**. Disabling does not
delete stored results. No model call to evaluate whether a toggle is on.

---

## Phase 12 — Approvals & Plane X executor

**Backend.** `proposed_actions` with `content_hash`, `context_version`, single-use
`approval_token_hash`, `expires_at`, `idempotency_key`. Response Agent emitting
`create_gmail_draft` only. `permission_grants` with **separate send authorization**. Plane X
executor — no LLM, re-validating allowlist, grant, hash, version, token and idempotency.
`audit_logs` on every execution.

**UI.** The approval surfaces, and the Suggested response slot filled.

- **Approval card**: `target_summary` in plain words, full params, evidence links, expiry
- Draft editor — editing recomputes the hash and requires fresh approval
- Client **echoes the `content_hash`** it displayed; a mismatch shows the **superseded** state
  explaining that the thread changed
- Separate consent flow before the first send, distinct from read access
- Audit view: what was done, when, under which approval
- `[Draft response]` in Screen 05 and the Companion's proposals both route here

**Demo.** Maail drafts a reply to a real email. You edit it, approve it, it sends. Approve a
draft, let a new message land, and watch the approval correctly refuse itself.

**Blocking gates.** Approval token cannot be replayed. A stale approval is superseded, not
honoured. Duplicate execute produces **one** provider call. No model participates in validation
or execution. Every execution has an audit row.

**v1 is complete here.**

---

## Phase 13 — Developer Hub & Developer agent

**Backend.** Developer Agent with the **ping-pong plane pattern**: Plane U extract (no tools
that act) → Plane C plan → GitHub read → back to Plane U → Plane C conclude. `github` MCP
server, read-only, **explicitly connected repositories only**. `dev_findings` where a root
cause requires `supporting_evidence_count > 0`. GitHub OAuth, separate grant.

**UI.** Screen **07**.

- *Technical communication, organized.*
- Stat cards: CI failures · API issues · Pending review
- Technical activity list with `[Analyze issue]` and `[View discussion]`
- *Connected tools: GitHub · More integrations*
- **Evidence-gated findings** — debugging context presented as gathered evidence, never as a
  diagnosis, per the spec's warning
- Repository connection UI with per-repo consent
- Mobile: stacked cards, not a squeezed dashboard

**Blocking gates.** An injected instruction in a GitHub issue comment produces zero side
effects. No finding claims a root cause without evidence. Unconnected repositories are
unreachable.

---

## Phase 14 — Agent Workspace & remaining agents

**Backend.** Opportunity Agent (with a prior-thread check before claiming a new opportunity),
Organizer Agent, Briefing Agent — **Plane C, stored intelligence only, never raw email**,
scheduled via `available_at`. `opportunities`. Agent enable/disable per user.

**UI.** Screen **08**.

- Agent cards with the five specified agents, descriptions and `Active` status
- Agent detail: purpose · inputs and permissions · recent executions · actions performed ·
  **reasoning summary and evidence** · errors and status · approval requirements ·
  enable/disable
- **Readable execution explanations, not raw chain-of-thought** — the spec is explicit
- Daily briefing rendered in the Overview right panel, filling the phase 7 slot
- Mobile: agent list

**Blocking gates.** A disabled agent never executes. The Briefing agent reads zero raw email.
Execution explanations expose no internal reasoning traces.

---

## Phase 15 — Insights & Memory · H4

**Backend.** Aggregate analytics views over existing records. Memory consolidation job —
**deterministic**: normalised dedupe, date expiry, prune by observation count; conflicts ask
the user. H4: cost-regression detection, stale-doc checks, dead-code detection.

**UI.** Screen **10**.

- **Communication analytics**: incoming emails over time · important versus low-priority ·
  pending replies · most active conversations
- **Developer analytics**: technical issue discussions · common project references · repeated
  error patterns · open development conversations
- **Personal memory**: writing style · frequently discussed topics · active projects ·
  frequently contacted people — each **inspectable, editable and deletable**
- Charts using the locked palette; violet as the primary series

**Blocking gates.** Every displayed memory is traceable to its source. Delete actually deletes.
Consolidation makes no unbudgeted model calls.

---

## Coverage check

**All eleven screens placed.** 01, 02 → phase 1 · 03 → 7 · 04 → 2 then 6 · 05 → 3 then 8 ·
06 → 10 · 07 → 13 · 08 → 14 · 09 → 9 · 10 → 15 · 11 → 11.

**All seventeen feature toggles placed** in phase 11, with the four groups, ten-on default,
per-feature config and three presets.

**All four interaction flows validated:** Flow A (technical email) by phase 13 · Flow B
(personalized response) by 12 · Flow C (finding an internship) by 14 · Flow D (asking Maail) by 10.

**Design system complete at phase 0** — palette, typography, 8px scale, 10–14px radii, subtle
borders, Lucide, 150–200ms motion, skeleton and empty/error/offline states, light + dark +
system.

**Responsive rules honoured throughout.** Desktop three-pane; mobile single-pane with the AI
companion as a separate view; the three panels are never compressed into one narrow view.

## Deliberate ordering choices

| Choice | Why |
|---|---|
| Design system is phase 0, not phase 7 | Retrofitting dark mode across fifteen phases of components is the expensive version |
| `AiValue` lands in phase 4, before any agent | So no screen ever renders an AI value without provenance; later it is a refactor of everything |
| Quote stripping in phase 3, before any model | Biggest cost saving in the project, and it needs no AI |
| Eval suite with the *first* agent, not after the last | An agent without a regression suite cannot be improved, only changed |
| Inbox shell ships with empty AI slots | Honest about what exists; no fake data in a running app |
| Approvals last in v1 | The only phase that can touch the outside world ships once everything feeding it is tested |
| Developer Hub after v1 | The signature feature needs the plane model proven on simpler agents first |
