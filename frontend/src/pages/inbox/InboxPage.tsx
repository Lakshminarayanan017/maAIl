import { ArrowLeft, Inbox } from "lucide-react";
import { useEffect, useState } from "react";

import { EmptyState } from "@/components/common/EmptyState";
import { EmailList } from "@/components/inbox/EmailList";
import { InboxFilters } from "@/components/inbox/InboxFilters";
import { SyncProgress } from "@/components/inbox/SyncProgress";
import { ThreadPreview } from "@/components/thread/ThreadPreview";
import { Button } from "@/components/ui/button";
import { useIsDesktop } from "@/hooks/useMediaQuery";
import { useAccounts } from "@/stores/accounts";
import { useInbox } from "@/stores/inbox";

/**
 * Screen 04 — Smart Inbox (08-ui-spec.md §9), as far as phase 2 can take it.
 *
 *     Inbox                      │ Email preview
 *     Search emails...           │ Select an email
 *     [All] [Unread] ...         │
 *
 * Real mail, no intelligence. The AI category and priority slots on each
 * row are present and empty until the Triage agent exists.
 *
 * On a phone the two panes become one: a list, or a thread with a back
 * button. §8 forbids squeezing the desktop panes into a narrow column, and
 * a 40%-wide reading pane on a 375px screen is that squeeze.
 */
export function InboxPage() {
  // A rule the user could make so they never correct this sender again.
  // Offered once the same correction has happened twice; never applied.
  const [ruleSuggestion, setRuleSuggestion] = useState<string | null>(null);

  // The shell already loads accounts for the reconnect banner. Loading
  // them again here would mean two fetches per render and, because the
  // array identity changes each time, an effect that retriggers itself.
  const accounts = useAccounts((state) => state.items);

  const {
    items,
    selectedId,
    thread,
    threadLoading,
    threadError,
    loading,
    loadingMore,
    hasMore,
    error,
    filter,
    query,
    syncStatus,
    load,
    loadMore,
    select,
    setFilter,
    setQuery,
    correct,
    startSync,
    watchSync,
    refreshSyncStatus,
  } = useInbox();

  const isDesktop = useIsDesktop();
  const account = accounts.find((item) => item.status === "active");
  // The id, not the account object. Depending on the object reopens the
  // stream on every store update, because the array is rebuilt each fetch.
  const accountId = account?.id ?? null;

  useEffect(() => {
    void load();
  }, [load]);

  // One live status stream per connected account, torn down on unmount so a
  // navigation does not leave an open SSE connection behind.
  useEffect(() => {
    if (!accountId) return;
    void refreshSyncStatus(accountId);
    return watchSync(accountId);
  }, [accountId, watchSync, refreshSyncStatus]);

  if (accounts.length === 0 && !loading && items.length === 0) {
    return (
      <EmptyState
        icon={Inbox}
        title="No connected account"
        description="Connect Gmail in Settings and your mail appears here."
      />
    );
  }

  const syncing = Boolean(
    syncStatus && !["idle", "active", "error", "reauth_required"].includes(syncStatus.phase),
  );

  const list = (
    <div className="flex h-full min-w-0 flex-col border-r border-line">
      <InboxFilters
        active={filter}
        query={query}
        onFilter={(next) => void setFilter(next)}
        onQuery={(next) => void setQuery(next)}
      />
      <SyncProgress status={syncStatus} onResync={() => account && void startSync(account.id)} />
      {ruleSuggestion ? (
        <div
          role="status"
          className="flex items-start gap-2 border-b border-ai-border bg-ai px-s2 py-1.5 text-2xs text-ai-fg"
        >
          <span className="flex-1">{ruleSuggestion} Want a rule for it?</span>
          <button
            type="button"
            className="underline underline-offset-2"
            onClick={() => setRuleSuggestion(null)}
          >
            Not now
          </button>
        </div>
      ) : null}
      <div className="min-h-0 flex-1">
        <EmailList
          items={items}
          selectedId={selectedId}
          loading={loading}
          loadingMore={loadingMore}
          hasMore={hasMore}
          error={error}
          syncing={syncing}
          onSelect={(id) => void select(id)}
          onCorrect={(id, field, value) => {
            void correct(id, field, value).then((suggestion) => {
              if (suggestion) setRuleSuggestion(suggestion);
            });
          }}
          onLoadMore={() => void loadMore()}
          onRetry={() => void load()}
        />
      </div>
    </div>
  );

  const preview = (
    <ThreadPreview
      thread={thread}
      loading={threadLoading}
      error={threadError}
      onRetry={() => selectedId && void select(selectedId)}
    />
  );

  if (!isDesktop) {
    return selectedId ? (
      <div className="flex h-full flex-col">
        <div className="shrink-0 border-b border-line px-s2 py-1.5">
          <Button variant="ghost" size="sm" onClick={() => void select(null)}>
            <ArrowLeft aria-hidden />
            Inbox
          </Button>
        </div>
        <div className="min-h-0 flex-1">{preview}</div>
      </div>
    ) : (
      <div className="h-full">{list}</div>
    );
  }

  return (
    <div className="grid h-full grid-cols-[minmax(320px,2fr)_3fr]">
      {list}
      <div className="min-w-0">{preview}</div>
    </div>
  );
}

export default InboxPage;
