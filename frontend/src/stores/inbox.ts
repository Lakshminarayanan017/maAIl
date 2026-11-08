import { create } from "zustand";

import { sync as syncApi, threads as threadsApi } from "@/services/api";
import type { SyncStatus, ThreadDetail, ThreadFilter, ThreadListItem } from "@/types/api";

/**
 * The inbox: a cursor-paged list, a selection, and the sync behind both.
 *
 * Pages append rather than replace, because the list is virtualised over
 * everything loaded so far and a replace would jump the scroll position to
 * the top mid-read.
 *
 * `loadingMore` is separate from `loading` for the same reason the session
 * store has three states: a spinner over the whole list while page 4 loads
 * would hide the mail someone is reading.
 */
interface InboxState {
  items: ThreadListItem[];
  cursor: string | null;
  hasMore: boolean;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;

  filter: ThreadFilter;
  query: string;

  selectedId: string | null;
  thread: ThreadDetail | null;
  threadLoading: boolean;
  threadError: string | null;

  syncStatus: SyncStatus | null;

  load: (options?: { reset?: boolean }) => Promise<void>;
  loadMore: () => Promise<void>;
  setFilter: (filter: ThreadFilter) => Promise<void>;
  setQuery: (query: string) => Promise<void>;
  select: (id: string | null) => Promise<void>;
  correct: (
    id: string,
    field: "category" | "priority",
    value: string | number,
  ) => Promise<string | null>;
  startSync: (accountId: string, full?: boolean) => Promise<void>;
  watchSync: (accountId: string) => () => void;
  refreshSyncStatus: (accountId: string) => Promise<void>;
}

const PAGE_SIZE = 50;

function message(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export const useInbox = create<InboxState>((set, get) => ({
  items: [],
  cursor: null,
  hasMore: true,
  loading: false,
  loadingMore: false,
  error: null,

  filter: "all",
  query: "",

  selectedId: null,
  thread: null,
  threadLoading: false,
  threadError: null,

  syncStatus: null,

  load: async ({ reset = true } = {}) => {
    set({ loading: true, error: null });
    try {
      const page = await threadsApi.list({
        limit: PAGE_SIZE,
        filter: get().filter,
        q: get().query || null,
      });
      set({
        items: page.items,
        cursor: page.next_cursor,
        hasMore: page.next_cursor !== null,
        loading: false,
      });
      if (reset && page.items.length > 0 && get().selectedId === null) {
        // Nothing is auto-opened. Marking a thread read because the list
        // happened to render is a read receipt nobody asked for.
      }
    } catch (error) {
      set({ loading: false, error: message(error, "Could not load your inbox") });
    }
  },

  loadMore: async () => {
    const { cursor, hasMore, loadingMore, loading, items } = get();
    if (!hasMore || !cursor || loadingMore || loading) return;

    set({ loadingMore: true });
    try {
      const page = await threadsApi.list({
        cursor,
        limit: PAGE_SIZE,
        filter: get().filter,
        q: get().query || null,
      });
      // De-duplicate on append: mail arriving mid-scroll can push a thread
      // onto a page that already showed it.
      const seen = new Set(items.map((item) => item.id));
      set({
        items: [...items, ...page.items.filter((item) => !seen.has(item.id))],
        cursor: page.next_cursor,
        hasMore: page.next_cursor !== null,
        loadingMore: false,
      });
    } catch (error) {
      set({ loadingMore: false, error: message(error, "Could not load more") });
    }
  },

  setFilter: async (filter) => {
    set({ filter, items: [], cursor: null, hasMore: true });
    await get().load();
  },

  setQuery: async (query) => {
    set({ query, items: [], cursor: null, hasMore: true });
    await get().load();
  },

  select: async (id) => {
    if (id === null) {
      set({ selectedId: null, thread: null, threadError: null });
      return;
    }
    set({ selectedId: id, threadLoading: true, threadError: null });
    try {
      const thread = await threadsApi.read(id);
      set({ thread, threadLoading: false });

      if (thread.unread_count > 0) {
        // Optimistic: the row stops shouting immediately, and the next
        // delta sync reconciles against Gmail, which wins.
        set({
          items: get().items.map((item) =>
            item.id === id ? { ...item, unread_count: 0, is_read: true } : item,
          ),
        });
        void threadsApi.setRead(id, true).catch(() => undefined);
      }
    } catch (error) {
      set({ threadLoading: false, threadError: message(error, "Could not open that thread") });
    }
  },

  correct: async (id, field, value) => {
    // Optimistic, and marked as a correction immediately: once a person
    // has decided, the badge must stop looking like an estimate.
    set({
      items: get().items.map((item) =>
        item.id === id
          ? {
              ...item,
              ...(field === "category"
                ? {
                    category: value as ThreadListItem["category"],
                    category_source: "user_override",
                  }
                : { priority: Number(value), priority_reason: "You set this" }),
            }
          : item,
      ),
    });
    try {
      const response = await threadsApi.override(id, field, value);
      return response.suggested_rule?.because ?? null;
    } catch {
      // Put it back rather than leaving a correction that did not save.
      await get().load({ reset: false });
      return null;
    }
  },

  startSync: async (accountId, full = false) => {
    try {
      await syncApi.trigger(accountId, full);
    } catch (error) {
      set({ error: message(error, "Could not start the sync") });
    }
  },

  refreshSyncStatus: async (accountId) => {
    try {
      set({ syncStatus: await syncApi.status(accountId) });
    } catch {
      /* the status is a nicety; failing to read it is not an inbox error */
    }
  },

  watchSync: (accountId) => {
    let lastThreadCount = get().syncStatus?.threads ?? -1;
    return syncApi.watch(accountId, (status) => {
      set({ syncStatus: status });
      // Reload only when the sync has actually produced threads. Refetching
      // fifty rows on every tick while someone is scrolling is its own kind
      // of broken, and "active" alone would fire on a no-op sync.
      if (status.threads !== lastThreadCount) {
        lastThreadCount = status.threads;
        void get().load({ reset: false });
      }
    });
  },
}));
