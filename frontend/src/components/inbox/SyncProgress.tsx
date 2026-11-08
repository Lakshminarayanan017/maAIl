import { AlertTriangle, Check, Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { SyncStatus } from "@/types/api";

/**
 * Visible sync progress, which the cold-start rule requires: the newest
 * messages arrive first and the inbox is never blank while syncing, so
 * something has to say that more is still coming.
 *
 * The total is Gmail's own estimate and is labelled "about", because a
 * progress bar that reaches 100% and keeps going is worse than one that
 * admits it is guessing.
 */
const LABEL: Record<SyncStatus["phase"], string> = {
  idle: "Up to date",
  starting: "Starting",
  connecting: "Connecting to Gmail",
  initial_metadata: "Fetching your mail",
  initial_bodies: "Fetching message bodies",
  delta: "Checking for new mail",
  reconciling: "Catching up",
  active: "Up to date",
  error: "Sync problem",
  reauth_required: "Needs reconnecting",
};

export interface SyncProgressProps {
  status: SyncStatus | null;
  onResync: () => void;
}

export function SyncProgress({ status, onResync }: SyncProgressProps) {
  if (!status) return null;

  const running = !["idle", "active", "error", "reauth_required"].includes(status.phase);
  const percent =
    status.total && status.total > 0
      ? Math.min(100, Math.round((status.done / status.total) * 100))
      : null;

  return (
    <div className="flex items-center gap-2 border-b border-line px-s2 py-1.5 text-sm">
      {running ? (
        <Loader2 className="size-3.5 shrink-0 animate-spin text-violet" aria-hidden />
      ) : status.phase === "error" ? (
        <AlertTriangle className="size-3.5 shrink-0 text-danger-fg" aria-hidden />
      ) : (
        <Check className="size-3.5 shrink-0 text-success-fg" aria-hidden />
      )}

      <span className="min-w-0 flex-1 truncate text-fg-muted" role="status" aria-live="polite">
        {LABEL[status.phase]}
        {running && status.done > 0 ? (
          <>
            {" — "}
            <span className="tabular-nums">{status.done.toLocaleString()}</span>
            {status.total ? (
              <span className="text-fg-subtle"> of about {status.total.toLocaleString()}</span>
            ) : null}
          </>
        ) : null}
        {status.phase === "error" && status.error ? (
          <span className="text-danger-fg"> — {status.error}</span>
        ) : null}
      </span>

      {percent !== null && running ? (
        <span
          className="h-1 w-24 shrink-0 overflow-hidden rounded-pill bg-surface-sunken"
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <span
            className={cn("block h-full bg-violet transition-[width]")}
            style={{ width: `${percent}%` }}
          />
        </span>
      ) : null}

      {!running ? (
        <Button size="icon-sm" variant="ghost" onClick={onResync} aria-label="Sync now">
          <RefreshCw aria-hidden />
        </Button>
      ) : null}
    </div>
  );
}
