import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";
import type * as React from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  /** One sentence. What is absent, and what would put something here. */
  description?: string;
  action?: { label: string; onClick: () => void };
  /** A secondary route out, when doing nothing is also reasonable. */
  secondaryAction?: { label: string; onClick: () => void };
  className?: string;
  children?: React.ReactNode;
}

/**
 * Clear empty states (08-ui-spec.md §4). An empty state says what is not here
 * and what would change that. It never apologises and never shows a sample row
 * to fill the space.
 */
export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  secondaryAction,
  className,
  children,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-s2 px-s3 py-s6 text-center",
        className,
      )}
    >
      <span className="flex size-12 items-center justify-center rounded-md border border-line bg-surface-sunken text-fg-subtle">
        <Icon className="size-5" aria-hidden />
      </span>
      <div className="flex max-w-sm flex-col gap-1">
        <h3 className="font-brand text-lg font-semibold text-fg">{title}</h3>
        {description ? <p className="text-base text-fg-muted">{description}</p> : null}
      </div>
      {children}
      {action || secondaryAction ? (
        <div className="flex items-center gap-s1">
          {action ? (
            <Button size="sm" onClick={action.onClick}>
              {action.label}
            </Button>
          ) : null}
          {secondaryAction ? (
            <Button size="sm" variant="ghost" onClick={secondaryAction.onClick}>
              {secondaryAction.label}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
