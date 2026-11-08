import { Search } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ThreadFilter } from "@/types/api";

/**
 * The filter row from screen 04 (08-ui-spec.md §9).
 *
 * > Filters: All emails · Unread · Important · Technical · Opportunities ·
 * > Team communication · Notifications · Archived
 *
 * All eight are shown, because the set is locked. The five that depend on
 * classification are disabled and say why. The alternative — enabling them
 * now — would return an empty list and read as "you have no technical
 * email", which is a lie told by omission.
 */
interface FilterSpec {
  id: string;
  label: string;
  value: ThreadFilter;
}

/**
 * All eight, exactly as the spec lists them, and all eight live. The five
 * that read a classification answer from a stored judgement -- a SQL
 * predicate over a column, not a model call.
 */
const FILTERS: FilterSpec[] = [
  { id: "all", label: "All emails", value: "all" },
  { id: "unread", label: "Unread", value: "unread" },
  { id: "important", label: "Important", value: "important" },
  { id: "technical", label: "Technical", value: "technical" },
  { id: "opportunities", label: "Opportunities", value: "opportunities" },
  { id: "team", label: "Team communication", value: "team" },
  { id: "notifications", label: "Notifications", value: "notifications" },
  { id: "archived", label: "Archived", value: "archived" },
];

export interface InboxFiltersProps {
  active: ThreadFilter;
  query: string;
  onFilter: (filter: ThreadFilter) => void;
  onQuery: (query: string) => void;
}

export function InboxFilters({ active, query, onFilter, onQuery }: InboxFiltersProps) {
  const [draft, setDraft] = useState(query);

  // Debounced, because every keystroke is a full-text query against the
  // whole mailbox.
  useEffect(() => {
    if (draft === query) return;
    const timer = setTimeout(() => onQuery(draft), 250);
    return () => clearTimeout(timer);
  }, [draft, query, onQuery]);

  return (
    <div className="flex flex-col gap-2 border-b border-line px-s2 py-2">
      <label className="relative flex items-center">
        <Search
          className="pointer-events-none absolute left-2 size-3.5 text-fg-subtle"
          aria-hidden
        />
        <span className="sr-only">Search emails</span>
        <input
          type="search"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Search emails..."
          className={cn(
            "w-full rounded-sm border border-line bg-surface py-1.5 pl-7 pr-2 text-base",
            "text-fg placeholder:text-fg-subtle",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          )}
        />
      </label>

      <div className="flex flex-wrap gap-1" role="group" aria-label="Filters">
        {FILTERS.map((filter) => (
          <Button
            key={filter.id}
            size="sm"
            variant={active === filter.value ? "subtle" : "ghost"}
            aria-pressed={active === filter.value}
            onClick={() => onFilter(filter.value)}
            className="h-7 rounded-pill px-2.5 text-sm"
          >
            {filter.label}
          </Button>
        ))}
      </div>
    </div>
  );
}
