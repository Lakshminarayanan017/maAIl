import { Check, Pencil, Sparkles } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { ThreadCategory, ThreadListItem } from "@/types/api";

/**
 * The classification badges on an email row (08-ui-spec.md, screen 04).
 *
 * > AI classification badges: `High priority` · `Technical` ·
 * > `AI classified`.
 *
 * Soft lavender on all three, because all three are a model's judgement
 * rather than something the email said. A correction turns the badge a
 * different colour on purpose: once a person has decided, it stops being
 * an estimate and must stop looking like one.
 *
 * `priority_reason` is attached to the priority badge as a tooltip, so
 * there is never an unexplained badge on the screen.
 */
const CATEGORIES: { value: ThreadCategory; label: string }[] = [
  { value: "technical", label: "Technical" },
  { value: "opportunity", label: "Opportunity" },
  { value: "academic", label: "Academic" },
  { value: "administrative", label: "Administrative" },
  { value: "personal", label: "Personal" },
  { value: "promotional", label: "Promotional" },
  { value: "notification", label: "Notification" },
  { value: "other", label: "Other" },
];

const PRIORITY_LABEL: Record<number, string> = {
  3: "High priority",
  2: "Needs attention",
  1: "Normal",
  0: "Low",
};

function Chip({
  children,
  tone = "ai",
  title,
}: {
  children: React.ReactNode;
  tone?: "ai" | "user" | "neutral";
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-pill border px-1.5 py-0.5 text-2xs",
        tone === "ai" && "border-ai-border bg-ai text-ai-fg",
        tone === "user" && "border-violet/30 bg-violet-subtle text-violet",
        tone === "neutral" && "border-line bg-surface-sunken text-fg-muted",
      )}
    >
      {children}
    </span>
  );
}

export interface ClassificationBadgesProps {
  thread: ThreadListItem;
  onCorrect?: ((field: "category" | "priority", value: string | number) => void) | undefined;
  compact?: boolean | undefined;
}

export function ClassificationBadges({
  thread,
  onCorrect,
  compact = false,
}: ClassificationBadgesProps) {
  const [open, setOpen] = useState(false);
  const corrected = thread.category_source === "user_override";
  const byRule = thread.category_source === "user_rule";

  const analysing =
    thread.category === null &&
    (thread.status_summary === "pending" || thread.status_summary === "running");

  if (analysing) {
    return (
      <span className="inline-flex items-center gap-1" data-testid="ai-slots">
        <Chip tone="neutral">Analysing</Chip>
      </span>
    );
  }

  if (thread.category === null) {
    return (
      <span className="inline-flex items-center gap-1" data-testid="ai-slots">
        <Chip tone="neutral">Not analysed</Chip>
      </span>
    );
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-1" data-testid="ai-slots">
      {thread.priority !== null && thread.priority >= 2 ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <span>
              <Chip tone={corrected ? "user" : "ai"}>
                {PRIORITY_LABEL[thread.priority] ?? "Priority"}
              </Chip>
            </span>
          </TooltipTrigger>
          {/* Never an unexplained badge. */}
          <TooltipContent>
            {thread.priority_reason || "No reason was recorded for this."}
          </TooltipContent>
        </Tooltip>
      ) : null}

      {thread.is_technical ? <Chip tone={corrected ? "user" : "ai"}>Technical</Chip> : null}

      <Chip tone={corrected ? "user" : byRule ? "neutral" : "ai"}>
        {corrected ? (
          <>
            <Check className="size-2.5" aria-hidden />
            You filed this
          </>
        ) : byRule ? (
          "Your rule"
        ) : (
          <>
            <Sparkles className="size-2.5" aria-hidden />
            AI classified
          </>
        )}
      </Chip>

      {thread.stale ? (
        <Chip tone="neutral" title="New mail has arrived since this was worked out">
          Out of date
        </Chip>
      ) : null}

      {onCorrect && !compact ? (
        <DropdownMenu open={open} onOpenChange={setOpen}>
          <DropdownMenuTrigger asChild>
            <Button
              size="icon-sm"
              variant="ghost"
              className="size-5"
              aria-label="Correct this classification"
              // Radix opens on pointer-down, so stopping only the click
              // lets the row's own handler select the thread underneath.
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => event.stopPropagation()}
            >
              <Pencil className="size-3" aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" onClick={(event) => event.stopPropagation()}>
            <DropdownMenuLabel>File this as</DropdownMenuLabel>
            {CATEGORIES.map((option) => (
              <DropdownMenuItem
                key={option.value}
                onSelect={() => onCorrect("category", option.value)}
              >
                {option.value === thread.category ? (
                  <Check className="size-3 text-violet" aria-hidden />
                ) : (
                  <span className="size-3" />
                )}
                {option.label}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Priority</DropdownMenuLabel>
            {[3, 2, 1, 0].map((level) => (
              <DropdownMenuItem key={level} onSelect={() => onCorrect("priority", level)}>
                {level === thread.priority ? (
                  <Check className="size-3 text-violet" aria-hidden />
                ) : (
                  <span className="size-3" />
                )}
                {PRIORITY_LABEL[level]}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </span>
  );
}
