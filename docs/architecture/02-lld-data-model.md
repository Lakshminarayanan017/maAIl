# Maail LLD — Data Model

PostgreSQL 16. Every user-scoped table carries `user_id` and an RLS policy. All DDL below
is the v1 target; `uuid` defaults assume `pgcrypto`.

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS btree_gin;
-- pgvector deliberately absent; see 00-gap-analysis.md §1 gap 6
```

## 1. Identity and connections

```sql
CREATE TABLE users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email         citext NOT NULL UNIQUE,
  name          text,
  timezone      text NOT NULL DEFAULT 'UTC',   -- resolves relative dates (E2)
  created_at    timestamptz NOT NULL DEFAULT now(),
  deleted_at    timestamptz
);

CREATE TYPE account_status AS ENUM (
  'connecting', 'active', 'reauth_required', 'disconnected', 'error'
);

CREATE TABLE connected_accounts (
  id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                 uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider                text NOT NULL CHECK (provider IN ('gmail')),
  provider_account_email  citext NOT NULL,
  status                  account_status NOT NULL DEFAULT 'connecting',
  granted_scopes          text[] NOT NULL DEFAULT '{}',

  -- sync cursors (A2: cursor age matters as much as the cursor)
  history_cursor          text,
  history_cursor_at       timestamptz,
  initial_sync_total      int,
  initial_sync_done       int NOT NULL DEFAULT 0,
  last_delta_sync_at      timestamptz,
  last_error              text,

  created_at              timestamptz NOT NULL DEFAULT now(),
  disconnected_at         timestamptz,
  purge_after             timestamptz,              -- O5: 30-day soft delete
  UNIQUE (user_id, provider, provider_account_email)
);

-- Envelope encryption, rotatable (D8)
CREATE TABLE oauth_credentials (
  account_id          uuid PRIMARY KEY REFERENCES connected_accounts(id) ON DELETE CASCADE,
  user_id             uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  access_ciphertext   bytea NOT NULL,
  refresh_ciphertext  bytea NOT NULL,
  dek_wrapped         bytea NOT NULL,
  key_version         int   NOT NULL,
  access_expires_at   timestamptz,
  refresh_expires_at  timestamptz,   -- A3: ~7 days while in Testing mode
  updated_at          timestamptz NOT NULL DEFAULT now()
);
```

`refresh_expires_at` is populated from the known Testing-mode window so the UI can warn
*before* the token dies rather than after a sync fails.

## 2. Threads and messages

The internal `id` is the intelligence anchor; `provider_thread_id` is a mutable attribute,
because Gmail splits and merges threads (A5).

```sql
CREATE TABLE email_threads (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id               uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  account_id            uuid NOT NULL REFERENCES connected_accounts(id) ON DELETE CASCADE,
  provider_thread_id    text NOT NULL,
  merged_into_thread_id uuid REFERENCES email_threads(id),  -- A5

  subject               text,
  subject_normalized    text,            -- re:/fwd: stripped, for merge detection
  participant_emails    citext[] NOT NULL DEFAULT '{}',
  message_count         int NOT NULL DEFAULT 0,
  unread_count          int NOT NULL DEFAULT 0,
  has_attachments       boolean NOT NULL DEFAULT false,
  provider_labels       text[] NOT NULL DEFAULT '{}',

  first_message_at      timestamptz,
  latest_message_at     timestamptz,

  -- bumped on every ingested message; invalidates derived rows (C4, D5)
  content_version       int NOT NULL DEFAULT 0,
  search_tsv            tsvector,

  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (account_id, provider_thread_id)
);

CREATE TABLE email_messages (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  account_id           uuid NOT NULL REFERENCES connected_accounts(id) ON DELETE CASCADE,
  thread_id            uuid NOT NULL REFERENCES email_threads(id) ON DELETE CASCADE,

  provider_message_id  text NOT NULL,
  rfc822_message_id    text,             -- A5: survives provider re-threading
  in_reply_to          text,
  references_ids       text[],

  from_email           citext,
  from_name            text,
  to_emails            citext[] NOT NULL DEFAULT '{}',
  cc_emails            citext[] NOT NULL DEFAULT '{}',
  subject              text,

  sent_at              timestamptz NOT NULL,
  sender_tz_offset_min int,              -- E2: from the Date header

  snippet              text,
  body_text            text,             -- cleaned plain text
  body_text_stripped   text,             -- B1: quotes + signature removed
  stripped_ratio       real,             -- observability on the biggest cost lever

  size_bytes           int,
  is_from_user         boolean NOT NULL DEFAULT false,  -- A6
  is_read              boolean NOT NULL DEFAULT false,
  provider_labels      text[] NOT NULL DEFAULT '{}',
  body_fetched_at      timestamptz,      -- null => metadata-only (A1 pass 1)

  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (account_id, provider_message_id)      -- dedupe by DB, not by code
);
```

Raw HTML is deliberately **not** a column (E6). Bodies render from an on-demand Gmail fetch,
sanitised at the edge. This removes the largest single item from the breach surface and the
largest single item from the database.

```sql
CREATE TABLE message_attachments (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  message_id  uuid NOT NULL REFERENCES email_messages(id) ON DELETE CASCADE,
  filename    text,
  mime_type   text,
  size_bytes  int,
  provider_attachment_id text
  -- D6: metadata only. No content, no parsing, in v1.
);
```

## 3. Intelligence — current plus history

```sql
CREATE TYPE thread_category AS ENUM (
  'technical','opportunity','academic','administrative',
  'personal','promotional','notification','other'
);  -- E4: fixed, so eval is possible

CREATE TYPE capability_status AS ENUM (
  'not_applicable','pending','running','ready','failed','skipped_disabled','skipped_budget'
);

CREATE TABLE thread_intelligence (
  thread_id        uuid PRIMARY KEY REFERENCES email_threads(id) ON DELETE CASCADE,
  user_id          uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  category         thread_category,
  category_source  text CHECK (category_source IN ('user_rule','agent','user_override')),
  priority         smallint CHECK (priority BETWEEN 0 AND 3),
  priority_reason  text,
  priority_computed_at timestamptz,        -- E3: decay at query time
  needs_reply      boolean,
  is_technical     boolean,

  routed_agents    text[] NOT NULL DEFAULT '{}',

  -- C4: honest per-capability state, never one global boolean
  status_summary   capability_status NOT NULL DEFAULT 'pending',
  status_deadline  capability_status NOT NULL DEFAULT 'pending',
  status_actions   capability_status NOT NULL DEFAULT 'pending',
  status_developer capability_status NOT NULL DEFAULT 'not_applicable',
  status_opportunity capability_status NOT NULL DEFAULT 'not_applicable',

  computed_from_content_version int NOT NULL,
  pipeline_version text NOT NULL,          -- C7
  updated_at       timestamptz NOT NULL DEFAULT now()
);

-- Why a thread became important, preserved rather than overwritten
CREATE TABLE thread_intelligence_versions (
  id                 bigserial PRIMARY KEY,
  thread_id          uuid NOT NULL REFERENCES email_threads(id) ON DELETE CASCADE,
  user_id            uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  snapshot           jsonb NOT NULL,
  content_version    int NOT NULL,
  pipeline_version   text NOT NULL,
  trigger_message_id uuid REFERENCES email_messages(id),
  agent_run_id       uuid,
  created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE thread_summaries (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  thread_id       uuid NOT NULL REFERENCES email_threads(id) ON DELETE CASCADE,
  user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind            text NOT NULL CHECK (kind IN ('short','detailed')),
  summary         text NOT NULL,
  bullet_points   jsonb,
  evidence        jsonb,       -- [{message_id, char_start, char_end}]
  content_version int NOT NULL,
  model           text,
  agent_run_id    uuid,
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (thread_id, kind, content_version)   -- cache key: never recompute for free
);
```

## 4. Deadlines — the honest schema

This is the table most likely to make Maail look either trustworthy or stupid.

```sql
CREATE TYPE date_type AS ENUM (
  'explicit_absolute',   -- "submit by 12 November"
  'explicit_relative',   -- "by Friday"
  'soft_request',        -- "hoping to receive it by Friday"
  'vague',               -- "finish it soon"
  'recurring'
);

CREATE TYPE date_resolution AS ENUM (
  'resolved','ambiguous','unresolved','user_confirmed','user_corrected'
);

CREATE TABLE deadlines (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id            uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  thread_id          uuid NOT NULL REFERENCES email_threads(id) ON DELETE CASCADE,
  message_id         uuid NOT NULL REFERENCES email_messages(id) ON DELETE CASCADE,

  raw_phrase         text NOT NULL,          -- always shown to the user (E2)
  normalized_date    date,
  normalized_time    time,
  timezone           text,
  date_type          date_type NOT NULL,
  resolution_status  date_resolution NOT NULL,
  confidence_band    text NOT NULL CHECK (confidence_band IN ('high','medium','low')),
                     -- E1: a band, not a fabricated float

  evidence_char_start int,
  evidence_char_end   int,

  is_for_user        boolean NOT NULL DEFAULT true,
  created_by         text NOT NULL CHECK (created_by IN ('agent','user','rule')),
  superseded_by      uuid REFERENCES deadlines(id),
  created_at         timestamptz NOT NULL DEFAULT now()
);
```

The three sentences from the v2 document now land in distinct rows:

| Email text | `date_type` | `resolution_status` | `confidence_band` |
|---|---|---|---|
| "Submit the assignment by Friday." | `explicit_relative` | `resolved` | high |
| "We are hoping to receive it by Friday." | `soft_request` | `resolved` | medium |
| "It would be good if you could finish it soon." | `vague` | `unresolved` | low |

A row with `resolution_status = 'ambiguous'` renders as a question to the user, never as a
date. Nothing is invented to fill the column.

## 5. Actions, opportunities, findings, tasks

```sql
CREATE TABLE action_items (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  thread_id     uuid NOT NULL REFERENCES email_threads(id) ON DELETE CASCADE,
  message_id    uuid REFERENCES email_messages(id),
  description   text NOT NULL,
  owner         text NOT NULL CHECK (owner IN ('user','sender','other','unclear')),
  source        text NOT NULL CHECK (source IN ('stated','inferred')),  -- never conflated
  evidence_char_start int,
  evidence_char_end   int,
  status        text NOT NULL DEFAULT 'open'
                CHECK (status IN ('open','done','dismissed')),
  created_by    text NOT NULL CHECK (created_by IN ('agent','user')),
  agent_run_id  uuid,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE opportunities (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  thread_id      uuid NOT NULL REFERENCES email_threads(id) ON DELETE CASCADE,
  kind           text CHECK (kind IN ('internship','job','hackathon','event','scholarship','other')),
  organization   text,
  role_title     text,
  location       text,
  apply_by       uuid REFERENCES deadlines(id),
  already_applied boolean,                  -- agent checks prior threads before claiming
  requirements   jsonb,
  stage          text DEFAULT 'discovered',
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE dev_findings (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  thread_id      uuid NOT NULL REFERENCES email_threads(id) ON DELETE CASCADE,
  issue_type     text CHECK (issue_type IN ('ci_failure','pr_review','bug_report',
                                            'deploy','api_issue','other')),
  repository     text,
  branch         text,
  failed_tests   text[],
  error_excerpt  text,
  github_refs    jsonb,       -- [{type:'pr'|'issue', number, url, fetched_at}]
  evidence       jsonb,
  -- never a root-cause claim without this being non-empty
  supporting_evidence_count int NOT NULL DEFAULT 0,
  agent_run_id   uuid,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tasks (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title           text NOT NULL,
  thread_id       uuid REFERENCES email_threads(id) ON DELETE SET NULL,
  action_item_id  uuid REFERENCES action_items(id) ON DELETE SET NULL,
  deadline_id     uuid REFERENCES deadlines(id) ON DELETE SET NULL,
  due_at          timestamptz,
  status          text NOT NULL DEFAULT 'pending',
  origin          text NOT NULL CHECK (origin IN ('user','ai_suggestion','sender_request')),
  confirmed_at    timestamptz,    -- AI suggestions are not tasks until confirmed
  created_at      timestamptz NOT NULL DEFAULT now()
);
```

## 6. Features, rules, budgets

```sql
CREATE TABLE user_features (
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  feature_id text NOT NULL,
  enabled    boolean NOT NULL,
  config     jsonb NOT NULL DEFAULT '{}',
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, feature_id)
);

-- E4/F4: deterministic pass, runs BEFORE any agent, can override it
CREATE TABLE user_rules (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name       text NOT NULL,
  priority   int NOT NULL DEFAULT 100,
  match      jsonb NOT NULL,   -- {from_domain, from_email, subject_contains,
                               --  body_contains, has_label}
  action     jsonb NOT NULL,   -- {set_category, set_priority, add_label,
                               --  skip_intelligence}
  enabled    boolean NOT NULL DEFAULT true,
  derived_from_override_id uuid,     -- born from a user correction
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_overrides (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  thread_id   uuid NOT NULL REFERENCES email_threads(id) ON DELETE CASCADE,
  field       text NOT NULL,     -- 'category' | 'priority' | 'deadline'
  old_value   jsonb,
  new_value   jsonb NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- B3: enforced before the model call
CREATE TABLE usage_budgets (
  user_id          uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  period_month     date NOT NULL,
  soft_cap_micros  bigint NOT NULL,
  hard_cap_micros  bigint NOT NULL,
  spent_micros     bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, period_month)
);
```

## 7. Agents, approvals, jobs, audit

```sql
CREATE TYPE agent_run_status AS ENUM (
  'queued','running','awaiting_approval','succeeded',
  'failed','cancelled','budget_denied','cap_exceeded'
);

CREATE TABLE agent_runs (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  agent_id       text NOT NULL,
  agent_version  text NOT NULL,                      -- C7
  plane          text NOT NULL CHECK (plane IN ('U','C')),
  trigger        text NOT NULL,
  subject_type   text,
  subject_id     uuid,
  parent_run_id  uuid REFERENCES agent_runs(id),     -- C3: cycle detection
  depth          smallint NOT NULL DEFAULT 0,

  status         agent_run_status NOT NULL DEFAULT 'queued',
  output         jsonb,
  error          jsonb,

  model          text,
  input_tokens   int NOT NULL DEFAULT 0,
  output_tokens  int NOT NULL DEFAULT 0,
  cached_input_tokens int NOT NULL DEFAULT 0,         -- B5
  cost_micros    bigint NOT NULL DEFAULT 0,
  step_count     smallint NOT NULL DEFAULT 0,

  started_at     timestamptz,
  finished_at    timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now()
);

-- C1: without this, agent bugs are unreproducible
CREATE TABLE agent_steps (
  id                 bigserial PRIMARY KEY,
  run_id             uuid NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  user_id            uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  seq                smallint NOT NULL,
  kind               text NOT NULL CHECK (kind IN ('llm','tool')),
  tool_name          text,
  tool_args          jsonb,
  tool_result_digest text,        -- D8: digest, never raw email text
  tool_result_bytes  int,
  input_tokens       int,
  output_tokens      int,
  latency_ms         int,
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, seq)
);
```

### Proposed actions — the only route to an external side effect

```sql
CREATE TYPE action_status AS ENUM (
  'pending','approved','rejected','expired','superseded','executing','executed','failed'
);

CREATE TABLE proposed_actions (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  run_id           uuid REFERENCES agent_runs(id) ON DELETE SET NULL,

  action_type      text NOT NULL,     -- allowlist-validated in code
  params           jsonb NOT NULL,    -- validated against the per-type schema
  target_summary   text NOT NULL,     -- the human-readable line in the approval UI

  thread_id        uuid REFERENCES email_threads(id) ON DELETE CASCADE,
  evidence_ids     uuid[] NOT NULL DEFAULT '{}',

  -- D5: approval binds to content AND context
  content_hash     text NOT NULL,
  context_version  int NOT NULL,

  status           action_status NOT NULL DEFAULT 'pending',
  expires_at       timestamptz NOT NULL,
  approval_token_hash text,           -- single use
  approved_by      uuid REFERENCES users(id),
  approved_at      timestamptz,

  idempotency_key  text NOT NULL UNIQUE,       -- D4: retries cannot double-send
  executed_at      timestamptz,
  execution_result jsonb,
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE permission_grants (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  capability  text NOT NULL,      -- 'gmail.draft','gmail.send','github.read'
  scope       jsonb NOT NULL DEFAULT '{}',
  granted_at  timestamptz NOT NULL DEFAULT now(),
  revoked_at  timestamptz
);
```

### Job queue

```sql
CREATE TABLE background_jobs (
  id               bigserial PRIMARY KEY,
  user_id          uuid REFERENCES users(id) ON DELETE CASCADE,
  job_type         text NOT NULL,
  payload          jsonb NOT NULL DEFAULT '{}',
  dedupe_key       text,              -- C5: collapses reprocessing storms
  priority         smallint NOT NULL DEFAULT 100,
  status           text NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','running','completed','failed','dead')),
  attempts         int NOT NULL DEFAULT 0,
  max_attempts     int NOT NULL DEFAULT 5,
  available_at     timestamptz NOT NULL DEFAULT now(),
  locked_by        text,
  lease_expires_at timestamptz,
  last_error       text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

-- one live job per dedupe_key
CREATE UNIQUE INDEX uq_jobs_dedupe_live ON background_jobs (dedupe_key)
  WHERE dedupe_key IS NOT NULL AND status IN ('pending','running');

CREATE TABLE audit_logs (
  id          bigserial PRIMARY KEY,
  user_id     uuid REFERENCES users(id) ON DELETE SET NULL,
  actor       text NOT NULL,      -- 'user' | 'system' | agent_id
  action      text NOT NULL,
  subject_type text,
  subject_id  uuid,
  detail      jsonb,
  ip          inet,
  created_at  timestamptz NOT NULL DEFAULT now()
);
```

### Companion conversations

```sql
CREATE TABLE chat_conversations (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title      text,
  thread_id  uuid REFERENCES email_threads(id) ON DELETE SET NULL,  -- thread-scoped chat
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chat_messages (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
  user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role            text NOT NULL CHECK (role IN ('user','assistant','system')),
  content         text NOT NULL,
  citations       jsonb,     -- [{thread_id, message_id, char_start, char_end}]
  run_id          uuid REFERENCES agent_runs(id),
  created_at      timestamptz NOT NULL DEFAULT now()
);
```

## 8. Row-level security

The boundary. Not a convention.

```sql
ALTER DATABASE maail SET row_security = on;

CREATE OR REPLACE FUNCTION app_current_user() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('app.user_id', true), '')::uuid
$$;

-- applied to every user-scoped table
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'connected_accounts','oauth_credentials','email_threads','email_messages',
    'message_attachments','thread_intelligence','thread_intelligence_versions',
    'thread_summaries','deadlines','action_items','opportunities','dev_findings',
    'tasks','user_features','user_rules','user_overrides','usage_budgets',
    'agent_runs','agent_steps','proposed_actions','permission_grants',
    'chat_conversations','chat_messages'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (user_id = app_current_user())
         WITH CHECK (user_id = app_current_user())', t);
  END LOOP;
END $$;
```

The application connects as a **non-superuser, non-owner** role — `FORCE ROW LEVEL
SECURITY` plus a non-owner role is what actually makes the policy inescapable. Every
request sets `SET LOCAL app.user_id = $1` inside the transaction; every job wrapper does the
same. Phase 0 is not complete until a test proves user A's query returns zero of user B's
rows **with the application's own connection**.

## 9. Indexes

```sql
-- E5: cursor pagination for the inbox
CREATE INDEX ix_threads_inbox ON email_threads (user_id, latest_message_at DESC, id DESC);
CREATE INDEX ix_threads_account ON email_threads (account_id, latest_message_at DESC);

-- full-text search; replaces a vector store in v1
CREATE INDEX ix_threads_tsv ON email_threads USING gin (search_tsv);
CREATE INDEX ix_threads_participants ON email_threads USING gin (participant_emails);

CREATE INDEX ix_messages_thread ON email_messages (thread_id, sent_at);
CREATE INDEX ix_messages_from ON email_messages (user_id, from_email, sent_at DESC);
-- A1 pass 2: find what still needs a body
CREATE INDEX ix_messages_needs_body ON email_messages (account_id, sent_at DESC)
  WHERE body_fetched_at IS NULL;

-- the triage/work queue: threads whose intelligence is stale
CREATE INDEX ix_ti_stale ON thread_intelligence (user_id)
  WHERE status_summary IN ('pending','failed');

CREATE INDEX ix_deadlines_upcoming ON deadlines (user_id, normalized_date)
  WHERE resolution_status IN ('resolved','user_confirmed') AND is_for_user;
CREATE INDEX ix_deadlines_ambiguous ON deadlines (user_id)
  WHERE resolution_status = 'ambiguous';

-- the job claim path
CREATE INDEX ix_jobs_claim ON background_jobs (priority, available_at, id)
  WHERE status = 'pending';
CREATE INDEX ix_jobs_reap ON background_jobs (lease_expires_at)
  WHERE status = 'running';

CREATE INDEX ix_runs_cost ON agent_runs (user_id, agent_id, created_at DESC);
CREATE INDEX ix_actions_pending ON proposed_actions (user_id, status, expires_at)
  WHERE status = 'pending';
```

### Search vector maintenance

```sql
CREATE OR REPLACE FUNCTION refresh_thread_tsv(p_thread_id uuid) RETURNS void
LANGUAGE sql AS $$
  UPDATE email_threads t SET search_tsv =
      setweight(to_tsvector('english', coalesce(t.subject,'')), 'A')
   || setweight(to_tsvector('english',
        coalesce((SELECT string_agg(m.body_text_stripped, ' ')
                    FROM email_messages m WHERE m.thread_id = t.id), '')), 'B')
   || setweight(to_tsvector('simple',
        array_to_string(t.participant_emails, ' ')), 'C')
  WHERE t.id = p_thread_id;
$$;
```

Subject outranks body, body outranks participants. Built from `body_text_stripped`, so
quoted chains do not pollute relevance — the same column that saves the token budget also
improves search quality.

## 10. Lifecycle rules

| Event | Consequence |
|---|---|
| Message ingested | `content_version` bumps; `search_tsv` refreshed; significance gate evaluated (C5) |
| Gate passes | Triage job enqueued with `dedupe_key = 'triage:' || thread_id` |
| Gate fails | Nothing runs. Thread stays current. |
| `content_version` moves | Derived rows for the old version stay, marked stale by comparison, never deleted |
| Feature disabled | Future runs become `skipped_disabled`. **Existing results are retained.** |
| User override | `user_overrides` row written; a `user_rule` is *suggested*, not auto-created |
| Thread merged | `merged_into_thread_id` set; intelligence re-derived on the surviving thread |
| Account disconnected | `purge_after = now() + 30 days`; immediate purge on request (O5) |
| Approval given | Token single-use; `content_hash` + `context_version` re-checked at execution |
| Thread changes while an approval is pending | Proposal → `superseded`; the user is told why |

## 11. v3.1 additions — memory, MCP and cache tables

Full rationale in `05-memory.md`, `06-mcp.md` and `07-harness.md`. Only the schema here.

### What deliberately gets no table

| Candidate | Why not |
|---|---|
| `episodic_memories` | The existing thread/intelligence/run tables **are** the episodic record. A parallel store means dual writes and divergence on every `content_version` bump. Episodic memory is a retriever. |
| `procedures` | Procedural memory lives in Git, read at deploy. If a procedure is never a row, an email can never write one. |
| `working_memory` / session store | Working memory is the assembled context for one run. What survives is `agent_runs.output` and `chat_messages`. |
| `tool_definitions` | MCP schemas are pinned in Git at `tool_contracts/<server>/<tool>.json` so a schema change is a reviewed commit. |

Three of the four reference-architecture datastores disappear here, and the fourth is the
repository you already have.

### Semantic facts

```sql
CREATE TYPE fact_type AS ENUM ('preference','interest','relationship','project_fact');
```

The enum is the primary defence against persistent prompt injection: there is **no row shape**
for a fact that alters agent behaviour or grants a permission, so the dangerous fact cannot be
stored even if a model extracts it. See `05-memory.md` §2.

```sql
CREATE TABLE semantic_facts (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  fact_type      fact_type NOT NULL,
  subject        text NOT NULL,
  content        text NOT NULL,

  source         text NOT NULL CHECK (source IN ('user_stated','agent_inferred','derived')),
  source_thread_id  uuid REFERENCES email_threads(id) ON DELETE SET NULL,
  source_message_id uuid REFERENCES email_messages(id) ON DELETE SET NULL,
  evidence_char_start int,
  evidence_char_end   int,

  confirmation_status text NOT NULL DEFAULT 'unconfirmed'
    CHECK (confirmation_status IN ('unconfirmed','user_confirmed','user_rejected')),
  confidence_band text NOT NULL CHECK (confidence_band IN ('high','medium','low')),

  first_seen_at     timestamptz NOT NULL DEFAULT now(),
  last_confirmed_at timestamptz,
  observation_count int NOT NULL DEFAULT 1,
  expires_at        timestamptz,
  superseded_by     uuid REFERENCES semantic_facts(id),
  deleted_at        timestamptz,
  UNIQUE (user_id, fact_type, subject)
);

CREATE TABLE memory_proposals (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  run_id      uuid REFERENCES agent_runs(id) ON DELETE SET NULL,
  operation   text NOT NULL CHECK (operation IN ('create','update','supersede','delete')),
  fact_type   fact_type NOT NULL,
  subject     text NOT NULL,
  content     text NOT NULL,
  evidence    jsonb NOT NULL,
  status      text NOT NULL DEFAULT 'pending'
              CHECK (status IN ('pending','accepted','rejected_policy',
                                'rejected_duplicate','rejected_no_evidence')),
  rejection_reason text,
  created_at  timestamptz NOT NULL DEFAULT now()
);
```

Agents write `memory_proposals`; deterministic validation promotes to `semantic_facts`. No
agent tool writes `semantic_facts` directly.

### Intelligence cache

```sql
CREATE TABLE intelligence_cache (
  cache_key    text PRIMARY KEY,         -- sha256 of the 9-part composite, 07-harness §4
  user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  thread_id    uuid REFERENCES email_threads(id) ON DELETE CASCADE,
  agent_id     text NOT NULL,
  result_ref   jsonb NOT NULL,           -- POINTER to the real row, never a copy
  hit_count    int NOT NULL DEFAULT 0,
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_hit_at  timestamptz
);
```

`result_ref` is a pointer for the same reason episodic memory gets no table: a copy is a
second source of truth for intelligence.

### MCP invocation accounting

`agent_steps` already records tool calls. Two columns are added so MCP boundaries are
attributable and schema drift is diagnosable after the fact:

```sql
ALTER TABLE agent_steps ADD COLUMN mcp_server_ns text;
ALTER TABLE agent_steps ADD COLUMN mcp_schema_hash text;
```

### Indexes and RLS

```sql
CREATE INDEX ix_facts_live ON semantic_facts (user_id, fact_type)
  WHERE deleted_at IS NULL AND superseded_by IS NULL;
CREATE INDEX ix_facts_expiring ON semantic_facts (expires_at)
  WHERE expires_at IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX ix_proposals_pending ON memory_proposals (user_id, created_at)
  WHERE status = 'pending';
CREATE INDEX ix_cache_thread ON intelligence_cache (user_id, thread_id);
```

`semantic_facts`, `memory_proposals` and `intelligence_cache` join the RLS loop in §8. The
"can one user's memory appear in another user's results?" test is answered by RLS, not by
trusting that every memory query was written correctly.

### Lifecycle additions to §10

| Event | Consequence |
|---|---|
| Proposal accepted | `semantic_facts` row created `unconfirmed`, with provenance mandatory |
| Same fact observed again | `observation_count++`, `last_confirmed_at` refreshed — no duplicate row |
| Conflicting fact proposed | User is asked. Nothing flips silently. |
| User confirms a fact | `user_confirmed` — permanent, outranks every inferred fact |
| Inferred fact untouched 90 days | Soft-deleted by the consolidation job |
| `content_version` bumps | Cache entries for that thread become unreachable by key; rows are retained |
| Prompt or agent version changes | Cache key changes, so stale results are unreachable rather than wrongly reused |
| Account deleted | Facts, proposals and cache cascade |
