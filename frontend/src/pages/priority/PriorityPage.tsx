import { Star } from "lucide-react";
import { useEffect } from "react";

import { EmptyState } from "@/components/common/EmptyState";
import { EmailList } from "@/components/inbox/EmailList";
import { useInbox } from "@/stores/inbox";

/**
 * Priority as its own route, which phase 6 asks for.
 *
 * It is the inbox with the `important` filter and nothing else: the same
 * list, the same corrections, the same cursor paging. A second
 * implementation would be a second thing to keep in step for no gain.
 */
export function PriorityPage() {
  const {
    items,
    selectedId,
    loading,
    loadingMore,
    hasMore,
    error,
    load,
    loadMore,
    select,
    correct,
    setFilter,
  } = useInbox();

  useEffect(() => {
    void setFilter("important");
  }, [setFilter]);

  if (!loading && items.length === 0) {
    return (
      <EmptyState
        icon={Star}
        title="Nothing is waiting on you"
        description="Threads Maail judges important enough to need you appear here, each with its reason."
      />
    );
  }

  return (
    <div className="h-full">
      <EmailList
        items={items}
        selectedId={selectedId}
        loading={loading}
        loadingMore={loadingMore}
        hasMore={hasMore}
        error={error}
        syncing={false}
        onSelect={(id) => void select(id)}
        onCorrect={(id, field, value) => void correct(id, field, value)}
        onLoadMore={() => void loadMore()}
        onRetry={() => void load()}
      />
    </div>
  );
}

export default PriorityPage;
