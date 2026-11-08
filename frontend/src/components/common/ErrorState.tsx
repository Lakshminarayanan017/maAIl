import { AlertTriangle, RotateCcw } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface ErrorStateProps {
  title?: string;
  /** What failed, in the user's terms. Not a stack trace. */
  description?: string;
  /** The correlation id from the X-Request-ID header, when there is one. */
  requestId?: string;
  onRetry?: () => void;
  className?: string;
}

/**
 * Clear error states (08-ui-spec.md §4).
 *
 * Two rules. It says what failed rather than that something failed, and it
 * surfaces the request id, because "it broke" with a correlation id is a
 * support ticket somebody can actually answer.
 */
export function ErrorState({
  title = "Something went wrong",
  description = "We could not load this. It is usually temporary.",
  requestId,
  onRetry,
  className,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center gap-s2 px-s3 py-s6 text-center",
        className,
      )}
    >
      <span className="flex size-12 items-center justify-center rounded-md border border-danger-border bg-danger text-danger-fg">
        <AlertTriangle className="size-5" aria-hidden />
      </span>
      <div className="flex max-w-sm flex-col gap-1">
        <h3 className="font-brand text-lg font-semibold text-fg">{title}</h3>
        <p className="text-base text-fg-muted">{description}</p>
      </div>
      {onRetry ? (
        <Button size="sm" variant="secondary" onClick={onRetry}>
          <RotateCcw aria-hidden />
          Try again
        </Button>
      ) : null}
      {requestId ? (
        <p className="font-mono text-2xs text-fg-subtle">
          reference <span className="select-all">{requestId}</span>
        </p>
      ) : null}
    </div>
  );
}

interface BoundaryState {
  error: Error | null;
}

/**
 * The last line of defence. A render crash shows this instead of a white page,
 * which is the difference between a bug and a product that looks broken.
 */
export class ErrorBoundary extends React.Component<
  { children: React.ReactNode; fallback?: React.ReactNode },
  BoundaryState
> {
  override state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error): void {
    // Phase 4 ships the client error sink. Until then the console is the sink,
    // and silently swallowing a crash would be worse.
    console.error("render failed", error);
  }

  override render(): React.ReactNode {
    if (this.state.error) {
      return (
        this.props.fallback ?? (
          <ErrorState
            title="This view crashed"
            description={this.state.error.message}
            onRetry={() => this.setState({ error: null })}
          />
        )
      );
    }
    return this.props.children;
  }
}
