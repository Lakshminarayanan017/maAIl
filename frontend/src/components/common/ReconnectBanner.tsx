import { AlertTriangle, RefreshCw } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { accountNeedingReconnect, useAccounts } from "@/stores/accounts";

/**
 * Persistent and non-dismissable while an account needs re-authorising.
 *
 * > **Reconnect banner** — persistent, non-dismissable while
 * > `reauth_required`
 * > (09-execution-plan.md, phase 1)
 *
 * There is no close button on purpose. While this is showing, no mail is
 * arriving, and a banner the user can dismiss is a banner that turns a
 * stalled mailbox into a mystery a week later.
 *
 * This is the weekly case rather than an error: Google expires a
 * Testing-mode refresh token after about seven days (gap A3), so the copy
 * says what happened and what to do, without alarm.
 */
export function ReconnectBanner() {
  const items = useAccounts((state) => state.items);
  const reconnect = useAccounts((state) => state.reconnect);
  const [busy, setBusy] = useState(false);

  const account = accountNeedingReconnect(items);
  if (!account) return null;

  const start = () => {
    setBusy(true);
    void reconnect(account.id).catch(() => setBusy(false));
  };

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-wrap items-center justify-center gap-x-s2 gap-y-1 border-b border-warning-border bg-warning px-s2 py-1.5 text-sm text-warning-fg"
    >
      <span className="flex items-center gap-2">
        <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
        <span>
          <strong className="font-medium">{account.email}</strong> needs reconnecting. New mail is
          not arriving until you do.
        </span>
      </span>
      <Button size="sm" variant="secondary" onClick={start} disabled={busy}>
        <RefreshCw className={busy ? "animate-spin" : ""} aria-hidden />
        Reconnect
      </Button>
    </div>
  );
}
