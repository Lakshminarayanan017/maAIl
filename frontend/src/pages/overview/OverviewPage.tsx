import { ArrowRight, CalendarClock, Code2, Inbox, Mail, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { Skeleton } from "@/components/common/Skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { overview as overviewApi } from "@/services/api";
import { useAiPanel } from "@/stores/aiPanel";
import { useInbox } from "@/stores/inbox";
import type { Overview, PriorityCard } from "@/types/api";

/**
 * Screen 03 — Overview / Command Center (08-ui-spec.md §9).
 *
 *     Good morning, [name]              │ Maail AI
 *     Your day, simplified.             │ Daily briefing
 *
 *     ┌────────┐ ┌───────────┐          │ ...
 *     │  24    │ │     5     │          │
 *     │ Emails │ │ Attention │          │ [ Explore → ]
 *     └────────┘ └───────────┘          │ Ask Maail...
 *
 * The one thing this screen must not do:
 *
 * > counts and AI-generated classifications must be clearly separated. We
 * > shouldn't present estimated urgency as a factual status.
 *
 * So the two count cards are plain: no lavender, no sparkle, large
 * tabular numerals. Everything below them is a judgement and wears the
 * AI treatment, with the reason attached. "24 Emails" is a fact; "5
 * Attention" is a count *of* judgements, which is why it says how many of
 * the mailbox has actually been looked at underneath.
 */
function CountCard({
  value,
  label,
  note,
  icon: Icon,
}: {
  value: number;
  label: string;
  note?: string;
  icon: typeof Mail;
}) {
  return (
    <Card className="flex min-w-32 flex-1 flex-col gap-0.5 p-s2">
      <span className="flex items-center gap-1.5 text-2xs uppercase tracking-wide text-fg-subtle">
        <Icon className="size-3" aria-hidden />
        {label}
      </span>
      <span className="font-brand text-3xl font-bold tabular-nums text-fg">{value}</span>
      {note ? <span className="text-2xs text-fg-subtle">{note}</span> : null}
    </Card>
  );
}

function PriorityRow({
  card,
  onOpen,
}: {
  card: PriorityCard;
  onOpen: (card: PriorityCard) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(card)}
      className="flex w-full items-start gap-2 rounded-sm border border-line bg-surface px-s2 py-2 text-left transition-colors hover:bg-surface-sunken"
    >
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-1">
          {card.category ? (
            <Badge variant="ai">
              <Sparkles className="size-2.5" aria-hidden />
              {card.category}
            </Badge>
          ) : null}
          {card.is_technical ? <Badge variant="violet">Technical</Badge> : null}
          <span className="truncate text-2xs text-fg-subtle">{card.sender}</span>
        </span>
        <span className="mt-0.5 block truncate text-base font-medium text-fg">
          {card.subject || "(no subject)"}
        </span>
        {/* Never an unexplained badge. */}
        {card.priority_reason ? (
          <span className="mt-0.5 block truncate text-sm text-fg-muted">
            {card.priority_reason}
          </span>
        ) : null}
      </span>
      <ArrowRight className="mt-1 size-3.5 shrink-0 text-fg-subtle" aria-hidden />
    </button>
  );
}

export function OverviewPage() {
  const navigate = useNavigate();
  const select = useInbox((state) => state.select);
  const openPanel = useAiPanel((state) => state.open);
  const setContext = useAiPanel((state) => state.setContext);

  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setError(null);
    void overviewApi
      .read()
      .then(setData)
      .catch((caught: unknown) =>
        setError(caught instanceof Error ? caught.message : "Could not load your overview"),
      );
  };

  useEffect(load, []);

  /**
   * The specified interaction:
   *
   * > clicking a GitHub failure card goes directly to the email detail
   * > screen with Developer Intelligence activated in the right panel.
   *
   * So the card opens the thread *and* focuses the panel on it, rather
   * than dropping the reader in the inbox to find it again.
   */
  const open = (card: PriorityCard) => {
    void select(card.thread_id);
    setContext({
      kind: "thread",
      id: card.thread_id,
      label: card.subject || "Thread",
    });
    openPanel();
    void navigate("/inbox");
  };

  if (error) return <ErrorState description={error} onRetry={load} />;

  if (!data) {
    return (
      <div role="status" aria-busy="true" className="mx-auto max-w-3xl px-s3 py-s3">
        <span className="sr-only">Loading your overview</span>
        <Skeleton className="h-8 w-64" />
        <div className="mt-s3 flex gap-s2">
          <Skeleton className="h-24 flex-1" />
          <Skeleton className="h-24 flex-1" />
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-s3 py-s3">
      <h2 className="font-brand text-2xl font-bold text-fg">{data.greeting}</h2>
      <p className="mt-0.5 text-md text-fg-muted">Your day, simplified.</p>

      {/* Facts. Deliberately plain: no lavender, no sparkle. */}
      <div className="mt-s3 flex flex-wrap gap-s2">
        <CountCard
          value={data.counts.threads}
          label="Emails"
          note={`${data.counts.unread} unread · ${data.counts.today} today`}
          icon={Mail}
        />
        <CountCard
          value={data.attention.length}
          label="Attention"
          note={
            data.counts.analysed < data.counts.threads
              ? `${data.counts.analysed} of ${data.counts.threads} analysed so far`
              : "all analysed"
          }
          icon={Inbox}
        />
      </div>

      <section className="mt-s4">
        <h3 className="flex items-center gap-1.5 font-brand text-lg font-semibold text-fg">
          Today&rsquo;s important items
          <Tooltip>
            <TooltipTrigger asChild>
              <span>
                <Badge variant="ai">
                  <Sparkles className="size-2.5" aria-hidden />
                  AI classified
                </Badge>
              </span>
            </TooltipTrigger>
            <TooltipContent>
              These are Maail&rsquo;s judgements, not facts about your mail. Each one says why.
            </TooltipContent>
          </Tooltip>
        </h3>

        <div className="mt-s2 flex flex-col gap-1.5">
          {data.attention.length === 0 ? (
            <EmptyState
              icon={Inbox}
              title="Nothing needs you right now"
              description={
                data.counts.analysed === 0
                  ? "Nothing has been analysed yet. Sync your mail and Maail will start."
                  : "Maail has read your mail and found nothing urgent."
              }
            />
          ) : (
            data.attention.map((card) => (
              <PriorityRow key={card.thread_id} card={card} onOpen={open} />
            ))
          )}
        </div>
      </section>

      <section className="mt-s4">
        <h3 className="font-brand text-lg font-semibold text-fg">Upcoming deadlines</h3>
        <div className="mt-s2">
          {data.upcoming_deadlines.length === 0 ? (
            <EmptyState
              icon={CalendarClock}
              title="No deadlines yet"
              description="Maail lists a deadline only when a sender named one. Extraction arrives in phase 9."
            />
          ) : null}
        </div>
      </section>

      {data.technical_count > 0 ? (
        <section className="mt-s4">
          <h3 className="flex items-center gap-1.5 font-brand text-lg font-semibold text-fg">
            <Code2 className="size-4 text-violet" aria-hidden />
            Developer activity
          </h3>
          <p className="mt-1 text-base text-fg-muted">
            {data.technical_count} technical thread{data.technical_count === 1 ? "" : "s"} worth a
            look.
          </p>
          <Button
            variant="ghost"
            size="sm"
            className="mt-s1"
            onClick={() => void navigate("/developer")}
          >
            Developer Hub
            <ArrowRight aria-hidden />
          </Button>
        </section>
      ) : null}
    </div>
  );
}

export default OverviewPage;
