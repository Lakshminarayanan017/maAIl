import { Paperclip } from "lucide-react";

import { ClassificationBadges } from "@/components/inbox/ClassificationBadges";
import { cn, initials } from "@/lib/utils";
import type { ThreadListItem } from "@/types/api";

/**
 * One row of the inbox (08-ui-spec.md, screen 04).
 *
 * > Every email row displays: sender avatar and name · subject · short
 * > preview · received timestamp · **AI category** · **priority indicator** ·
 * > attachment indicator when applicable.
 *
 * The AI slots are rendered and empty rather than omitted. Two reasons: the
 * row's layout does not shift when phase 6 fills them, and "not analysed
 * yet" is a true statement where a missing slot would quietly imply the
 * thread had been looked at and found unremarkable.
 */
export interface EmailRowProps {
  thread: ThreadListItem;
  selected: boolean;
  onSelect: (id: string) => void;
  onCorrect?:
    ((id: string, field: "category" | "priority", value: string | number) => void) | undefined;
}

function displayName(thread: ThreadListItem): string {
  return thread.sender.name || thread.sender.email || "Unknown sender";
}

function timestamp(value: string | null): string {
  if (!value) return "";
  const sent = new Date(value);
  const now = new Date();
  const sameDay = sent.toDateString() === now.toDateString();
  if (sameDay) {
    return sent.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  }
  const sameYear = sent.getFullYear() === now.getFullYear();
  return sent.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

export function EmailRow({ thread, selected, onSelect, onCorrect }: EmailRowProps) {
  const unread = thread.unread_count > 0;

  return (
    // A div with a button role, not a <button>. The correction control is
    // itself a button, and a button inside a button is invalid HTML that
    // the browser silently restructures -- which is how the correction
    // menu stopped being reachable at all.
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(thread.id)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(thread.id);
        }
      }}
      aria-current={selected ? "true" : undefined}
      className={cn(
        "flex w-full items-start gap-2 border-b border-line px-s2 py-2 text-left",
        "transition-colors focus-visible:outline-none focus-visible:ring-2",
        "focus-visible:ring-inset focus-visible:ring-ring",
        selected ? "bg-violet-subtle" : "hover:bg-surface-sunken",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-pill",
          "border border-line bg-surface-sunken text-2xs font-semibold text-fg-muted",
        )}
      >
        {initials(displayName(thread))}
      </span>

      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span
            className={cn(
              "min-w-0 flex-1 truncate text-base",
              unread ? "font-semibold text-fg" : "text-fg-muted",
            )}
          >
            {displayName(thread)}
          </span>
          {thread.message_count > 1 ? (
            <span className="shrink-0 text-2xs text-fg-subtle">{thread.message_count}</span>
          ) : null}
          <span className="shrink-0 text-2xs tabular-nums text-fg-subtle">
            {timestamp(thread.latest_message_at)}
          </span>
        </span>

        <span className="flex items-center gap-1.5">
          <span
            className={cn(
              "min-w-0 flex-1 truncate text-sm",
              unread ? "font-medium text-fg" : "text-fg-muted",
            )}
          >
            {thread.subject || "(no subject)"}
          </span>
          {thread.has_attachments ? (
            <Paperclip className="size-3 shrink-0 text-fg-subtle" aria-label="Has attachments" />
          ) : null}
        </span>

        <span className="block truncate text-sm text-fg-subtle">{thread.preview || ""}</span>

        {/*
          The AI slots, now populated. Soft lavender marks a judgement; a
          correction the user made is a different colour, because once a
          person has decided it must stop looking like an estimate.
        */}
        <span className="mt-1 flex items-center gap-1">
          <ClassificationBadges
            thread={thread}
            onCorrect={onCorrect ? (field, value) => onCorrect(thread.id, field, value) : undefined}
          />
        </span>
      </span>

      {unread ? (
        <span aria-label="Unread" className="mt-2 size-2 shrink-0 rounded-pill bg-violet" />
      ) : null}
    </div>
  );
}
