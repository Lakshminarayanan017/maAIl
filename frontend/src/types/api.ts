/**
 * Shapes the API actually returns. Hand-written while the surface is small;
 * generated from the OpenAPI document once it is not, so a contract change
 * becomes a type error rather than a runtime surprise.
 */
export interface HealthLive {
  status: "ok";
  env: string;
  version: string;
}

export interface TenancyReport {
  role: string;
  is_superuser: boolean;
  can_bypass_rls: boolean;
  owns_tables: boolean;
  rls_enabled: boolean;
  rls_forced: boolean;
}

export interface HealthReady {
  status: "ok" | "degraded";
  database: boolean;
  migrations: string | null;
  tenancy: TenancyReport;
  problems: string[];
}

export interface SessionUser {
  id: string;
  email: string;
  name: string | null;
  timezone: string;
}

export interface SessionResponse {
  authenticated: true;
  user: SessionUser;
}

/**
 * `connecting`        the flow has started and not finished
 * `active`            usable
 * `reauth_required`   the refresh token is gone. The weekly case in Testing
 *                     mode, not an error: the banner shows, the user
 *                     reconnects, the account keeps its id.
 * `disconnected`      the user disconnected it; data purges at `purge_after`
 * `error`             a scope is missing, or something needs a human
 */
export type AccountStatus = "connecting" | "active" | "reauth_required" | "disconnected" | "error";

export interface SyncProgress {
  total: number | null;
  done: number;
  last_synced_at: string | null;
}

export interface Account {
  id: string;
  email: string;
  provider: string;
  status: AccountStatus;
  granted_scopes: string[];
  /** Non-empty when a scope was declined on the consent screen. */
  missing_scopes: string[];
  /** Known in advance, so the UI warns before the expiry rather than after. */
  refresh_expires_at: string | null;
  needs_reconnect: boolean;
  expires_soon: boolean;
  connected_at: string;
  last_error: string | null;
  sync_progress: SyncProgress;
  disconnected_at: string | null;
  purge_after: string | null;
}

// ---------------------------------------------------------------------------
// mail
// ---------------------------------------------------------------------------
export interface Participant {
  email: string | null;
  name: string | null;
}

/**
 * `category`, `priority` and `intelligence_status` are present and empty on
 * purpose. The row renders the slot as "not analysed yet" rather than
 * leaving a gap that shifts the layout once phase 6 fills it — and never
 * shows a value that no agent produced.
 */
export type ThreadCategory =
  | "technical"
  | "opportunity"
  | "academic"
  | "administrative"
  | "personal"
  | "promotional"
  | "notification"
  | "other";

export type CapabilityStatus =
  | "not_applicable"
  | "pending"
  | "running"
  | "ready"
  | "failed"
  | "skipped_disabled"
  | "skipped_budget";

export interface ThreadListItem {
  id: string;
  subject: string | null;
  sender: Participant;
  preview: string | null;
  latest_message_at: string | null;
  message_count: number;
  unread_count: number;
  has_attachments: boolean;
  is_read: boolean;
  content_version: number;

  // AI-derived, and labelled as such wherever it renders.
  category: ThreadCategory | null;
  priority: number | null;
  /** Never an unexplained badge. */
  priority_reason: string | null;
  needs_reply: boolean | null;
  is_technical: boolean | null;
  /** 'agent' | 'user_rule' | 'user_override' — kept visibly different. */
  category_source: string | null;
  status_summary: CapabilityStatus;
  status_deadline: CapabilityStatus;
  status_actions: CapabilityStatus;
  /** The judgement predates the newest message. Shown, not hidden. */
  stale: boolean;
}

export interface OverviewCounts {
  threads: number;
  unread: number;
  today: number;
  analysed: number;
}

export interface PriorityCard {
  thread_id: string;
  subject: string | null;
  sender: string | null;
  category: ThreadCategory | null;
  priority: number;
  priority_reason: string | null;
  is_technical: boolean;
  latest_message_at: string | null;
}

export interface Overview {
  greeting: string;
  counts: OverviewCounts;
  attention: PriorityCard[];
  upcoming_deadlines: Record<string, string>[];
  technical_count: number;
}

export interface ThreadPage {
  items: ThreadListItem[];
  next_cursor: string | null;
  total: number | null;
}

export interface Attachment {
  id: string;
  filename: string | null;
  mime_type: string | null;
  size_bytes: number | null;
}

export interface LinkWarning {
  text: string;
  href: string;
  claimed_host: string;
  actual_host: string;
}

/** Sanitised on the server, rendered in a sandboxed iframe, never stored. */
export interface MessageBody {
  message_id: string;
  html: string;
  blocked_images: number;
  images_loaded: boolean;
  link_warnings: LinkWarning[];
  empty: boolean;
}

/**
 * A date-ish phrase found deterministically in the message. Not a deadline:
 * deciding which of these is one, and for whom, is the Deadline agent's job
 * in phase 9.
 */
export interface DateCandidate {
  text: string;
  start: number;
  end: number;
  kind: "explicit_absolute" | "explicit_relative" | "soft_request" | "vague" | "recurring";
  resolved: string | null;
  confidence_band: "high" | "medium" | "low";
  rule: string;
}

export interface Message {
  id: string;
  from_email: string | null;
  from_name: string | null;
  to_emails: string[];
  cc_emails: string[];
  subject: string | null;
  sent_at: string;
  snippet: string | null;
  body_text: string | null;
  is_from_user: boolean;
  is_read: boolean;
  /** False while pass 2 has not reached this message yet. */
  has_body: boolean;
  /** Quoted history and signature removed. What the agents read. */
  body_text_stripped: string | null;
  /** How much the stripper took off, 0 to 1. */
  stripped_ratio: number | null;
  date_candidates: DateCandidate[];
  attachments: Attachment[];
}

export interface ThreadDetail {
  id: string;
  subject: string | null;
  participants: string[];
  message_count: number;
  unread_count: number;
  has_attachments: boolean;
  first_message_at: string | null;
  latest_message_at: string | null;
  content_version: number;
  messages: Message[];
}

export type SyncPhase =
  | "idle"
  | "starting"
  | "connecting"
  | "initial_metadata"
  | "initial_bodies"
  | "delta"
  | "reconciling"
  | "active"
  | "error"
  | "reauth_required";

export interface SyncStatus {
  account_id: string;
  phase: SyncPhase;
  done: number;
  total: number | null;
  threads: number;
  new_messages: number;
  misses: number;
  error: string | null;
}

/** Only the filters phase 2 can answer. The rest arrive with classification. */
export type ThreadFilter =
  | "all"
  | "unread"
  | "archived"
  | "important"
  | "technical"
  | "opportunities"
  | "team"
  | "notifications";

// ---------------------------------------------------------------------------
// agent runs
// ---------------------------------------------------------------------------
export interface RunStep {
  seq: number;
  kind: "llm" | "tool";
  tool_name: string | null;
  tool_args: Record<string, unknown> | null;
  /** A hash of what the tool returned, never the content. */
  tool_result_digest: string | null;
  tool_result_bytes: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
  created_at: string;
}

export interface AgentRun {
  id: string;
  agent_id: string;
  agent_version: string;
  plane: "U" | "C";
  trigger: string;
  subject_type: string | null;
  subject_id: string | null;
  status:
    | "queued"
    | "running"
    | "awaiting_approval"
    | "succeeded"
    | "failed"
    | "cancelled"
    | "budget_denied"
    | "cap_exceeded";
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  cost_micros: number;
  step_count: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface AgentRunDetail extends AgentRun {
  output: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  steps: RunStep[];
}

export interface BudgetStanding {
  state: "ok" | "soft_exceeded" | "hard_exceeded";
  spent_micros: number;
  soft_cap_micros: number;
  hard_cap_micros: number;
  remaining_micros: number;
}

// ---------------------------------------------------------------------------
// phase 8 — the intelligence panel
// ---------------------------------------------------------------------------

/**
 * The three classes the spec requires the reader to be able to tell apart:
 *
 * > Information explicitly present in the email. AI-generated
 * > interpretations. Information retrieved from external integrations.
 *
 * It is a field rather than a convention because a value alone cannot say
 * which of the three it is, and the panel paints them differently.
 */
export type Provenance = "stated" | "interpreted" | "retrieved";

/** A span the backend has already checked. `quote` exists because it resolved. */
export interface Evidence {
  message_id: string;
  char_start: number;
  char_end: number;
  quote: string | null;
}

export interface SummarySection {
  status: AiStatusValue;
  summary: string | null;
  bullet_points: string[];
  evidence: Evidence[];
  provenance: Provenance;
  model: string | null;
  stale: boolean;
}

export interface IntentSection {
  status: AiStatusValue;
  intent: string | null;
  reason: string | null;
  confidence: string | null;
  evidence: Evidence[];
  provenance: Provenance;
}

export type EntityKind =
  "project" | "repository" | "technology" | "date" | "error_message" | "person" | "organization";

export interface Entity {
  kind: EntityKind;
  value: string;
  provenance: Provenance;
  evidence: Evidence | null;
}

export interface ActionItem {
  id: string;
  description: string;
  owner: "user" | "sender" | "other" | "unclear";
  /** Never conflated with `inferred`. Rendered differently. */
  source: "stated" | "inferred";
  status: "open" | "done" | "dismissed";
  evidence: Evidence | null;
  task_id: string | null;
}

export interface Deadline {
  id: string;
  /** What the sender wrote. Always shown, whatever became of it. */
  raw_phrase: string;
  normalized_date: string | null;
  date_type: "explicit_absolute" | "explicit_relative" | "soft_request" | "vague" | "recurring";
  resolution_status: "resolved" | "ambiguous" | "unresolved" | "user_confirmed" | "user_corrected";
  confidence_band: "high" | "medium" | "low";
  is_for_user: boolean;
  evidence: Evidence | null;
}

export interface RelatedThread {
  thread_id: string;
  subject: string | null;
  sender: string | null;
  latest_message_at: string | null;
  category: string | null;
  because: string;
  provenance: Provenance;
}

export type AiStatusValue =
  | "not_applicable"
  | "pending"
  | "running"
  | "ready"
  | "failed"
  | "skipped_disabled"
  | "skipped_budget";

export interface ThreadIntelligence {
  thread_id: string;
  content_version: number;
  summary: SummarySection;
  intent: IntentSection;
  entities: Entity[];
  action_items: ActionItem[];
  deadlines: Deadline[];
  related: RelatedThread[];
  suggested_response: { available: boolean; arrives_in_phase?: number };
  status_summary: AiStatusValue;
  status_deadline: AiStatusValue;
  status_actions: AiStatusValue;
  /** What a POST would actually run, so the button offers the right thing. */
  missing: ("summary" | "deadlines" | "actions")[];
}

// ---------------------------------------------------------------------------
// phase 9 — tasks and deadlines
// ---------------------------------------------------------------------------
export interface Task {
  id: string;
  title: string;
  status: "pending" | "done" | "dismissed";
  origin: "user" | "ai_suggestion" | "sender_request";
  due_at: string | null;
  notes: string | null;
  remind_at: string | null;
  confirmed_at: string | null;
  completed_at: string | null;
  thread_id: string | null;
  thread_subject: string | null;
  source_sender: string | null;
  action_item_id: string | null;
  deadline_id: string | null;
  deadline_phrase: string | null;
  deadline_resolution: string | null;
}

export interface TaskPage {
  items: Task[];
  counts: { all: number; today: number; upcoming: number; completed: number };
}

/** An extracted action item that is not a task until someone accepts it. */
export interface Suggestion {
  action_item_id: string;
  description: string;
  owner: string;
  source: "stated" | "inferred";
  thread_id: string;
  thread_subject: string | null;
  sender: string | null;
  quote: string | null;
}

/** A deadline that renders as a question, never as a date. */
export interface AmbiguousDeadline {
  deadline_id: string;
  raw_phrase: string;
  date_type: string;
  confidence_band: string;
  thread_id: string;
  thread_subject: string | null;
  sender: string | null;
  message_sent_at: string | null;
  options: string[];
}

// ---------------------------------------------------------------------------
// phase 10 — companion and memory
// ---------------------------------------------------------------------------
export interface Conversation {
  id: string;
  title: string | null;
  thread_id: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface Citation {
  thread_id?: string;
  message_id: string;
  char_start: number;
  char_end: number;
  quote?: string | null;
}

export interface Turn {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  citations: Citation[];
  /** Which path answered. 'sql' and 'cached' cost nothing. */
  route: "sql" | "cached" | "model" | null;
  created_at: string;
}

export interface ConversationDetail {
  conversation: Conversation;
  turns: Turn[];
  suggested_prompts: string[];
}

export interface ThreadReference {
  thread_id: string;
  subject: string | null;
  sender: string | null;
  detail: string | null;
}

export interface AskDone {
  turn_id: string;
  answer: string;
  citations: Citation[];
  references: ThreadReference[];
  follow_ups: string[];
  route: "sql" | "cached" | "model";
  cost_micros: number;
  dropped_citations: number;
}

export interface Fact {
  id: string;
  fact_type: "preference" | "interest" | "relationship" | "project_fact";
  subject: string;
  content: string;
  source: "user_stated" | "agent_inferred" | "derived";
  confirmation_status: "unconfirmed" | "user_confirmed" | "user_rejected";
  confidence_band: "high" | "medium" | "low";
  observation_count: number;
  first_seen_at: string;
  last_confirmed_at: string | null;
  expires_at: string | null;
  quote: string | null;
  source_thread_id: string | null;
  source_message_id: string | null;
}

export interface MemoryConflict {
  proposal_id: string;
  fact_type: string;
  subject: string;
  proposed_content: string;
  stored_fact_id: string | null;
  stored_content: string | null;
  created_at: string;
}

export interface MemoryRejection {
  id: string;
  fact_type: string;
  subject: string;
  content: string;
  status: string;
  rejection_reason: string | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// phase 11 — feature controls
// ---------------------------------------------------------------------------
export interface ConfigOption {
  value: string;
  label: string;
  /** The spec's exact wording, carried from the server rather than retyped. */
  detail: string;
}

export interface ConfigFieldSchema {
  key: string;
  label: string;
  kind: "choice" | "number" | "tags";
  default: unknown;
  options: ConfigOption[];
  minimum: number | null;
  maximum: number | null;
  help: string;
}

export interface FeatureToggle {
  id: string;
  name: string;
  description: string;
  group: string;
  enabled: boolean;
  default: boolean;
  /** What this needs. Turning it on turns these on too. */
  requires: string[];
  /** What needs this. Turning it off turns these off too. */
  required_by: string[];
  /** False when the capability has not been built yet. */
  live: boolean;
  arrives_in_phase: number | null;
  config: Record<string, unknown>;
  config_schema: ConfigFieldSchema[];
}

export interface FeatureGroupOut {
  id: string;
  label: string;
  features: FeatureToggle[];
}

export interface FeaturePreset {
  id: string;
  name: string;
  label: string;
  features: string[];
  active: boolean;
}

export interface SettingsSection {
  id: string;
  label: string;
  controls: string;
}

export interface FeatureSettings {
  groups: FeatureGroupOut[];
  presets: FeaturePreset[];
  sections: SettingsSection[];
  enabled_count: number;
  total_count: number;
}

export interface FeatureChange {
  settings: FeatureSettings;
  /** Ids that moved as a consequence rather than by being clicked. */
  also_changed: string[];
}
