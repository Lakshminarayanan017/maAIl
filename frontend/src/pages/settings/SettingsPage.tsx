import {
  Bell,
  Bot,
  Brain,
  LogOut,
  Mail,
  Palette,
  Plug,
  Plus,
  ShieldCheck,
  Sparkles,
  User,
} from "lucide-react";
import { useEffect, useState } from "react";

import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { Skeleton } from "@/components/common/Skeleton";
import { ThemeSwitcher } from "@/components/common/ThemeSwitcher";
import { AccountCard } from "@/components/settings/AccountCard";
import { FeatureControls } from "@/components/settings/FeatureControls";
import { MemoryInspector } from "@/components/settings/MemoryInspector";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { auth } from "@/services/api";
import { useAccounts } from "@/stores/accounts";
import { useSession } from "@/stores/session";
import { cn } from "@/lib/utils";

/**
 * Screen 11 — Settings & Integrations. All nine sections, in the spec's
 * order (08-ui-spec.md, screen 10 table):
 *
 *   Account · Email accounts · AI preferences · Memory · Agents ·
 *   Integrations · Privacy · Appearance · Notifications
 *
 * Phase 11 fills AI preferences with the real feature registry — entry
 * point B, "the complete control center". Four of the nine are honest
 * placeholders naming the phase that fills them, because a section that
 * is missing reads as a bug while a section that says "arrives in phase
 * 13" reads as a plan.
 *
 * The rail on the left is a jump list rather than a router: the whole
 * page is one document, so Ctrl+F finds a setting wherever it lives.
 */
const SECTIONS = [
  { id: "account", label: "Account", icon: User },
  { id: "email-accounts", label: "Email accounts", icon: Mail },
  { id: "ai-preferences", label: "AI preferences", icon: Sparkles },
  { id: "memory", label: "Memory", icon: Brain },
  { id: "agents", label: "Agents", icon: Bot },
  { id: "integrations", label: "Integrations", icon: Plug },
  { id: "privacy", label: "Privacy", icon: ShieldCheck },
  { id: "appearance", label: "Appearance", icon: Palette },
  { id: "notifications", label: "Notifications", icon: Bell },
] as const;

function Section({
  id,
  title,
  description,
  children,
}: {
  id: string;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-s3">
      <h2 className="font-brand text-xl font-semibold text-fg">{title}</h2>
      {description ? <p className="mt-1 text-base text-fg-muted">{description}</p> : null}
      <div className="mt-s2">{children}</div>
    </section>
  );
}

/** A section whose controls belong to a later phase. Named, not hidden. */
function ComingIn({ phase, what }: { phase: number; what: string }) {
  return (
    <p className="inline-flex items-center gap-1.5 rounded-sm border border-line bg-surface-sunken px-s2 py-1.5 text-sm text-fg-muted">
      <Badge variant="neutral">phase {phase}</Badge>
      {what}
    </p>
  );
}

export function SettingsPage() {
  const user = useSession((state) => state.user);
  const signOut = useSession((state) => state.signOut);

  const items = useAccounts((state) => state.items);
  const loading = useAccounts((state) => state.loading);
  const error = useAccounts((state) => state.error);
  const load = useAccounts((state) => state.load);
  const reconnect = useAccounts((state) => state.reconnect);
  const disconnect = useAccounts((state) => state.disconnect);

  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState<string>(SECTIONS[0].id);

  useEffect(() => {
    void load();
  }, [load]);

  // Highlight whichever section is currently in view, so the rail says
  // where you are rather than only where you can go.
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (visible) setActive(visible.target.id);
      },
      { rootMargin: "-10% 0px -70% 0px" },
    );
    for (const section of SECTIONS) {
      const node = document.getElementById(section.id);
      if (node) observer.observe(node);
    }
    return () => observer.disconnect();
  }, []);

  const connect = () => {
    setBusy(true);
    void auth
      .startGoogle()
      .then(({ authorize_url }) => window.location.assign(authorize_url))
      .catch(() => setBusy(false));
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl gap-s4 px-s3 py-s3">
      <nav aria-label="Settings sections" className="hidden w-44 shrink-0 lg:block">
        <ul className="sticky top-s3 flex flex-col gap-0.5">
          {SECTIONS.map((section) => (
            <li key={section.id}>
              <a
                href={`#${section.id}`}
                className={cn(
                  "flex items-center gap-1.5 rounded-sm px-1.5 py-1 text-base transition-colors",
                  active === section.id
                    ? "bg-ai text-ai-fg"
                    : "text-fg-muted hover:bg-surface-sunken",
                )}
              >
                <section.icon className="size-3.5 shrink-0" aria-hidden />
                {section.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col gap-s4">
        <Section id="account" title="Account" description="Profile and authentication.">
          <p className="text-base text-fg">{user?.email ?? "Not signed in"}</p>
          {user?.name ? <p className="text-sm text-fg-muted">{user.name}</p> : null}
          <Button
            variant="secondary"
            size="sm"
            className="mt-s2"
            onClick={() => {
              void signOut().then(() => window.location.assign("/"));
            }}
          >
            <LogOut aria-hidden />
            Sign out
          </Button>
        </Section>

        <Separator />

        <Section
          id="email-accounts"
          title="Email accounts"
          description="Maail reads these mailboxes. It never sends anything without asking."
        >
          <div className="flex flex-col gap-s2">
            {loading && items.length === 0 ? (
              <div role="status" aria-busy="true">
                <span className="sr-only">Loading accounts</span>
                <Skeleton className="h-28" />
              </div>
            ) : null}

            {error ? <ErrorState description={error} onRetry={() => void load()} /> : null}

            {!loading && !error && items.length === 0 ? (
              <EmptyState
                title="No connected account"
                description="Connect Gmail to start. Maail reads your mail; it never sends without asking."
                action={{ label: "Connect Gmail", onClick: connect }}
              />
            ) : null}

            {items.map((account) => (
              <AccountCard
                key={account.id}
                account={account}
                busy={busy}
                onReconnect={(id) => {
                  setBusy(true);
                  void reconnect(id).catch(() => setBusy(false));
                }}
                onDisconnect={(id, purge) => {
                  setBusy(true);
                  void disconnect(id, purge).finally(() => setBusy(false));
                }}
              />
            ))}

            {items.length > 0 ? (
              <Button
                variant="ghost"
                size="sm"
                className="self-start"
                onClick={connect}
                disabled={busy}
              >
                <Plus aria-hidden />
                Connect another account
              </Button>
            ) : null}
          </div>
        </Section>

        <Separator />

        {/* Entry point B — the complete control center. */}
        <section id="ai-preferences" className="scroll-mt-s3">
          <FeatureControls />
        </section>

        <Separator />

        <section id="memory" className="scroll-mt-s3">
          <MemoryInspector />
        </section>

        <Separator />

        <Section
          id="agents"
          title="Agents"
          description="Which specialists may run, and what each is allowed to reach."
        >
          <p className="text-base text-fg-muted">
            Every agent&rsquo;s permissions are set by its plane, which is declared in Git and
            enforced before it starts &mdash; an agent that has read your mail holds no tool that
            can act. What you can change is which of them run, and that is the feature list above.
          </p>
          <div className="mt-s2">
            <ComingIn phase={14} what="Per-agent controls and the Agent Workspace." />
          </div>
        </Section>

        <Separator />

        <Section
          id="integrations"
          title="Integrations"
          description="Services Maail may read alongside your mail."
        >
          <ComingIn phase={13} what="GitHub and Calendar, each read-only and separately granted." />
        </Section>

        <Separator />

        <Section
          id="privacy"
          title="Privacy"
          description="What Maail holds, and how to get rid of it."
        >
          <ul className="flex flex-col gap-1 text-base text-fg-muted">
            <li>Message bodies are fetched when you open them and never stored.</li>
            <li>
              Provider tokens are sealed before they are written and only ever opened in one place.
            </li>
            <li>
              Disconnecting an account deletes its mail after 30 days, or immediately if you ask
              &mdash; in the Email accounts section above.
            </li>
            <li>
              Everything Maail remembers about you is listed in Memory, with a delete button each.
            </li>
          </ul>
          <div className="mt-s2">
            <ComingIn phase={16} what="Full export and one-click account deletion." />
          </div>
        </Section>

        <Separator />

        <Section
          id="appearance"
          title="Appearance"
          description="Light, dark, or whatever your system says."
        >
          <ThemeSwitcher />
        </Section>

        <Separator />

        <Section
          id="notifications"
          title="Notifications"
          description="Priority and deadline alerts."
        >
          <ComingIn phase={15} what="Alert channels and quiet hours." />
        </Section>
      </div>
    </div>
  );
}

export default SettingsPage;
