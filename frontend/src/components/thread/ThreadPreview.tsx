import { Archive, Forward, Mail, Paperclip, Reply } from "lucide-react";

import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { Skeleton, SkeletonText } from "@/components/common/Skeleton";
import { MessageBody } from "@/components/thread/MessageBody";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn, initials } from "@/lib/utils";
import type { Message, ThreadDetail } from "@/types/api";

/**
 * Screen 05, left pane: the reading experience.
 *
 *     Email
 *     Subject: CI pipeline failed
 *     From: GitHub Actions
 *     Date: 10:30 AM
 *
 *     Message body
 *
 *     [Reply] [Forward] [Archive]
 *
 * All three actions are shown and all three are disabled, each saying why.
 * Reply and Forward need a send authorisation v1 deliberately does not
 * hold; Archive needs `gmail.modify`, which screen 02 promised not to ask
 * for. Hiding them would make the screen look finished when it is not;
 * enabling them would break a promise made on the connect screen.
 */
export interface ThreadPreviewProps {
  thread: ThreadDetail | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}

function senderLabel(message: Message): string {
  return message.from_name || message.from_email || "Unknown sender";
}

function when(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

const PENDING_ACTIONS = [
  {
    icon: Reply,
    label: "Reply",
    why: "Sending needs its own authorisation, which Maail asks for separately. Phase 12.",
  },
  {
    icon: Forward,
    label: "Forward",
    why: "Sending needs its own authorisation, which Maail asks for separately. Phase 12.",
  },
  {
    icon: Archive,
    label: "Archive",
    why: "Changing your mailbox needs a write scope v1 does not request.",
  },
] as const;

function MessageBlock({ threadId, message }: { threadId: string; message: Message }) {
  return (
    <article className="px-s3 py-s2">
      <header className="flex items-start gap-2">
        <span
          aria-hidden
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-pill text-2xs font-semibold",
            message.is_from_user
              ? "bg-violet-subtle text-violet"
              : "border border-line bg-surface-sunken text-fg-muted",
          )}
        >
          {initials(senderLabel(message))}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-base font-medium text-fg">
            {senderLabel(message)}
            {message.is_from_user ? (
              <span className="ml-1.5 text-2xs font-normal text-fg-subtle">you</span>
            ) : null}
          </p>
          <p className="truncate text-2xs text-fg-subtle">
            to {message.to_emails.join(", ") || "undisclosed recipients"}
          </p>
        </div>
        <time className="shrink-0 text-2xs text-fg-subtle" dateTime={message.sent_at}>
          {when(message.sent_at)}
        </time>
      </header>

      <MessageBody threadId={threadId} message={message} />

      {message.attachments.length > 0 ? (
        <ul className="mt-s2 flex flex-wrap gap-1.5">
          {message.attachments.map((attachment) => (
            <li
              key={attachment.id}
              className="flex items-center gap-1 rounded-sm border border-line bg-surface-sunken px-2 py-1 text-2xs text-fg-muted"
            >
              <Paperclip className="size-3" aria-hidden />
              {attachment.filename || "attachment"}
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

export function ThreadPreview({ thread, loading, error, onRetry }: ThreadPreviewProps) {
  if (error) {
    return <ErrorState title="Could not open that thread" description={error} onRetry={onRetry} />;
  }

  if (loading) {
    return (
      <div role="status" aria-busy="true" className="px-s3 py-s3">
        <span className="sr-only">Opening</span>
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="mt-s2 h-3 w-1/3" />
        <SkeletonText className="mt-s3" lines={6} />
      </div>
    );
  }

  if (!thread) {
    return (
      <EmptyState
        icon={Mail}
        title="Select an email"
        description="Pick a conversation on the left to read it here."
      />
    );
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <header className="shrink-0 border-b border-line px-s3 py-s2">
        <h2 className="font-brand text-lg font-semibold text-fg">
          {thread.subject || "(no subject)"}
        </h2>
        <p className="mt-0.5 text-sm text-fg-muted">
          {thread.message_count} message{thread.message_count === 1 ? "" : "s"}
          {thread.participants.length > 0 ? ` · ${thread.participants.slice(0, 3).join(", ")}` : ""}
          {thread.participants.length > 3 ? ` +${thread.participants.length - 3}` : ""}
        </p>

        <div className="mt-s2 flex flex-wrap gap-1">
          {PENDING_ACTIONS.map(({ icon: Icon, label, why }) => (
            <Tooltip key={label}>
              <TooltipTrigger asChild>
                <span>
                  <Button size="sm" variant="secondary" disabled>
                    <Icon aria-hidden />
                    {label}
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent>{why}</TooltipContent>
            </Tooltip>
          ))}
        </div>
      </header>

      <div className="flex-1">
        {thread.messages.map((message, index) => (
          <div key={message.id}>
            {index > 0 ? <Separator /> : null}
            <MessageBlock threadId={thread.id} message={message} />
          </div>
        ))}
      </div>
    </div>
  );
}
