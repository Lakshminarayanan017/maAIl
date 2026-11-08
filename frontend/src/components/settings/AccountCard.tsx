import { AlertTriangle, Check, Clock, Mail, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { Account, AccountStatus } from "@/types/api";

/**
 * The connected-account card: address, status, disconnect.
 *
 * > Connection and synchronization status
 * > (08-ui-spec.md, screen 02 requirements)
 *
 * The status line never says "connected" when it is not. A connection whose
 * refresh token is about to expire says so, with a date, because the whole
 * point of storing `refresh_expires_at` is to warn before the expiry rather
 * than after a sync has already failed (gap A3).
 */

const STATUS_LABEL: Record<AccountStatus, string> = {
  connecting: "Connecting",
  active: "Connected",
  reauth_required: "Needs reconnecting",
  disconnected: "Disconnected",
  error: "Needs attention",
};

const STATUS_VARIANT: Record<AccountStatus, "success" | "warning" | "danger" | "neutral"> = {
  connecting: "neutral",
  active: "success",
  reauth_required: "warning",
  disconnected: "neutral",
  error: "danger",
};

function formatDate(value: string | null): string | null {
  if (!value) return null;
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function relativeDays(value: string | null): string | null {
  if (!value) return null;
  const days = Math.round((new Date(value).getTime() - Date.now()) / 86_400_000);
  if (days < 0) return "already expired";
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}

export interface AccountCardProps {
  account: Account;
  onReconnect: (id: string) => void;
  onDisconnect: (id: string, purge: "now" | "30d") => void;
  busy?: boolean;
}

export function AccountCard({ account, onReconnect, onDisconnect, busy }: AccountCardProps) {
  const [confirming, setConfirming] = useState(false);
  const expiry = formatDate(account.refresh_expires_at);

  return (
    <Card className="p-s2">
      <div className="flex flex-wrap items-start justify-between gap-s2">
        <div className="flex min-w-0 items-start gap-2">
          <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-sm border border-line bg-surface-sunken text-fg-muted">
            <Mail className="size-4" aria-hidden />
          </span>
          <div className="min-w-0">
            <p className="truncate font-medium text-fg">{account.email}</p>
            <p className="text-sm capitalize text-fg-subtle">{account.provider}</p>
          </div>
        </div>
        <Badge variant={STATUS_VARIANT[account.status]}>
          {account.status === "active" ? (
            <Check className="size-3" aria-hidden />
          ) : account.status === "reauth_required" || account.status === "error" ? (
            <AlertTriangle className="size-3" aria-hidden />
          ) : null}
          {STATUS_LABEL[account.status]}
        </Badge>
      </div>

      {account.missing_scopes.length > 0 ? (
        <p className="mt-s2 rounded-sm border border-danger-border bg-danger px-2 py-1.5 text-sm text-danger-fg">
          A permission was declined, so Maail cannot read this mailbox. Reconnect and leave every
          box ticked.
        </p>
      ) : null}

      {account.needs_reconnect ? (
        <p className="mt-s2 rounded-sm border border-warning-border bg-warning px-2 py-1.5 text-sm text-warning-fg">
          Google ended this authorisation. Reconnecting takes a few seconds and keeps everything
          Maail already knows about this mailbox.
        </p>
      ) : null}

      {account.status === "active" && expiry ? (
        <p
          className={
            account.expires_soon
              ? "mt-s2 flex items-center gap-1.5 text-sm text-warning-fg"
              : "mt-s2 flex items-center gap-1.5 text-sm text-fg-muted"
          }
        >
          <Clock className="size-3.5 shrink-0" aria-hidden />
          Authorisation expires {relativeDays(account.refresh_expires_at)}
          <span className="text-fg-subtle">({expiry})</span>
        </p>
      ) : null}

      <Separator className="my-s2" />

      <div className="flex flex-wrap items-center gap-s1">
        <Button
          size="sm"
          variant={account.needs_reconnect ? "primary" : "secondary"}
          onClick={() => onReconnect(account.id)}
          disabled={busy}
        >
          <RefreshCw aria-hidden />
          Reconnect
        </Button>

        {confirming ? (
          <>
            <span className="text-sm text-fg-muted">
              Disconnect {account.email}? Mail is deleted after 30 days.
            </span>
            <Button
              size="sm"
              variant="danger"
              onClick={() => {
                setConfirming(false);
                onDisconnect(account.id, "30d");
              }}
              disabled={busy}
            >
              Disconnect
            </Button>
            <Button
              size="sm"
              variant="danger"
              onClick={() => {
                setConfirming(false);
                onDisconnect(account.id, "now");
              }}
              disabled={busy}
            >
              Disconnect and delete now
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => setConfirming(true)} disabled={busy}>
            <Trash2 aria-hidden />
            Disconnect
          </Button>
        )}
      </div>
    </Card>
  );
}
