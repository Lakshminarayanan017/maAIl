# Maail — Harness Engineering Blueprint



New architectural principle

Cross-cutting engineering standard



This is a very important addition. I want us to make harness engineering a fundamental part of Maail, not a separate development tool that we occasionally use.

And I want to establish one distinction first.

## 1. Maail needs two levels of harness engineering

Level 1 — Development Harness Engineering

This controls how we build Maail using coding agents and engineering tools such as Codex.

The objective is to make coding agents understand the project, follow architecture, avoid unnecessary work, run tests, detect mistakes and verify their changes without repeatedly asking an LLM what to do.

Level 2 — Runtime Harness Engineering

This controls how Maail's own AI agents operate when users interact with the application.

The objective is to eliminate unnecessary LLM calls, retrieve only relevant data, constrain tool usage, reuse previous intelligence, and verify outputs deterministically.

# Two harnesses. One engineering philosophy.

Development Harness

Controls the engineering process.

- Repository knowledge
- Coding instructions
- Architecture enforcement
- Reusable scripts
- Automated testing
- Coding-agent feedback loops

Runtime Harness

Controls the product's AI execution.

- Deterministic processing
- Context selection
- Model routing
- MCP tool control
- Token and execution budgets
- Caching and reuse
- Output verification

This follows the central idea of harness engineering: engineering effort moves beyond writing prompts and code, toward designing an environment where agents can reliably accomplish work. OpenAI's engineering account specifically emphasizes repository legibility, executable feedback loops, architecture enforcement and continuous maintenance.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://openai.com\&sz=32)

OpenAI+1



Our objective is not to make the LLM smarter at everything. It's to build a system that doesn't need an LLM for everything.

# 2. The Maail harness engineering principles

I propose we establish these 12 principles across the entire project.

| #  | Principle                 | How Maail applies it                                           |
| -- | ------------------------- | -------------------------------------------------------------- |
| 1  | Deterministic first       | Solve problems using code before calling a model               |
| 2  | Context minimization      | Send only relevant information                                 |
| 3  | Progressive disclosure    | Load capabilities only when needed                             |
| 4  | Reuse                     | Never regenerate unchanged intelligence                        |
| 5  | Contract enforcement      | Validate every input and output                                |
| 6  | Explicit execution        | No agent executes arbitrary operations                         |
| 7  | Bounded autonomy          | Limit steps, tokens, time and tool calls                       |
| 8  | Observability             | Record why each model or tool was invoked                      |
| 9  | Feedback loops            | Test every important behavior                                  |
| 10 | Architectural enforcement | Make invalid dependencies difficult to introduce               |
| 11 | Self-service engineering  | Give coding agents scripts and project knowledge               |
| 12 | Continuous cleanup        | Detect stale docs, duplicated services and unused capabilities |

These principles should become part of the engineering standards in our repository.

# 3. Harness application across every HLD development stage

I am using the 13 implementation phases in `01-hld.md` as the source of the development sequence. The following is the additional harness specification for each phase, not a replacement for the existing design.&#x20;

01-hld.md



## Phase 0 — Repository, Docker, PostgreSQL, RLS and CI

Harness priority: foundational

Problem: Coding agents may create duplicated modules, violate architectural boundaries, generate inconsistent migrations and forget project conventions.

Harness to implement:

| Harness               | Implementation                                            |
| --------------------- | --------------------------------------------------------- |
| Repository map        | Short `AGENTS.md` linking to architecture and module docs |
| Architecture linter   | Check prohibited module dependencies                      |
| Migration validator   | Detect schema migration inconsistencies                   |
| Environment harness   | One-command Docker development environment                |
| Test harness          | Standardized unit, integration and security test commands |
| Documentation harness | Validate links and required module documentation          |
| Worktree harness      | Isolated development environment for each coding task     |

Expected automation:

```
scripts/
├── setup.sh
├── dev.sh
├── check.sh
├── test-unit.sh
├── test-integration.sh
├── test-security.sh
├── db-reset.sh
├── db-migrate-check.sh
└── architecture-check.sh
```

A coding agent should not need to ask how to start Maail, where to run tests or how to validate a migration.

Acceptance gate: A fresh development environment can be initialized and all baseline checks run from documented commands.

## Phase 1 — Authentication and Gmail OAuth

Problem: Incorrect token handling, repeated authentication logic and insecure account access.

| Harness                       | Application                                                 |
| ----------------------------- | ----------------------------------------------------------- |
| OAuth state validator         | Deterministically validate state and callback               |
| Scope validator               | Compare actual granted scopes against required capabilities |
| Token lifecycle monitor       | Detect expiration and `reauth_required`                     |
| Credential encryption harness | Enforce encryption and key-version rules                    |
| Authentication contract tests | Test login, callback, reconnect and disconnect              |
| Tenant isolation tests        | Attempt cross-user account access                           |

LLM usage: Zero.

No LLM should participate in authentication, authorization or token management.

Acceptance gate: Invalid state, expired credentials, insufficient scopes and cross-tenant access are rejected automatically.

## Phase 2 — Gmail sync and thread construction

Problem: Repeated fetching, inconsistent thread grouping, quota exhaustion and duplicate jobs.

| Harness                  | Application                                             |
| ------------------------ | ------------------------------------------------------- |
| Metadata-first sync      | Fetch message skeletons before full bodies              |
| Incremental sync harness | Use Gmail history cursor                                |
| Quota limiter            | Prevent exceeding per-account request budgets           |
| Idempotency harness      | Repeated sync doesn't duplicate messages                |
| Thread reconstruction    | RFC-822 Message-ID and References                       |
| Reconciliation harness   | Recover expired history cursors                         |
| Failure injection        | Simulate 404s, rate limits, timeouts and worker crashes |

The current HLD already specifies two-pass synchronization, a per-account quota limiter and resumable syncing.&#x20;

01-hld.md



LLM usage: Zero.

Thread reconstruction must be deterministic. Do not use an LLM to decide whether two messages belong to a thread.

Acceptance gate: Repeated and interrupted synchronization produces the same correct local state.

## Phase 3 — Tier 0 ingestion and normalization

Major LLM cost reduction

This phase should be almost entirely deterministic.

| Module             | Harness                                           |
| ------------------ | ------------------------------------------------- |
| HTML parser        | HTML-to-text converter                            |
| Quote stripper     | Detect quoted replies and remove repeated content |
| Signature detector | Deterministic signature patterns                  |
| Date parser        | Extract candidate phrases and spans               |
| Normalizer         | Consistent message schema                         |
| Deduplicator       | Database uniqueness constraints                   |
| User rules         | Apply user-defined rules before AI routing        |

The existing design already identifies quote stripping as a major token-saving mechanism and applies it before agents receive messages.&#x20;

03-lld-agent-runtime.md



I would add a benchmark to this phase:

```
Input:
10-message email conversation

Output:
10 normalized messages
10 stripped bodies
10 quote-removal measurements

Validation:
No new message content lost
Quoted content not repeatedly passed to agents
Original evidence offsets remain resolvable
```

Acceptance gate: Measure token reduction across a representative reply-thread dataset. Do not optimize only for a reduction percentage; ensure the stripping algorithm does not remove meaningful new content.

## Phase 4 — PostgreSQL job queue and workers

Problem: Repeated jobs, duplicate processing and wasted model calls following worker failures.

Harness:

- Deduplication keys.
- Job leases.
- Atomic job claiming.
- Bounded retry policies.
- Dead-letter states.
- Retry classification by error type.
- Worker crash simulation.
- Idempotent intelligence writes.

Example:

```
triage:<thread_id>:<content_version>
```

A duplicate event should reuse the existing job rather than start another Triage Agent execution.

LLM usage: Zero for job lifecycle management.

Acceptance gate: A worker killed halfway through a job recovers without producing duplicate intelligence or spending on unnecessary repeated inference.

## Phase 5 — Agent runtime and MCP client manager

Critical harness layer

This is where both our harness architecture and MCP architecture meet.

The Agent Runtime should be responsible for making sure each agent gets exactly the capabilities and context it needs.

| Component           | Harness                                          |
| ------------------- | ------------------------------------------------ |
| Agent registry      | Declarative agent manifests                      |
| MCP server registry | Discover and cache server capabilities           |
| MCP client manager  | Reuse connections and sessions appropriately     |
| Tool filtering      | Only expose permitted tools to each agent        |
| Tool schema cache   | Avoid repeated discovery and schema construction |
| Context manager     | Build minimal agent-specific context             |
| Budget manager      | Enforce tokens, cost, steps and time             |
| Execution manager   | Bounded loops and termination conditions         |
| Trace manager       | Record every model and tool invocation           |
| Output validator    | Pydantic schema validation                       |
| Plane enforcement   | Prevent unauthorized tools and data flows        |

### Special MCP harness

We should not expose the entire MCP tool catalog to every agent.

Consider 40 tools across five MCP servers.

Without filtering, we risk sending unnecessary tool schemas and descriptions with every model request.

Instead:

```
Agent request
     |
     v
Identify agent identity
     |
     v
Load agent manifest
     |
     v
Check allowed MCP servers
     |
     v
Load allowed tool schemas
     |
     v
Filter by task capability
     |
     v
Construct model request
```

Additional optimizations:

1. Cache discovered tools by server identity and schema version.
2. Maintain a stable tool registry rather than rediscovering everything per turn.
3. Load only the permitted tool schemas for the current agent.
4. Limit returned records and response sizes.
5. Reuse existing connections where transport permits.
6. Validate inputs and results using the same contracts.
7. Block tools that violate the agent's trust plane.

The MCP protocol provides the standardized server/client interaction; Maail's runtime supplies the policy, context and budget harness around it.

Acceptance gate: A Plane U agent must be unable to discover or invoke unauthorized Plane C or Plane X capabilities.

## Phase 6 — Triage Agent and evaluation

Problem: Repeatedly calling a model when deterministic rules can already classify an email.

I recommend one additional optimization to the current HLD.

Introduce a Rule-first Triage Fast Path.

\#chatgpt-mermaid-\_r_3rd\_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(237, 237, 237);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_3rd\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_3rd\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_3rd\_ .error-icon{fill:rgb(48, 48, 48);}#chatgpt-mermaid-\_r_3rd\_ .error-text{fill:rgb(237, 237, 237);stroke:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3rd\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_3rd\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_3rd\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_3rd\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_3rd\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_3rd\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_3rd\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3rd\_ .marker.cross{stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3rd\_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-\_r_3rd\_ p{margin:0;}#chatgpt-mermaid-\_r_3rd\_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3rd\_ .cluster-label text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3rd\_ .cluster-label span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3rd\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_3rd\_ .label text,#chatgpt-mermaid-\_r_3rd\_ span{fill:rgb(237, 237, 237);color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3rd\_ .node rect,#chatgpt-mermaid-\_r_3rd\_ .node circle,#chatgpt-mermaid-\_r_3rd\_ .node ellipse,#chatgpt-mermaid-\_r_3rd\_ .node polygon,#chatgpt-mermaid-\_r_3rd\_ .node path{fill:rgb(9, 23, 44);stroke:rgb(31, 78, 148);stroke-width:1px;}#chatgpt-mermaid-\_r_3rd\_ .rough-node .label text,#chatgpt-mermaid-\_r_3rd\_ .node .label text,#chatgpt-mermaid-\_r_3rd\_ .image-shape .label,#chatgpt-mermaid-\_r_3rd\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_3rd\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_3rd\_ .rough-node .label,#chatgpt-mermaid-\_r_3rd\_ .node .label,#chatgpt-mermaid-\_r_3rd\_ .image-shape .label,#chatgpt-mermaid-\_r_3rd\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_3rd\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_3rd\_ .root .anchor path{fill:rgb(175, 175, 175)!important;stroke-width:0;stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3rd\_ .arrowheadPath{fill:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3rd\_ .edgePath .path{stroke:rgb(175, 175, 175);stroke-width:1px;}#chatgpt-mermaid-\_r_3rd\_ .flowchart-link{stroke:rgb(175, 175, 175);fill:none;}#chatgpt-mermaid-\_r_3rd\_ .edgeLabel{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_3rd\_ .edgeLabel p{background-color:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_3rd\_ .edgeLabel rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_3rd\_ .labelBkg{background-color:rgba(0, 0, 0, 0.5);}#chatgpt-mermaid-\_r_3rd\_ .cluster rect{fill:rgb(48, 48, 48);stroke:rgba(255, 255, 255, 0.15);stroke-width:1px;}#chatgpt-mermaid-\_r_3rd\_ .cluster text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3rd\_ .cluster span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3rd\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(48, 48, 48);border:1px solid rgba(255, 255, 255, 0.15);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_3rd\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3rd\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_3rd\_ .icon-shape,#chatgpt-mermaid-\_r_3rd\_ .image-shape{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_3rd\_ .icon-shape p,#chatgpt-mermaid-\_r_3rd\_ .image-shape p{background-color:rgb(0, 0, 0);padding:2px;}#chatgpt-mermaid-\_r_3rd\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_3rd\_ .image-shape .label rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_3rd\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_3rd\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_3rd\_ .node .neo-node{stroke:rgb(31, 78, 148);}#chatgpt-mermaid-\_r_3rd\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_3rd\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_3rd\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_3rd\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3rd\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_3rd\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_3rd\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_3rd\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3rd\_ [data-look="neo"].node .neo-line path{stroke:rgb(31, 78, 148);filter:none;}#chatgpt-mermaid-\_r_3rd\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_3rd\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3rd\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_3rd\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_3rd\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3rd\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_3rd\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3rd\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(153, 206, 255);}#chatgpt-mermaid-\_r_3rd\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(153, 206, 255);}#chatgpt-mermaid-\_r_3rd\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_3rd\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_3rd\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-width:1px;}#chatgpt-mermaid-\_r_3rd\_ .node rect,#chatgpt-mermaid-\_r_3rd\_ .node circle,#chatgpt-mermaid-\_r_3rd\_ .node ellipse,#chatgpt-mermaid-\_r_3rd\_ .node polygon,#chatgpt-mermaid-\_r_3rd\_ .node path{fill:rgb(0, 40, 77);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_3rd\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_3rd\_ .mermaid-decision .label-container{fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_3rd\_ .edgePaths .flowchart-link{stroke:rgb(175, 175, 175);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_3rd\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3rd\_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}New threadUser rulesRule provides a valid result?Apply deterministicclassificationSender and header heuristicsHigh-confidence match?Small Triage AgentValidated classification androutingSave thread intelligenceYesNoYesNo

For example, a user might define:

```
From: newsletter@example.com

Category: Promotional
Skip: Expensive intelligence
```

Maail can handle this without an LLM call.

We can also use deterministic signals from sender history, known notification domains and unsubscribe metadata. However, unknown or ambiguous senders must not be incorrectly classified as safe.

### Triage harness

- Category schema.
- Priority schema.
- Route allowlist.
- Confidence and abstention policy.
- Fixed regression fixtures.
- Prompt version tracking.
- Routing precision measurements.
- Model-call counter.
- Deterministic bypass tests.

I would retain the v3 Triage Agent as the fallback for ambiguous threads and measure whether the fast path is safe before enabling it broadly.

Acceptance gate: Classification quality must remain within agreed tolerances while unnecessary model calls decrease.

## Phase 7 — Smart Inbox

Problem: Too many frontend API calls and unnecessary AI interactions when navigating email.

Harness:

- Cursor-based pagination.
- Database indexes.
- Debounced search.
- Cached thread-list queries.
- Lazy-load message details.
- Cached intelligence status.
- Avoid re-fetching unchanged thread records.

LLM usage: Zero for opening, filtering, sorting and navigating the inbox.

The inbox is a presentation layer over existing database intelligence. It should never call an LLM merely because the user changes tabs.

## Phase 8 — Thread detail and safe rendering

Problem: Repeated summarization, unnecessary body fetching and unsafe HTML rendering.

Harness:

- Load message metadata first.
- Fetch sanitized body only when requested.
- Cache rendered representations carefully.
- Block remote images by default.
- Validate evidence offsets.
- Use a content version to identify changed threads.
- Cache summaries against content version and pipeline version.

LLM usage: No model calls for basic reading or rendering. Only request a summary when none exists for the current version or the user explicitly requests a different summary.

## Phase 9 — Summarizer, Deadline and ActionItem agents

These agents need different harnesses.

| Agent      | Harness                                                                    |
| ---------- | -------------------------------------------------------------------------- |
| Summarizer | Thread-level caching, quote stripping, short/detailed output contracts     |
| Deadline   | Deterministic candidate extraction, timezone normalization, evidence spans |
| ActionItem | Separate stated versus inferred actions, structured validation             |

For all three:

- Run only when routed and enabled.
- Skip if valid current-version results exist.
- Avoid sending the same quoted messages repeatedly.
- Limit the agent's context to relevant messages.
- Validate evidence before storage.

Acceptance gate: No repeated execution for identical thread content, configuration and agent versions.

## Phase 10 — AI Companion

High token-saving opportunity

The Companion should not automatically send every user message to a powerful model with the entire email history.

Introduce an intent and context-selection harness.

| User question                      | Preferred processing                 |
| ---------------------------------- | ------------------------------------ |
| "Open this email"                  | Normal application operation         |
| "Show sender details"              | Database query                       |
| "Find emails from GitHub"          | PostgreSQL FTS                       |
| "What is this email about?"        | Cached summary, otherwise summarizer |
| "What did my teammate mean?"       | Retrieval + LLM                      |
| "Investigate this technical issue" | Developer workflow if enabled        |
| "Draft a reply"                    | Response workflow                    |

### Companion context harness

```
User query
    |
    v
Intent / task router
    |
    +---- Simple lookup ----> SQL / FTS
    |
    +---- Existing result ---> Return cached intelligence
    |
    +---- Complex question --> Retrieve selected threads
                                  |
                                  v
                              Context builder
                                  |
                                  v
                              LLM response
                                  |
                                  v
                           Citation validation
```

We should also use:

- Conversation summarization when history becomes long.
- A maximum context size.
- Source IDs rather than complete email histories.
- Reusable thread summaries.
- Citation verification.
- Budget checks before inference.

Acceptance gate: Simple lookups should complete without a model call; complex answers must cite valid source evidence.

## Phase 11 — Feature controls

Your toggle system should itself be a harness.

The backend should compile enabled features and their configurations into an execution plan.

Example:

```
User configuration
       |
       v
Feature registry
       |
       v
Dependency resolver
       |
       v
Permission validator
       |
       v
Execution planner
       |
       v
Allowed capabilities only
```

Harness mechanisms:

- Backend-owned feature configuration.
- Feature dependency graph.
- User-rule overrides.
- Agent-to-feature mapping.
- Cached configuration with controlled invalidation.
- Tests that prove disabled features never execute.
- Explicit distinction between disabling and deleting previous results.

Do not call an LLM to decide whether an enabled toggle is enabled.

## Phase 12 — Approval and Plane X execution

Problem: Repeated approval requests, duplicate external actions and unnecessary model involvement in execution.

Harness:

- Action schema validation.
- Content hash.
- Context version.
- Approval expiry.
- Single-use approval tokens.
- Idempotency keys.
- Independent permission validation.
- Audit logging.
- Deterministic executor.

LLM usage: Zero during approval validation and actual action execution.

The existing LLD already establishes the central invariant that models propose actions while Plane X executes them using ordinary code.&#x20;

03-lld-agent-runtime.md



# 4. Harness application across every Maail module

The previous section covers development stages. Now let's define what each actual backend and frontend module must contain.

This should become a mandatory section in every module's technical specification.

| Maail module         | Harness to implement                                              | LLM savings                                     |
| -------------------- | ----------------------------------------------------------------- | ----------------------------------------------- |
| `auth`               | OAuth state validation, scope checks, session middleware          | Zero auth-related inference                     |
| `users`              | Cached profile retrieval, preference validation                   | Avoid repeated preference reasoning             |
| `email/providers`    | Provider adapter contracts, retry and quota controls              | Zero integration reasoning                      |
| `sync`               | Two-pass sync, incremental updates, deduplication                 | Zero sync-related inference                     |
| `ingest`             | Parsing, quote stripping, signature removal, normalization        | Reduce tokens before inference                  |
| `threads`            | Thread merge rules, content versioning, cached intelligence       | Prevent repeated processing                     |
| `features`           | Registry, dependency resolver, backend gates                      | Avoid unnecessary agent execution               |
| `rules`              | Deterministic user-defined rules                                  | Bypass eligible model calls                     |
| `retrieval`          | FTS, filters, ranking, compact snippets                           | Reduce context tokens                           |
| `mcp/client`         | Tool filtering, schema cache, reusable connections                | Reduce tool-schema overhead                     |
| `mcp/servers`        | Typed tool contracts, pagination, output limits                   | Reduce tool-result tokens                       |
| `agents/runtime`     | Model routing, context budgets, step limits, tracing              | Prevent excess inference                        |
| `agents/triage`      | Rule-first fast path, cheap model fallback                        | Reduce classification calls                     |
| `agents/summarizer`  | Versioned summary cache, quote removal                            | Prevent repeated summaries                      |
| `agents/deadline`    | Deterministic date candidates, evidence validation                | Avoid model date calculations                   |
| `agents/action_item` | Structured extraction and deduplication                           | Avoid redundant extraction                      |
| `agents/opportunity` | Triage-based routing and structured extraction                    | Avoid processing irrelevant threads             |
| `agents/developer`   | Technical routing, repository allowlist, bounded GitHub retrieval | Reduce unnecessary investigations               |
| `agents/response`    | Reuse thread context and derived style profile                    | Avoid retrieving entire email history           |
| `agents/briefing`    | Compile from stored intelligence rather than raw email            | Avoid reprocessing inbox                        |
| `agents/companion`   | Intent routing, scoped retrieval, summary reuse                   | Avoid full-history context                      |
| `approvals`          | Deterministic action validation and stale-state detection         | Zero approval-related inference                 |
| `executor`           | Idempotency, allowlists, approval verification                    | Zero execution-related inference                |
| `jobs/workers`       | Leases, job deduplication, bounded retries                        | Prevent repeated agent runs                     |
| `database`           | Indexes, constraints, RLS, query plans                            | Avoid asking models to solve database filtering |
| `frontend`           | Server-state caching, lazy loading, debounced requests            | Avoid accidental repeated requests              |
| `observability`      | Per-step cost, token and latency accounting                       | Identify unnecessary LLM calls                  |
| `evals`              | Golden fixtures and behavioral regression tests                   | Avoid manual prompt trial and error             |

### Important additional harness for MCP

I want one separate rule documented in `modules/agents/mcp/`.

MCP discovery should not be equivalent to sending every server's entire tool catalog into every LLM request.

We should maintain:

```
MCP Server Registry
       |
       v
Cached Server Capabilities
       |
       v
Agent Capability Manifest
       |
       v
Task-specific Tool Selection
       |
       v
Validated MCP Invocation
```

Tool discovery can occur at startup or when a server's tool-list version changes. Tool definitions should be cached and filtered before they reach an agent.

MCP's job is interoperability; Maail's harness decides which tools are appropriate for each task.

# 5. Harness engineering for each of our ten agents

This is especially important because we have chosen the agent-first architecture in v3.0.

The HLD defines ten agents with different triggers, tool subsets, model tiers and outputs. Each should have its own harness profile.&#x20;

01-hld.md



| Agent       | Specific harness                                                   | Avoided waste                               |
| ----------- | ------------------------------------------------------------------ | ------------------------------------------- |
| Triage      | Sender rules, significance gate, compact input, routing evaluation | Calling expensive specialists unnecessarily |
| Summarizer  | Thread-version cache, incremental summarization                    | Summarizing unchanged conversations         |
| Deadline    | Date candidate parser, timezone engine, evidence spans             | Asking LLM to calculate dates               |
| ActionItem  | Stated/inferred classifier, duplicate action detection             | Re-extracting existing actions              |
| Opportunity | Category gating, opportunity schema, eligibility rules             | Analyzing ordinary emails                   |
| Developer   | Technical routing, repository allowlist, scoped GitHub tools       | Investigating irrelevant technical messages |
| Response    | Style profile cache, reply context builder                         | Sending unnecessary history to the model    |
| Organizer   | User rules, deterministic label mapping                            | Repeated categorization decisions           |
| Briefing    | SQL aggregation over stored intelligence                           | Reading raw emails again                    |
| Companion   | Intent router, FTS, context selection, summary reuse               | Sending entire inbox history                |

## The most important optimization: Triage

Triage controls how much downstream processing happens.

So it should be evaluated not merely on whether it classifies correctly, but also on whether it routes intelligently.

For instance:

```
1,000 new threads
       |
       v
Deterministic filtering
       |
       v
Triage Agent for ambiguous threads
       |
       v
Only relevant specialist agents
       |
       v
On-demand deep analysis
```

We should track:

- Number of deterministic bypasses.
- Number of Triage calls.
- Specialist routing precision.
- False-negative routing.
- Number of specialist executions avoided.
- Cost per processed thread.

One caution: we should not optimize toward fewer model calls at the expense of missing important emails. The success metric must combine quality and cost.

# 6. A dedicated LLM usage optimization harness

I want this to be a centralized capability in Maail, not a collection of independent caching tricks.

Introduce a conceptual component:

Intelligence Efficiency Controller

It should decide whether a model call is needed, which model tier is appropriate, what context to include and whether a previous result can be reused.

### Architecture

\#chatgpt-mermaid-\_r_3sd\_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(237, 237, 237);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_3sd\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_3sd\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_3sd\_ .error-icon{fill:rgb(48, 48, 48);}#chatgpt-mermaid-\_r_3sd\_ .error-text{fill:rgb(237, 237, 237);stroke:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3sd\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_3sd\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_3sd\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_3sd\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_3sd\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_3sd\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_3sd\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3sd\_ .marker.cross{stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3sd\_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-\_r_3sd\_ p{margin:0;}#chatgpt-mermaid-\_r_3sd\_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3sd\_ .cluster-label text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3sd\_ .cluster-label span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3sd\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_3sd\_ .label text,#chatgpt-mermaid-\_r_3sd\_ span{fill:rgb(237, 237, 237);color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3sd\_ .node rect,#chatgpt-mermaid-\_r_3sd\_ .node circle,#chatgpt-mermaid-\_r_3sd\_ .node ellipse,#chatgpt-mermaid-\_r_3sd\_ .node polygon,#chatgpt-mermaid-\_r_3sd\_ .node path{fill:rgb(9, 23, 44);stroke:rgb(31, 78, 148);stroke-width:1px;}#chatgpt-mermaid-\_r_3sd\_ .rough-node .label text,#chatgpt-mermaid-\_r_3sd\_ .node .label text,#chatgpt-mermaid-\_r_3sd\_ .image-shape .label,#chatgpt-mermaid-\_r_3sd\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_3sd\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_3sd\_ .rough-node .label,#chatgpt-mermaid-\_r_3sd\_ .node .label,#chatgpt-mermaid-\_r_3sd\_ .image-shape .label,#chatgpt-mermaid-\_r_3sd\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_3sd\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_3sd\_ .root .anchor path{fill:rgb(175, 175, 175)!important;stroke-width:0;stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3sd\_ .arrowheadPath{fill:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3sd\_ .edgePath .path{stroke:rgb(175, 175, 175);stroke-width:1px;}#chatgpt-mermaid-\_r_3sd\_ .flowchart-link{stroke:rgb(175, 175, 175);fill:none;}#chatgpt-mermaid-\_r_3sd\_ .edgeLabel{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_3sd\_ .edgeLabel p{background-color:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_3sd\_ .edgeLabel rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_3sd\_ .labelBkg{background-color:rgba(0, 0, 0, 0.5);}#chatgpt-mermaid-\_r_3sd\_ .cluster rect{fill:rgb(48, 48, 48);stroke:rgba(255, 255, 255, 0.15);stroke-width:1px;}#chatgpt-mermaid-\_r_3sd\_ .cluster text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3sd\_ .cluster span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3sd\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(48, 48, 48);border:1px solid rgba(255, 255, 255, 0.15);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_3sd\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3sd\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_3sd\_ .icon-shape,#chatgpt-mermaid-\_r_3sd\_ .image-shape{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_3sd\_ .icon-shape p,#chatgpt-mermaid-\_r_3sd\_ .image-shape p{background-color:rgb(0, 0, 0);padding:2px;}#chatgpt-mermaid-\_r_3sd\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_3sd\_ .image-shape .label rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_3sd\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_3sd\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_3sd\_ .node .neo-node{stroke:rgb(31, 78, 148);}#chatgpt-mermaid-\_r_3sd\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_3sd\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_3sd\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_3sd\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3sd\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_3sd\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_3sd\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_3sd\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3sd\_ [data-look="neo"].node .neo-line path{stroke:rgb(31, 78, 148);filter:none;}#chatgpt-mermaid-\_r_3sd\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_3sd\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3sd\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_3sd\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_3sd\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3sd\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_3sd\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3sd\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(153, 206, 255);}#chatgpt-mermaid-\_r_3sd\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(153, 206, 255);}#chatgpt-mermaid-\_r_3sd\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_3sd\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_3sd\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-width:1px;}#chatgpt-mermaid-\_r_3sd\_ .node rect,#chatgpt-mermaid-\_r_3sd\_ .node circle,#chatgpt-mermaid-\_r_3sd\_ .node ellipse,#chatgpt-mermaid-\_r_3sd\_ .node polygon,#chatgpt-mermaid-\_r_3sd\_ .node path{fill:rgb(0, 40, 77);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_3sd\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_3sd\_ .mermaid-decision .label-container{fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_3sd\_ .edgePaths .flowchart-link{stroke:rgb(175, 175, 175);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_3sd\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3sd\_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}Feature / Agent RequestEfficiency ControllerCheck user feature settingsCheck permission and budgetCheck deterministic fast pathCan code solve it?Return deterministic resultCheck cacheValid result exists?Reuse stored resultSelect model tierBuild minimal contextCall LLMValidate structured outputStore result and traceReturn resultYesNoYesNo

### Proposed execution cache

Every reusable intelligence result should have a cache key derived from:

```
user_id
thread_id
content_version
feature_id
agent_version
prompt_version
model_version
configuration_hash
```

This ensures that:

- Unchanged threads reuse their intelligence.
- A new message invalidates only relevant outputs.
- A prompt change doesn't accidentally reuse incompatible results.
- Different user preferences don't share incompatible outputs.

We should distinguish:

1. Result cache: Reuses already completed analysis.
2. Job deduplication: Prevents duplicate work from running concurrently.
3. API response cache: Avoids repeated database and API requests.
4. LLM provider prompt caching: Reuses provider-supported stable prompt prefixes.

These are different mechanisms and should not be confused.

### Prompt/context harness

Organize model inputs into three sections:

| Section     | Content                                         | Handling                   |
| ----------- | ----------------------------------------------- | -------------------------- |
| Stable      | System policy, output schema, tool descriptions | Keep first and versioned   |
| Semi-stable | Agent configuration and feature instructions    | Cache by version           |
| Dynamic     | Selected email/thread content                   | Include only when required |

Also:

- Strip quoted content.
- Remove unnecessary HTML and signatures.
- Use snippets before retrieving full thread content.
- Apply context size limits.
- Avoid repeating tool results.
- Summarize long context only when required.

This follows the context reuse and prompt-layout decisions already present in our v3.0 design.&#x20;

03-lld-agent-runtime.md



### Model escalation harness

We should not default to the strongest model.

```
Deterministic operation
        |
        v
Small model
        |
        v
Quality / uncertainty check
        |
        v
Mid-tier model when justified
        |
        v
Strong model only for complex tasks
```

However, do not blindly escalate every model response with a low confidence score. Confidence itself may be unreliable. Escalation must be based on measurable quality conditions and task importance.

# 7. Development Harness — how we build Maail using coding agents

Now comes the other half.

I want Maail's repository to be designed so that Codex or another coding agent can understand and work on it without requiring us to repeatedly explain the entire project.

This is closely aligned with OpenAI's published harness engineering approach: repository knowledge becomes the system of record, agents receive a map rather than an enormous instruction file, and architecture and verification are enforced mechanically.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://openai.com\&sz=32)

OpenAI+1



## A. Repository knowledge harness

Proposed structure:

```
maail/
│
├── AGENTS.md
├── ARCHITECTURE.md
│
├── docs/
│   ├── product/
│   │   ├── requirements.md
│   │   └── feature-specifications/
│   │
│   ├── architecture/
│   │   ├── 00-gap-analysis.md
│   │   ├── 01-hld.md
│   │   ├── 02-lld-data-model.md
│   │   ├── 03-lld-agent-runtime.md
│   │   ├── 04-lld-api-sync-modules.md
│   │   └── 05-harness-engineering.md
│   │
│   ├── decisions/
│   │   ├── ADR-001-modular-monolith.md
│   │   ├── ADR-002-mcp-architecture.md
│   │   ├── ADR-003-thread-first-data-model.md
│   │   └── ADR-004-agent-runtime.md
│   │
│   ├── modules/
│   │   ├── email-sync.md
│   │   ├── ingestion.md
│   │   ├── intelligence.md
│   │   ├── mcp.md
│   │   ├── agents.md
│   │   └── companion.md
│   │
│   ├── execution-plans/
│   │   ├── active/
│   │   └── completed/
│   │
│   ├── quality/
│   │   ├── quality-scorecard.md
│   │   └── tech-debt.md
│   │
│   └── runbooks/
│       ├── local-development.md
│       ├── debugging.md
│       └── deployment.md
│
├── scripts/
├── backend/
├── frontend/
├── evals/
└── tests/
```

### B. AGENTS.md — project-wide coding instructions

Keep this short, approximately 100 lines or less.

Its job is to tell coding agents:

- What Maail is.
- How the repository is organized.
- Which architecture documents are authoritative.
- Which commands run the tests.
- Where the security boundaries are.
- Which modules must never directly depend on other modules.
- How to create and complete an implementation plan.

Do not put the entire HLD and LLD into `AGENTS.md`. That creates context bloat.

Instead, agents should follow links to the relevant documents when needed.

### C. Module context harness

This is something I'd particularly like us to build.

Suppose a coding agent gets this task:

"Implement the Gmail incremental synchronization retry mechanism."

It should not need to read the entire repository.

A context loader should provide:

```
TASK: Gmail incremental sync retry

Relevant modules:
- providers/email/gmail.py
- modules/sync/engine.py
- modules/sync/reconcile.py
- jobs/queue.py

Required documentation:
- HLD: Gmail synchronization
- LLD: Sync state machine
- ADR: Retry and idempotency

Required contracts:
- GmailProvider
- SyncCursor
- BackgroundJob

Required tests:
- tests/sync/test_delta_sync.py
- tests/sync/test_reconciliation.py
```

This is progressive context disclosure.

The agent receives enough context to work correctly, without spending tokens rediscovering the project.

### D. Architecture enforcement harness

We should make architecture rules executable.

Example:

| Rule                                               | Automated check          |
| -------------------------------------------------- | ------------------------ |
| Plane X cannot import LLM clients                  | Dependency/import test   |
| Agents cannot call Gmail directly                  | Architecture lint        |
| All agent tools go through MCP/runtime             | Import boundary test     |
| Every user-scoped table has RLS                    | Schema audit             |
| Every API mutation has authorization               | API security tests       |
| Agents have bounded budgets                        | Registry validator       |
| Output schemas are mandatory                       | Agent registration check |
| MCP tools have permission metadata                 | Tool registry validator  |
| All migrations have downgrade or recovery strategy | Migration review check   |

The idea is simple:

Don't merely tell coding agents to follow architecture. Make CI reject architectural violations.

## B. Coding-agent task execution harness

Every substantial development task should follow a standard workflow:

\#chatgpt-mermaid-\_r_3u0\_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(237, 237, 237);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_3u0\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_3u0\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_3u0\_ .error-icon{fill:rgb(48, 48, 48);}#chatgpt-mermaid-\_r_3u0\_ .error-text{fill:rgb(237, 237, 237);stroke:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3u0\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_3u0\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_3u0\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_3u0\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_3u0\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_3u0\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_3u0\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3u0\_ .marker.cross{stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3u0\_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-\_r_3u0\_ p{margin:0;}#chatgpt-mermaid-\_r_3u0\_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3u0\_ .cluster-label text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3u0\_ .cluster-label span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3u0\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_3u0\_ .label text,#chatgpt-mermaid-\_r_3u0\_ span{fill:rgb(237, 237, 237);color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3u0\_ .node rect,#chatgpt-mermaid-\_r_3u0\_ .node circle,#chatgpt-mermaid-\_r_3u0\_ .node ellipse,#chatgpt-mermaid-\_r_3u0\_ .node polygon,#chatgpt-mermaid-\_r_3u0\_ .node path{fill:rgb(9, 23, 44);stroke:rgb(31, 78, 148);stroke-width:1px;}#chatgpt-mermaid-\_r_3u0\_ .rough-node .label text,#chatgpt-mermaid-\_r_3u0\_ .node .label text,#chatgpt-mermaid-\_r_3u0\_ .image-shape .label,#chatgpt-mermaid-\_r_3u0\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_3u0\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_3u0\_ .rough-node .label,#chatgpt-mermaid-\_r_3u0\_ .node .label,#chatgpt-mermaid-\_r_3u0\_ .image-shape .label,#chatgpt-mermaid-\_r_3u0\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_3u0\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_3u0\_ .root .anchor path{fill:rgb(175, 175, 175)!important;stroke-width:0;stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3u0\_ .arrowheadPath{fill:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3u0\_ .edgePath .path{stroke:rgb(175, 175, 175);stroke-width:1px;}#chatgpt-mermaid-\_r_3u0\_ .flowchart-link{stroke:rgb(175, 175, 175);fill:none;}#chatgpt-mermaid-\_r_3u0\_ .edgeLabel{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_3u0\_ .edgeLabel p{background-color:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_3u0\_ .edgeLabel rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_3u0\_ .labelBkg{background-color:rgba(0, 0, 0, 0.5);}#chatgpt-mermaid-\_r_3u0\_ .cluster rect{fill:rgb(48, 48, 48);stroke:rgba(255, 255, 255, 0.15);stroke-width:1px;}#chatgpt-mermaid-\_r_3u0\_ .cluster text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3u0\_ .cluster span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3u0\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(48, 48, 48);border:1px solid rgba(255, 255, 255, 0.15);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_3u0\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3u0\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_3u0\_ .icon-shape,#chatgpt-mermaid-\_r_3u0\_ .image-shape{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_3u0\_ .icon-shape p,#chatgpt-mermaid-\_r_3u0\_ .image-shape p{background-color:rgb(0, 0, 0);padding:2px;}#chatgpt-mermaid-\_r_3u0\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_3u0\_ .image-shape .label rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_3u0\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_3u0\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_3u0\_ .node .neo-node{stroke:rgb(31, 78, 148);}#chatgpt-mermaid-\_r_3u0\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_3u0\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_3u0\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_3u0\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3u0\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_3u0\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_3u0\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_3u0\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3u0\_ [data-look="neo"].node .neo-line path{stroke:rgb(31, 78, 148);filter:none;}#chatgpt-mermaid-\_r_3u0\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_3u0\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3u0\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_3u0\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_3u0\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3u0\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_3u0\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3u0\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(153, 206, 255);}#chatgpt-mermaid-\_r_3u0\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(153, 206, 255);}#chatgpt-mermaid-\_r_3u0\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_3u0\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_3u0\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-width:1px;}#chatgpt-mermaid-\_r_3u0\_ .node rect,#chatgpt-mermaid-\_r_3u0\_ .node circle,#chatgpt-mermaid-\_r_3u0\_ .node ellipse,#chatgpt-mermaid-\_r_3u0\_ .node polygon,#chatgpt-mermaid-\_r_3u0\_ .node path{fill:rgb(0, 40, 77);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_3u0\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_3u0\_ .mermaid-decision .label-container{fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_3u0\_ .edgePaths .flowchart-link{stroke:rgb(175, 175, 175);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_3u0\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3u0\_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}Engineering taskRead module contextInspect relevantimplementationCreate execution planImplement smallest changeRun unit testsRun integration testsRun architecture checksReview own diffAll checks pass?Analyze failure and fixPrepare implementation reportNoYes

### Standard task contract

Every task should have:

```
Task ID:
Goal:
Affected modules:
Relevant ADRs:
Allowed dependencies:
Expected behavior:
Acceptance criteria:
Tests required:
Security implications:
Out of scope:
```

This prevents coding agents from interpreting an ambiguous task as permission to redesign an entire subsystem.

### Reusable engineering commands

Create commands that agents can invoke without figuring out the correct sequence every time.

| Command                   | Purpose                                 |
| ------------------------- | --------------------------------------- |
| `maail check`             | Formatting, typing and static analysis  |
| `maail test fast`         | Fast unit and contract tests            |
| `maail test integration`  | Database and provider integration tests |
| `maail test architecture` | Dependency and security invariants      |
| `maail eval`              | AI behavioral regression suite          |
| `maail db verify`         | Migration and schema validation         |
| `maail dev doctor`        | Environment and service diagnostics     |

These are proposed CLI interfaces; we should keep the underlying scripts simple.

### C. Reproducible coding environment

For complex work:

- Give each coding task an isolated Git worktree.
- Start a separate test application instance.
- Use seeded PostgreSQL fixtures.
- Stub Gmail, GitHub and LLM APIs.
- Use a deterministic clock for deadline tests.
- Keep test secrets separate from real credentials.
- Capture logs and traces for the task.

OpenAI's engineering approach specifically discusses worktree-isolated application instances and exposing UI and observability data directly to coding agents for debugging.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://openai.com\&sz=32)

OpenAI



This can save substantial human debugging effort.

## D. UI harness

Since Maail is a web application, the coding agent should be able to verify actual interface behavior.

Use:

- Playwright for browser automation.
- DOM snapshots for locating controls.
- Screenshots for visual comparison.
- Seeded inbox data.
- Accessibility checks.
- Responsive layout tests.
- Browser console and network error capture.

A UI task is not complete merely because the React component compiles.

It is complete when the actual interaction works.

# 8. Behavioral evaluation harness

We already have a regression dataset and golden traces in the Maail v3 plan. I want to extend that into a complete behavioral harness.&#x20;

03-lld-agent-runtime.md



An AI agent's correctness cannot be judged only by its final response.

We must evaluate how it behaves.

For example, consider the Companion.

Expected behavior:

```
User: Find the email about my API integration.

Expected:
1. Understand the lookup request.
2. Use search_threads.
3. Retrieve only relevant results.
4. Return source references.
5. Do not run the Developer Agent unnecessarily.
6. Do not generate a summary if a simple search answer suffices.
```

The test should examine the tool calls, permissions, retrieval and outcome—not require identical wording.

Google's September 2026 guidance on behavioral evaluations similarly recommends testing observable intermediate actions, with small deterministic checks complemented by broader end-to-end evaluations.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://developers.googleblog.com\&sz=32)

Google Developers Blog



### Three evaluation levels

Level 1 — Deterministic tests

Run locally on every change

Check schemas, rules, access boundaries, retries, tool restrictions and cache behavior.

Level 2 — Behavioral agent tests

Run for relevant agent changes

Check tool selection, context retrieval, abstention, citation behavior, budget compliance and routing decisions.

Level 3 — End-to-end evaluations

Run before significant releases

Check complete user journeys, intelligence quality, latency, cost and security.

A useful improvement is to separate hard deterministic assertions from probabilistic quality scores. A harmless change in a valid tool sequence shouldn't necessarily fail CI, while an unauthorized action must always fail.

# 9. Harness for observability and efficiency measurement

There is a trap I want us to avoid.

We might implement caching, routing, context trimming and model selection, but without measurement we won't know whether any of them actually helped.

So Maail needs an Efficiency Dashboard internally.

This isn't necessarily a user-facing product screen. It's an engineering and operational dashboard.

## Metrics we should monitor

## Maail — Engineering Efficiency Monitor

# 0

Unnecessary LLM calls

Target for deterministic operations

# —

Cache hit ratio

Measured, not assumed

# —

Input tokens / thread

By agent and capability

# —

Average model calls / thread

By execution path

# —

Deterministic bypass rate

Share of eligible requests solved without an LLM

# —

Agent success rate

Quality-qualified completion rate

Additional measurements

- Token savings from quote stripping.
- Prompt-cache hit rate, where provider support exists.
- Context size before and after retrieval.
- Tool calls per successful task.
- Average and p95 execution latency.
- Failed or retried jobs.
- Cost per capability.
- Cost per user and per thread.

  Conceptual monitoring design, not live Maail telemetry.

### A critical metric: Cost per successful task

Don't only measure cost per model call.

For example:

| Execution                         | Model calls | Outcome     |
| --------------------------------- | ----------- | ----------- |
| Search existing email             | 0           | Successful  |
| Retrieve cached summary           | 0           | Successful  |
| Generate new summary              | 1           | Successful  |
| Investigate a complex issue       | 4           | Successful  |
| Investigate same issue repeatedly | 12          | Inefficient |

We want to reduce the cost of successfully completing a user task, not simply minimize the number of calls.

### Proposed telemetry record

```
{
  "run_id": "run_123",
  "thread_id": "thread_456",
  "agent": "summarizer",
  "execution_path": "cache_miss",
  "model": "selected_model",
  "input_tokens": 1200,
  "output_tokens": 250,
  "tool_calls": 1,
  "latency_ms": 1800,
  "result_status": "success",
  "cache_hit": false
}
```

We should distinguish model token counts from tool payload size, database processing and provider-billed costs.

# 10. The harness configuration every agent should have

I also want every agent definition to declare its resource and context requirements.

Your current LLD already defines agent versions, planes, model tiers, tool subsets, output schemas and execution budgets.&#x20;

03-lld-agent-runtime.md



Let's extend that specification conceptually:

```
agent:
  id: summarizer
  version: "1.0.0"

  execution:
    model_tier: mid
    max_steps: 3
    max_tokens: 4000
    max_wall_clock_s: 20

  context:
    source: current_thread
    max_messages: 10
    use_stripped_content: true
    include_quoted_history: false

  caching:
    enabled: true
    key: content_version_and_agent_version

  tools:
    allowed:
      - get_thread

    max_tool_calls: 2
    max_result_bytes: 16000

  validation:
    output_schema: ThreadSummary
    require_evidence: true

  fallback:
    use_cached_result: true
    fail_without_guessing: true
```

This is a design example, not a final configuration. Exact limits must be established through evaluation.

I particularly like this pattern because each agent becomes a self-describing, versioned execution unit.

The runtime can enforce these constraints without relying on the model to remember them.

# 11. Complete harness coverage checklist

This is the master checklist I want attached to Maail's HLD and LLD.

Harness coverage

0/14 verified

1\. Repository and development environment

Modules: AGENTS.md, documentation, scripts, CI, worktreesHarness: Context maps, architecture lint, reproducible environments, task plans

2\. Authentication

Modules: auth, users, OAuth, securityHarness: Scope validation, token lifecycle, security contracts

3\. Email synchronization

Modules: Gmail adapter, sync, quota, reconciliationHarness: Two-pass fetch, idempotency, retries, failure injection

4\. Ingestion

Modules: parser, normalizer, quote stripper, date parserHarness: Deterministic preprocessing, token reduction benchmark

5\. Storage

Modules: threads, messages, intelligence, databaseHarness: Content versioning, RLS, constraints, cache invalidation

6\. Job execution

Modules: jobs, workersHarness: Dedupe, leases, bounded retries, crash recovery

7\. MCP

Modules: MCP clients, servers, tool registryHarness: Schema caching, capability filtering, output bounds, authorization

8\. Intelligence

Modules: feature registry, rules, triageHarness: Fast paths, model routing, confidence and evaluation gates

9\. Specialist agents

Modules: summary, deadline, action, opportunity, developer, response, briefingHarness: Agent manifests, caching, bounded execution, structured validation

10\. Retrieval

Modules: FTS, query parser, context builderHarness: Filtered retrieval, snippets, ranking and context budgets

11\. AI Companion

Modules: chat, orchestration, citationsHarness: Intent routing, thread-scoped context, summary reuse and groundedness

12\. Actions

Modules: approvals, executor, integrationsHarness: Hash-bound approval, idempotency, deterministic execution

13\. Frontend

Modules: inbox, thread, settings, dashboardHarness: Lazy loading, API cache, Playwright, accessibility and visual tests

14\. Testing and deployment

Modules: evals, monitoring, release infrastructureHarness: Golden traces, behavioral tests, CI gates and production telemetry

Planning checklist. Checking an item here is a personal review action, not evidence that its engineering implementation exists.

# 12. Where these additions belong in our architecture documents

I don't want us to create another disconnected document that no one refers to.

We should integrate this into the existing v3.0 design set.

| Document                        | What to add                                                                                   |
| ------------------------------- | --------------------------------------------------------------------------------------------- |
| `00-gap-analysis.md`            | Harness-related gaps, cost controls and unresolved decisions                                  |
| `01-hld.md`                     | Cross-cutting Harness Engineering layer and updated architecture diagram                      |
| `02-lld-data-model.md`          | Cache versions, usage accounting, execution metadata and invalidation                         |
| `03-lld-agent-runtime.md`       | Efficiency controller, per-agent budgets, context harness, MCP discovery and behavioral evals |
| `04-lld-api-sync-modules.md`    | Module-level harness responsibilities, scripts, test contracts, queue policies                |
| `README.md`                     | Harness engineering as a foundational architectural principle                                 |
| New `05-harness-engineering.md` | Detailed implementation guide for development and runtime harnesses                           |

I would also add these architectural invariants:

1. No LLM invocation without a registered capability, budget and execution reason.
2. No model processing when a deterministic operation or valid cached result is sufficient.
3. No agent receives the complete MCP tool catalog by default.
4. No agent processes unchanged content without a valid reprocessing reason.
5. No AI output enters persistent intelligence storage without validation.
6. No external side effect occurs through an LLM or MCP-exposed action tool.
7. Every agent run is measurable, traceable and bounded.
8. Every code change passes the relevant automated architectural and behavioral checks.

# 13. How to introduce all this without creating another complicated system

Harness engineering itself can become over-engineered. We should implement it incrementally.

I recommend five levels of harness maturity.

1. H0 — Basic engineering environment

   Repository instructions, documentation, consistent commands, Docker, test fixtures and module boundaries.
2. H1 — Deterministic application

   Parsing, normalization, caching, feature rules, database constraints and predictable job execution.
3. H2 — Controlled AI runtime

   Model routing, context limits, MCP filtering, tool budgets, schemas and execution traces.
4. H3 — Self-verifying application

   Behavioral evaluations, golden traces, regression detection, security tests and automated quality gates.
5. H4 — Continuous optimization

   Cost regression detection, automated documentation checks, stale-code detection, performance monitoring and controlled prompt/model experiments.

### CI pipeline we should eventually have

```
                 Pull Request
                      |
                      v
              Formatting & Types
                      |
                      v
             Architecture Validation
                      |
                      v
             Unit & Contract Tests
                      |
                      v
              Security / RLS Tests
                      |
                      v
            Integration Tests (Mocks)
                      |
                      v
             Relevant Behavioral Evals
                      |
                      v
               Build Verification
                      |
                      v
                 Merge Gate
```

For expensive real-model evaluations, run targeted batch tests for affected agents and broader scheduled or release evaluations. Don't run a large nondeterministic LLM evaluation suite on every trivial frontend change. Google’s behavioral evaluation guidance also recommends combining fast deterministic assertions with aggregate evaluation runs.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://developers.googleblog.com\&sz=32)

Google Developers Blog



## 14. The biggest opportunities for reducing LLM usage

If I had to prioritize the entire harness investment, I would rank it like this:

| Priority | Optimization                       | Why it matters                                            |
| -------- | ---------------------------------- | --------------------------------------------------------- |
| 1        | Deterministic preprocessing        | Prevent unnecessary content from reaching models          |
| 2        | Feature/rule-based bypass          | Avoid processing emails that need no AI                   |
| 3        | Significance gate                  | Avoid repeated processing of unchanged conversations      |
| 4        | Thread-level intelligence cache    | Reuse completed analysis                                  |
| 5        | MCP tool filtering                 | Avoid irrelevant tool schemas                             |
| 6        | Retrieval and context minimization | Reduce tokens per model call                              |
| 7        | Tiered model routing               | Reserve expensive models for complex work                 |
| 8        | Summary and conversation reuse     | Prevent redundant summarization                           |
| 9        | Strict agent budgets               | Prevent runaway execution                                 |
| 10       | Behavioral evaluation              | Prevent inefficient or low-quality changes from returning |

The first four are particularly important because they can reduce the number of inference calls altogether, rather than merely making each call cheaper.

## 15. Final engineering philosophy for Maail

I want us to lock this as a core principle:

# Build around intelligence, not inference.

## The LLM should be the last necessary step, not the first default step.

Every module should answer these questions:

1. Can deterministic code solve this?
2. Can existing data or a cached result solve this?
3. Can the task be completed with less context?
4. Does this agent actually need these tools?
5. Can the result be verified without another LLM call?
6. Can we measure whether this implementation is better?

One important qualification: harness engineering cannot guarantee zero mistakes or perfect reliability. What it can do is make behavior more constrained, measurable, reproducible and progressively improvable.

# 16. My recommended next step

Before we start implementation, I want to establish a proper Maail Engineering Constitution.

This should be a repository-level specification containing:

- Engineering principles.
- Development harness standards.
- Runtime harness standards.
- LLM efficiency policies.
- MCP tool governance.
- Module contracts.
- Architecture enforcement rules.
- Testing and evaluation standards.
- Coding-agent working instructions.
- Completion criteria for every implementation stage.

It should be referenced by `AGENTS.md`, HLD and all four LLD documents.

Then each development phase gets a small, explicit harness checklist, so harness engineering is implemented alongside the actual feature instead of being postponed.

My proposed sequence is:

1. Finalize the Maail Harness Engineering specification.
2. Revise HLD with the harness architecture and MCP layer.
3. Revise each LLD with its module-specific harness.
4. Define repository scripts, contracts and CI enforcement.
5. Establish baseline cost, quality and performance measurements.
6. Begin implementation.

I would make one more rule non-negotiable:

No new agent, MCP tool, AI feature or backend module enters Maail without documenting its execution boundaries, context requirements, resource budget, deterministic alternatives and verification method.

That is how we make Maail an engineered AI system rather than simply an application containing many AI calls.