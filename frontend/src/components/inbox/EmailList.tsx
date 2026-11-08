import { useVirtualizer } from "@tanstack/react-virtual";
import { Inbox } from "lucide-react";
import { useCallback, useEffect, useRef } from "react";

import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { Skeleton } from "@/components/common/Skeleton";
import { EmailRow } from "@/components/inbox/EmailRow";
import type { ThreadListItem } from "@/types/api";

/**
 * A virtualised list over cursor pages.
 *
 * Virtualised because a mailbox is tens of thousands of rows and the DOM is
 * not. Paged by cursor because OFFSET re-reads everything before the page
 * and double-counts rows when mail arrives mid-scroll — which is exactly
 * when someone is scrolling.
 *
 * The next page is requested before the scroll reaches the end, so the
 * fetch overlaps the scrolling instead of interrupting it.
 */
export interface EmailListProps {
  items: ThreadListItem[];
  selectedId: string | null;
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  error: string | null;
  syncing: boolean;
  onSelect: (id: string) => void;
  onCorrect?:
    ((id: string, field: "category" | "priority", value: string | number) => void) | undefined;
  onLoadMore: () => void;
  onRetry: () => void;
}

const ROW_HEIGHT = 92;
/** Fetch this many rows from the end, so the page lands before it is needed. */
const PREFETCH_ROWS = 10;

export function EmailList({
  items,
  selectedId,
  loading,
  loadingMore,
  hasMore,
  error,
  syncing,
  onSelect,
  onCorrect,
  onLoadMore,
  onRetry,
}: EmailListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
    getItemKey: (index) => items[index]?.id ?? index,
  });

  const virtualItems = virtualizer.getVirtualItems();
  const lastIndex = virtualItems.at(-1)?.index ?? 0;

  const maybeLoadMore = useCallback(() => {
    if (hasMore && !loadingMore && items.length > 0 && lastIndex >= items.length - PREFETCH_ROWS) {
      onLoadMore();
    }
  }, [hasMore, loadingMore, items.length, lastIndex, onLoadMore]);

  useEffect(maybeLoadMore, [maybeLoadMore]);

  if (error && items.length === 0) {
    return <ErrorState description={error} onRetry={onRetry} />;
  }

  if (loading && items.length === 0) {
    return (
      <div role="status" aria-busy="true" className="flex flex-col">
        <span className="sr-only">Loading your inbox</span>
        {Array.from({ length: 8 }, (_, index) => (
          <div key={index} className="flex gap-2 border-b border-line px-s2 py-2">
            <Skeleton className="size-8 rounded-pill" />
            <div className="flex-1">
              <Skeleton className="h-3.5 w-1/3" />
              <Skeleton className="mt-1.5 h-3 w-3/4" />
              <Skeleton className="mt-1.5 h-3 w-1/2" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return syncing ? (
      <EmptyState
        icon={Inbox}
        title="Your mail is on its way"
        description="Maail fetches the newest messages first, so this fills in as it goes."
      />
    ) : (
      <EmptyState
        icon={Inbox}
        title="Nothing here"
        description="No conversations match this view."
      />
    );
  }

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto" data-testid="email-list">
      <div style={{ height: virtualizer.getTotalSize(), position: "relative", width: "100%" }}>
        {virtualItems.map((virtualRow) => {
          const thread = items[virtualRow.index];
          if (!thread) return null;
          return (
            <div
              key={virtualRow.key}
              ref={virtualizer.measureElement}
              data-index={virtualRow.index}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              <EmailRow
                thread={thread}
                selected={thread.id === selectedId}
                onSelect={onSelect}
                onCorrect={onCorrect}
              />
            </div>
          );
        })}
      </div>
      {loadingMore ? (
        <div role="status" className="px-s2 py-2">
          <span className="sr-only">Loading more</span>
          <Skeleton className="h-3 w-24" />
        </div>
      ) : null}
    </div>
  );
}
