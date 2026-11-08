import { AlertTriangle, Ban, Loader2, Quote, Sparkles } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/common/Skeleton";
import { cn } from "@/lib/utils";

/**
 * The one component every AI-derived value renders through.
 *
 * > The user should always be able to distinguish: Information explicitly
 * > present in the email. AI-generated interpretations. Information
 * > retrieved from external integrations.
 * > (08-ui-spec.md, screen 05)
 *
 * Three rules it exists to enforce, none of which survive being left to
 * each screen's author:
 *
 * **Soft lavender means a model said it.** `#E8E2F5` is reserved for
 * AI-derived content and is applied here, so a fact lifted from the email
 * never wears it and an interpretation never goes without it.
 *
 * **No value renders without its provenance.** A value with no evidence
 * shows as "not determined" rather than as a bare claim. That is the
 * behaviour, not a guideline: `evidence` is required to render `ready`.
 *
 * **Status is per capability.** A summary that is ready and a deadline
 * that failed are two different states on one screen, and neither is
 * allowed to be represented by the other's absence.
 *
 * It exists before any agent on purpose. Added later, provenance becomes a
 * refactor of every screen that already shipped without it.
 */
export type AiStatus =
  | "not_applicable"
  | "pending"
  | "running"
  | "ready"
  | "failed"
  | "skipped_disabled"
  | "skipped_budget";

export type AiSource = "agent" | "user_rule" | "user_override" | "integration";

export interface Evidence {
  /** Which message the claim came from. */
  messageId: string;
  /** Character offsets into that message's text. */
  charStart: number;
  charEnd: number;
  /** The words themselves, when the caller already has them. */
  quote?: string;
}

export interface AiValueProps {
  /** What the agent concluded. Rendered only when `status` is "ready". */
  value: React.ReactNode;
  status: AiStatus;
  /** Required for a ready value. Without it the value does not render. */
  evidence?: Evidence[];
  source?: AiSource;
  label?: string;
  /** Shown instead of the value when a capability failed. */
  error?: string;
  onRetry?: () => void;
  className?: string;
}

const SOURCE_LABEL: Record<AiSource, string> = {
  agent: "Maail worked this out",
  user_rule: "From a rule you set",
  user_override: "You corrected this",
  integration: "From a connected service",
};

export function AiValue({
  value,
  status,
  evidence,
  source = "agent",
  label,
  error,
  onRetry,
  className,
}: AiValueProps) {
  const [showEvidence, setShowEvidence] = useState(false);

  if (status === "not_applicable") return null;

  if (status === "pending" || status === "running") {
    return (
      <span
        role="status"
        aria-busy="true"
        className={cn("inline-flex items-center gap-1.5", className)}
      >
        <Loader2 className="size-3 shrink-0 animate-spin text-violet" aria-hidden />
        <span className="text-2xs text-fg-subtle">
          {label ? `${label}: analysing` : "Analysing"}
        </span>
      </span>
    );
  }

  if (status === "skipped_disabled" || status === "skipped_budget") {
    return (
      <span className={cn("inline-flex items-center gap-1.5", className)}>
        <Ban className="size-3 shrink-0 text-fg-subtle" aria-hidden />
        <span className="text-2xs text-fg-subtle">
          {status === "skipped_disabled"
            ? "Turned off in settings"
            : "Skipped — monthly budget reached"}
        </span>
      </span>
    );
  }

  if (status === "failed") {
    return (
      <span role="alert" className={cn("inline-flex items-center gap-1.5", className)}>
        <AlertTriangle className="size-3 shrink-0 text-danger-fg" aria-hidden />
        <span className="text-2xs text-danger-fg">{error || "Could not work this out"}</span>
        {onRetry ? (
          <Button size="sm" variant="ghost" className="h-5 px-1 text-2xs" onClick={onRetry}>
            Try again
          </Button>
        ) : null}
      </span>
    );
  }

  const hasEvidence = Boolean(evidence && evidence.length > 0);

  // A value with nothing behind it is not shown as a value. This is the
  // whole point of the component: an unsourced claim renders as an
  // absence, never as an answer.
  if (!hasEvidence) {
    return (
      <span className={cn("inline-flex items-center gap-1.5", className)}>
        <span className="text-2xs text-fg-subtle">Not determined</span>
      </span>
    );
  }

  return (
    <span className={cn("inline-flex flex-col items-start gap-1", className)}>
      <span className="inline-flex items-center gap-1">
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded-sm border border-ai-border",
            "bg-ai px-1.5 py-0.5 text-ai-fg",
          )}
        >
          <Sparkles className="size-3 shrink-0" aria-hidden />
          <span className="text-sm">{value}</span>
        </span>

        <Button
          size="sm"
          variant="ghost"
          className="h-5 px-1 text-2xs"
          aria-expanded={showEvidence}
          onClick={() => setShowEvidence((previous) => !previous)}
        >
          <Quote aria-hidden className="size-3" />
          {showEvidence ? "Hide source" : "Source"}
        </Button>
      </span>

      {showEvidence ? (
        <span className="flex flex-col gap-1 rounded-sm border border-line bg-surface-sunken p-1.5">
          <span className="text-2xs text-fg-subtle">{SOURCE_LABEL[source]}</span>
          {evidence?.map((item) => (
            <span
              key={`${item.messageId}-${item.charStart}`}
              className="border-l-2 border-ai-border pl-1.5 text-2xs text-fg-muted"
            >
              {item.quote ? (
                <q className="italic">{item.quote}</q>
              ) : (
                <span className="font-mono">
                  message {item.messageId.slice(0, 8)} · characters {item.charStart}–{item.charEnd}
                </span>
              )}
            </span>
          ))}
        </span>
      ) : null}
    </span>
  );
}

/**
 * The per-capability chip. Small enough for an email row, explicit enough
 * that an empty slot never has to be interpreted.
 */
export function CapabilityChip({
  capability,
  status,
  className,
}: {
  capability: string;
  status: AiStatus;
  className?: string;
}) {
  const style: Record<AiStatus, string> = {
    not_applicable: "border-line bg-surface-sunken text-fg-subtle",
    pending: "border-line bg-surface-sunken text-fg-subtle",
    running: "border-ai-border bg-ai text-ai-fg",
    ready: "border-success-border bg-success text-success-fg",
    failed: "border-danger-border bg-danger text-danger-fg",
    skipped_disabled: "border-line bg-surface-sunken text-fg-subtle",
    skipped_budget: "border-warning-border bg-warning text-warning-fg",
  };
  const text: Record<AiStatus, string> = {
    not_applicable: "n/a",
    pending: "queued",
    running: "analysing",
    ready: "ready",
    failed: "failed",
    skipped_disabled: "off",
    skipped_budget: "budget",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-pill border px-1.5 py-0.5 text-2xs",
        style[status],
        className,
      )}
      title={`${capability}: ${text[status]}`}
    >
      {status === "running" ? <Loader2 className="size-2.5 animate-spin" aria-hidden /> : null}
      {capability} · {text[status]}
    </span>
  );
}

/** The shapes an intelligence block takes while it is being worked out. */
export function AiBlockSkeleton({
  kind = "summary",
}: {
  kind?: "summary" | "deadline" | "actions";
}) {
  const lines = kind === "summary" ? 3 : kind === "actions" ? 2 : 1;
  return (
    <div role="status" aria-busy="true" className="flex flex-col gap-1.5">
      <span className="sr-only">Working out the {kind}</span>
      <Skeleton className="h-2.5 w-20" />
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton
          key={index}
          className="h-3"
          style={{ width: index === lines - 1 ? "60%" : "100%" }}
        />
      ))}
    </div>
  );
}
