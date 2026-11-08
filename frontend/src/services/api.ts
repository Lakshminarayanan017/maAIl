import type {
  Account,
  AgentRun,
  AgentRunDetail,
  AmbiguousDeadline,
  AskDone,
  BudgetStanding,
  Conversation,
  ConversationDetail,
  Fact,
  FeatureChange,
  FeatureSettings,
  HealthLive,
  HealthReady,
  MemoryConflict,
  MemoryRejection,
  MessageBody,
  Overview,
  SessionResponse,
  Suggestion,
  SyncStatus,
  Task,
  TaskPage,
  ThreadDetail,
  ThreadFilter,
  ThreadIntelligence,
  ThreadPage,
} from "@/types/api";

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

const CSRF_COOKIE = "maail_csrf";
const CSRF_HEADER = "X-CSRF-Token";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /** The X-Request-ID the server echoed, for the error state to surface. */
    readonly requestId: string | null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  get isUnauthenticated(): boolean {
    return this.status === 401;
  }
}

/**
 * The other half of the double-submit CSRF check. The cookie is deliberately
 * readable; echoing it in a header is what proves the request came from a
 * page on this origin rather than from someone else's form.
 */
function csrfToken(): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${CSRF_COOKIE}=([^;]*)`));
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

/**
 * One fetch wrapper. Credentials are included because the session is a
 * cookie, and the request id is carried out of the response so an ErrorState
 * can show something a human can correlate with a log line.
 */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const mutating = !["GET", "HEAD", "OPTIONS"].includes(method);
  const token = mutating ? csrfToken() : null;

  const response = await fetch(`${BASE_URL}/api/v1${path}`, {
    ...init,
    method,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { [CSRF_HEADER]: token } : {}),
      ...init.headers,
    },
  });

  const requestId = response.headers.get("X-Request-ID");

  if (!response.ok) {
    throw new ApiError(
      await readErrorDetail(response, `${method} ${path}`),
      response.status,
      requestId,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    /* an error response that is not JSON is still an error */
  }
  return `${fallback} failed (${response.status})`;
}

export const health = {
  live: () => apiFetch<HealthLive>("/health/live"),
  ready: () => apiFetch<HealthReady>("/health/ready"),
};

export const auth = {
  session: () => apiFetch<SessionResponse>("/auth/session"),
  /** Returns the Google consent URL; the caller navigates the whole page. */
  startGoogle: () => apiFetch<{ authorize_url: string }>("/auth/google/start", { method: "POST" }),
  signOut: () => apiFetch<void>("/auth/signout", { method: "POST" }),
};

export const accounts = {
  list: (includeDisconnected = false) =>
    apiFetch<Account[]>(`/accounts?include_disconnected=${String(includeDisconnected)}`),
  reconnect: (id: string) =>
    apiFetch<{ authorize_url: string }>(`/accounts/${id}/reconnect`, { method: "POST" }),
  disconnect: (id: string, purge: "now" | "30d" = "30d") =>
    apiFetch<{ id: string; status: string; purge_after: string | null }>(
      `/accounts/${id}?purge=${purge}`,
      { method: "DELETE" },
    ),
};

export const threads = {
  list: (params: {
    cursor?: string | null;
    limit?: number;
    filter?: ThreadFilter;
    q?: string | null;
  }) => {
    const search = new URLSearchParams();
    if (params.cursor) search.set("cursor", params.cursor);
    if (params.limit) search.set("limit", String(params.limit));
    if (params.filter) search.set("filter", params.filter);
    if (params.q) search.set("q", params.q);
    const query = search.toString();
    return apiFetch<ThreadPage>(`/threads${query ? `?${query}` : ""}`);
  },
  read: (id: string) => apiFetch<ThreadDetail>(`/threads/${id}`),
  /** Fetched on demand: raw HTML is never stored, so this costs a Gmail call. */
  body: (threadId: string, messageId: string, images: "blocked" | "allowed" = "blocked") =>
    apiFetch<MessageBody>(`/threads/${threadId}/messages/${messageId}/body?images=${images}`),
  /** A correction. Wins immediately, recorded, may suggest a rule. */
  override: (
    id: string,
    field: "category" | "priority" | "needs_reply",
    value: string | number | boolean,
  ) =>
    apiFetch<{
      thread_id: string;
      field: string;
      value: string | number | boolean;
      suggested_rule: { name: string; because: string } | null;
    }>(`/threads/${id}/override`, {
      method: "POST",
      body: JSON.stringify({ field, value }),
    }),
  setRead: (id: string, isRead: boolean) =>
    apiFetch<{ is_read: boolean }>(`/threads/${id}/read`, {
      method: "POST",
      body: JSON.stringify({ is_read: isRead }),
    }),
};

export const sync = {
  trigger: (accountId: string, full = false) =>
    apiFetch<{ account_id: string; phase: string; already_running: boolean }>(
      `/sync/trigger?account_id=${accountId}&full=${String(full)}`,
      { method: "POST" },
    ),
  status: (accountId: string) => apiFetch<SyncStatus>(`/sync/status/once?account_id=${accountId}`),
  /** The live stream. Returns an unsubscribe function. */
  watch: (accountId: string, onStatus: (status: SyncStatus) => void): (() => void) => {
    const url = `${BASE_URL}/api/v1/sync/status?account_id=${accountId}`;
    const source = new EventSource(url, { withCredentials: true });
    source.onmessage = (event: MessageEvent<string>) => {
      try {
        onStatus(JSON.parse(event.data) as SyncStatus);
      } catch {
        /* a malformed frame is not worth tearing the stream down for */
      }
    };
    source.addEventListener("done", () => source.close());
    // An SSE error is usually the server finishing. Reconnecting forever
    // against a sync that has ended is a busy loop with extra steps.
    source.onerror = () => source.close();
    return () => source.close();
  },
};

export const runs = {
  list: (limit = 25) => apiFetch<AgentRun[]>(`/runs?limit=${String(limit)}`),
  read: (id: string) => apiFetch<AgentRunDetail>(`/runs/${id}`),
  budget: () => apiFetch<BudgetStanding>("/runs-budget"),
  /** The phase 5 demo: one run, inspectable end to end, with its cost. */
  hello: (threadId: string) =>
    apiFetch<AgentRunDetail>("/runs/hello", {
      method: "POST",
      body: JSON.stringify({ thread_id: threadId }),
    }),
};

export const overview = {
  read: () => apiFetch<Overview>("/overview"),
};

/**
 * Phase 8. The split matters: `read` never spends anything, `analyse` does.
 * Opening a thread is not a reason to pay for three agent runs, so the panel
 * reads first and asks only for what the read reported as missing.
 */
export const intelligence = {
  read: (threadId: string) => apiFetch<ThreadIntelligence>(`/threads/${threadId}/intelligence`),
  analyse: (
    threadId: string,
    capabilities: ("summary" | "deadlines" | "actions")[] = [],
    force = false,
  ) =>
    apiFetch<ThreadIntelligence>(`/threads/${threadId}/intelligence`, {
      method: "POST",
      body: JSON.stringify({ capabilities, force }),
    }),
};

export const tasks = {
  list: (filter: "all" | "today" | "upcoming" | "completed" = "all") =>
    apiFetch<TaskPage>(`/tasks?filter=${filter}`),
  /** Extracted action items that are not yet anyone's commitment. */
  suggestions: () => apiFetch<Suggestion[]>("/tasks-suggestions"),
  /** Deadlines the agent could not pin down. Rendered as questions. */
  ambiguous: () => apiFetch<AmbiguousDeadline[]>("/deadlines-ambiguous"),
  create: (body: {
    title: string;
    due_at?: string | null;
    notes?: string | null;
    thread_id?: string | null;
  }) => apiFetch<Task>("/tasks", { method: "POST", body: JSON.stringify(body) }),
  /** The moment a suggestion becomes a commitment. */
  confirm: (actionItemId: string) =>
    apiFetch<Task>(`/action-items/${actionItemId}/confirm`, { method: "POST" }),
  update: (
    id: string,
    body: {
      title?: string;
      status?: "pending" | "done" | "dismissed";
      due_at?: string | null;
      clear_due?: boolean;
      notes?: string | null;
      remind_at?: string | null;
    },
  ) => apiFetch<Task>(`/tasks/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  /** The user supplies the date; it stops being an estimate. */
  resolveDeadline: (deadlineId: string, chosenDate: string, wasWrong = false) =>
    apiFetch<{
      deadline_id: string;
      raw_phrase: string;
      normalized_date: string;
      resolution_status: string;
    }>(`/deadlines/${deadlineId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ chosen_date: chosenDate, was_wrong: wasWrong }),
    }),
};

export interface AskRouteInfo {
  route: string;
  label: string;
  costs_nothing: boolean;
}

export interface AskHandlers {
  onRoute?: (info: AskRouteInfo) => void;
  onDelta?: (text: string) => void;
  onDone?: (done: AskDone) => void;
  onFailed?: (message: string) => void;
}

export const companion = {
  conversations: () => apiFetch<Conversation[]>("/companion/conversations"),
  read: (id: string) => apiFetch<ConversationDetail>(`/companion/conversations/${id}`),
  create: (body: { title?: string | null; thread_id?: string | null } = {}) =>
    apiFetch<ConversationDetail>("/companion/conversations", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  remove: (id: string) => apiFetch<void>(`/companion/conversations/${id}`, { method: "DELETE" }),

  /**
   * Ask, and read the stream.
   *
   * `fetch` rather than `EventSource`, because the question travels as a POST
   * body and EventSource can only GET. Returns an abort function, so leaving
   * the page does not leave a reader running against a finished answer.
   */
  ask: (
    conversationId: string,
    question: string,
    handlers: AskHandlers,
    options: { regenerate?: boolean } = {},
  ): (() => void) => {
    const controller = new AbortController();

    void (async () => {
      try {
        const token = csrfToken();
        const response = await fetch(
          `${BASE_URL}/api/v1/companion/conversations/${conversationId}/ask`,
          {
            method: "POST",
            credentials: "include",
            signal: controller.signal,
            headers: {
              "Content-Type": "application/json",
              ...(token ? { [CSRF_HEADER]: token } : {}),
            },
            body: JSON.stringify({ question, regenerate: options.regenerate ?? false }),
          },
        );

        if (!response.ok || !response.body) {
          handlers.onFailed?.("Could not reach Maail.");
          return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // SSE frames are separated by a blank line. A partial frame stays
          // in the buffer rather than being parsed into nonsense.
          let split = buffer.indexOf("\n\n");
          while (split !== -1) {
            dispatch(buffer.slice(0, split), handlers);
            buffer = buffer.slice(split + 2);
            split = buffer.indexOf("\n\n");
          }
        }
      } catch (error) {
        if ((error as Error).name !== "AbortError") {
          handlers.onFailed?.("The connection dropped.");
        }
      }
    })();

    return () => controller.abort();
  },
};

function dispatch(frame: string, handlers: AskHandlers): void {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return;

  try {
    const payload = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
    if (event === "route") {
      handlers.onRoute?.({
        route: asText(payload.route),
        label: asText(payload.label),
        costs_nothing: payload.costs_nothing === true,
      });
    } else if (event === "delta") {
      handlers.onDelta?.(asText(payload.text));
    } else if (event === "done") {
      handlers.onDone?.(payload as unknown as AskDone);
    } else if (event === "failed") {
      handlers.onFailed?.(asText(payload.message) || "Something went wrong.");
    }
  } catch {
    /* a malformed frame is not worth tearing the stream down for */
  }
}

/**
 * A frame's field as text, or empty.
 *
 * `String(unknown)` would turn an object into "[object Object]" and put
 * that on screen. Anything that is not already a string is treated as
 * absent, which is the right reading of a frame that did not say what it
 * was supposed to say.
 */
function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export const memory = {
  facts: (includeRejected = false) =>
    apiFetch<Fact[]>(`/memory/facts?include_rejected=${String(includeRejected)}`),
  conflicts: () => apiFetch<MemoryConflict[]>("/memory/conflicts"),
  /** What the promoter refused. A run of these is an email trying to persist. */
  rejections: () => apiFetch<MemoryRejection[]>("/memory/rejections"),
  confirm: (id: string) => apiFetch<Fact>(`/memory/facts/${id}/confirm`, { method: "POST" }),
  reject: (id: string) => apiFetch<Fact>(`/memory/facts/${id}/reject`, { method: "POST" }),
  remove: (id: string) => apiFetch<void>(`/memory/facts/${id}`, { method: "DELETE" }),
  resolveConflict: (proposalId: string, keep: "stored" | "proposed") =>
    apiFetch<{ proposal_id: string; kept: string }>(
      `/memory/conflicts/${proposalId}/resolve?keep=${keep}`,
      { method: "POST" },
    ),
  state: (body: { fact_type: string; subject: string; content: string }) =>
    apiFetch<Fact>("/memory/facts", { method: "POST", body: JSON.stringify(body) }),
};

/**
 * Phase 11. Reads and writes rows; no model is involved at either end,
 * which is a blocking gate rather than an implementation detail.
 */
export const featureSettings = {
  read: () => apiFetch<FeatureSettings>("/settings"),
  /** Returns the whole configuration, because one toggle can move several. */
  set: (id: string, body: { enabled?: boolean; config?: Record<string, unknown> }) =>
    apiFetch<FeatureChange>(`/settings/features/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  preset: (id: string) => apiFetch<FeatureChange>(`/settings/presets/${id}`, { method: "POST" }),
  enableAll: () => apiFetch<FeatureChange>("/settings/features/enable-all", { method: "POST" }),
};
