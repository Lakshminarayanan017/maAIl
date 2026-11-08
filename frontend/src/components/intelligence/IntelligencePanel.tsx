import {
  AlertTriangle,
  ArrowRight,
  Ban,
  CalendarClock,
  CheckCircle2,
  Circle,
  CircleHelp,
  Code2,
  FileSearch,
  Loader2,
  MessageSquareReply,
  RefreshCw,
  Sparkles,
  Tags,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/common/ErrorState";
import { AiBlockSkeleton } from "@/components/intelligence/AiValue";
import {
  ProvenanceLegend,
  ProvenanceMark,
  ProvenanceValue,
} from "@/components/intelligence/Provenance";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { intelligence as intelligenceApi, tasks as tasksApi } from "@/services/api";
import { useInbox } from "@/stores/inbox";
import type {
  ActionItem,
  AiStatusValue,
  Deadline,
  Entity,
  EntityKind,
  ThreadIntelligence,
} from "@/types/api";

/**
 * Screen 05's right pane — the product differentiator.
 *
 * Six sections in the specified order: Summary · Intent detection ·
 * Extracted entities · Action items · Related context · Suggested
 * response.
 *
 * Three things this component is responsible for, none of which can be
 * left to the reader to work out:
 *
 * **Status is per capability.** A ready summary next to a failed deadline
 * pass is two states on one screen, and neither is allowed to be
 * represented by the other's absence (gap C4). Every section renders its
 * own.
 *
 * **Nothing is claimed without its source.** Values go through
 * `ProvenanceValue`, which refuses to render a `stated` value with no
 * resolvable span. The backend has already dropped the spans that do not
 * resolve, so what arrives here is checkable by construction.
 *
 * **Reading costs nothing.** Opening a thread does a GET. Analysis is a
 * button, because three agent runs per scroll is a bill, not a feature.
 */
const STATUS_WORD: Record<AiStatusValue, string> = {
  not_applicable: "not applicable",
  pending: "not analysed",
  running: "analysing",
  ready: "ready",
  failed: "failed",
  skipped_disabled: "turned off",
  skipped_budget: "budget reached",
};

const INTENT_LABEL: Record<string, string> = {
  reply_requested: "Waiting on your reply",
  action_requested: "Wants something done",
  information_only: "Just information",
  deadline_set: "Sets a deadline",
  approval_requested: "Needs a yes or no",
  scheduling: "Finding a time",
  other: "Something else",
};

const ENTITY_LABEL: Record<EntityKind, string> = {
  project: "Project",
  repository: "Repository",
  technology: "Technology",
  date: "Date",
  error_message: "Error",
  person: "Person",
  organization: "Organisation",
};

const DATE_TYPE_NOTE: Record<string, string> = {
  explicit_absolute: "A named date",
  explicit_relative: "Relative to when it was sent",
  soft_request: "A preference, not a requirement",
  vague: "No date named",
  recurring: "Recurring",
};

function SectionStatus({ status }: { status: AiStatusValue }) {
  if (status === "ready") return null;

  const Icon =
    status === "running"
      ? Loader2
      : status === "failed"
        ? AlertTriangle
        : status === "skipped_disabled" || status === "skipped_budget"
          ? Ban
          : Circle;

  return (
    <span
      className={cnStatus(status)}
      role={status === "failed" ? "alert" : undefined}
      aria-live={status === "running" ? "polite" : undefined}
    >
      <Icon className={`size-3 ${status === "running" ? "animate-spin" : ""}`} aria-hidden />
      {STATUS_WORD[status]}
    </span>
  );
}

function cnStatus(status: AiStatusValue): string {
  const base = "inline-flex items-center gap-1 text-2xs";
  if (status === "failed") return `${base} text-danger-fg`;
  if (status === "running") return `${base} text-violet`;
  return `${base} text-fg-subtle`;
}

function Section({
  title,
  icon: Icon,
  status,
  children,
  action,
}: {
  title: string;
  icon: typeof Sparkles;
  status?: AiStatusValue;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-1.5 px-s2 py-s2">
      <header className="flex items-center gap-1.5">
        <Icon className="size-3.5 shrink-0 text-violet" aria-hidden />
        <h3 className="flex-1 font-brand text-base font-semibold text-fg">{title}</h3>
        {status ? <SectionStatus status={status} /> : null}
        {action}
      </header>
      {children}
    </section>
  );
}

function DeadlineRow({
  deadline,
  onResolve,
}: {
  deadline: Deadline;
  onResolve: (deadline: Deadline) => void;
}) {
  const unclear = deadline.resolution_status === "ambiguous";
  const settled =
    deadline.resolution_status === "user_confirmed" ||
    deadline.resolution_status === "user_corrected";

  return (
    <div className="flex flex-col gap-1 rounded-sm border border-line bg-surface p-1.5">
      {/* The sender's words first, always. The user sees what was
          written next to whatever became of it. */}
      <q className="text-base italic text-fg">{deadline.raw_phrase}</q>

      {unclear ? (
        <>
          {/* A question, never a date. Nothing was invented to fill the
              column, so there is nothing to show but the question. */}
          <span className="flex items-start gap-1.5 text-sm text-warning-fg">
            <CircleHelp className="mt-0.5 size-3 shrink-0" aria-hidden />
            Which one does this mean?
          </span>
          <Button
            size="sm"
            variant="secondary"
            className="h-6 self-start text-2xs"
            onClick={() => onResolve(deadline)}
          >
            Tell Maail which
          </Button>
        </>
      ) : deadline.normalized_date ? (
        <span className="flex items-center gap-1.5">
          <ProvenanceMark provenance={settled ? "stated" : "interpreted"} />
          <span className="text-base font-medium text-fg">{deadline.normalized_date}</span>
          {settled ? (
            <Badge variant="violet">
              {deadline.resolution_status === "user_corrected"
                ? "You corrected this"
                : "You confirmed this"}
            </Badge>
          ) : (
            <Badge variant="neutral">{deadline.confidence_band} confidence</Badge>
          )}
        </span>
      ) : (
        <span className="text-2xs text-fg-subtle">No date named</span>
      )}

      <span className="text-2xs text-fg-subtle">
        {DATE_TYPE_NOTE[deadline.date_type] ?? deadline.date_type}
        {deadline.is_for_user ? "" : " · not yours"}
      </span>
    </div>
  );
}

function ActionRow({
  item,
  onConfirm,
  busy,
}: {
  item: ActionItem;
  onConfirm: (item: ActionItem) => void;
  busy: boolean;
}) {
  return (
    <div className="flex items-start gap-1.5 rounded-sm border border-line bg-surface p-1.5">
      <ProvenanceMark
        provenance={item.source === "stated" ? "stated" : "interpreted"}
        className="mt-0.5"
      />
      <div className="min-w-0 flex-1">
        <p className="text-base text-fg">{item.description}</p>
        <p className="mt-0.5 flex flex-wrap items-center gap-1 text-2xs text-fg-subtle">
          {/* The two labels are never merged, including in the wording. */}
          <span>{item.source === "stated" ? "They asked for this" : "Maail inferred this"}</span>
          <span aria-hidden>·</span>
          <span>
            {item.owner === "user"
              ? "yours"
              : item.owner === "sender"
                ? "theirs"
                : item.owner === "other"
                  ? "someone else's"
                  : "nobody said whose"}
          </span>
        </p>
        {item.evidence?.quote ? (
          <q className="mt-0.5 block border-l-2 border-ai-border pl-1.5 text-2xs italic text-fg-muted">
            {item.evidence.quote}
          </q>
        ) : null}
      </div>

      {item.task_id ? (
        <Badge variant="success" className="mt-0.5 shrink-0">
          <CheckCircle2 className="size-2.5" aria-hidden />
          On your list
        </Badge>
      ) : (
        <Button
          size="sm"
          variant="ghost"
          className="mt-0.5 h-6 shrink-0 text-2xs"
          disabled={busy}
          onClick={() => onConfirm(item)}
        >
          Add to tasks
        </Button>
      )}
    </div>
  );
}

function EntityGroup({ kind, items }: { kind: EntityKind; items: Entity[] }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-2xs uppercase tracking-wide text-fg-subtle">{ENTITY_LABEL[kind]}</span>
      <div className="flex flex-wrap gap-1">
        {items.map((entity) => (
          <Tooltip key={`${entity.kind}-${entity.value}`}>
            <TooltipTrigger asChild>
              <span
                className={
                  entity.provenance === "stated"
                    ? "inline-flex items-center gap-1 rounded-sm border border-line bg-surface-sunken px-1.5 py-0.5 text-sm text-fg"
                    : "inline-flex items-center gap-1 rounded-sm border border-ai-border bg-ai px-1.5 py-0.5 text-sm text-ai-fg"
                }
              >
                <ProvenanceMark provenance={entity.provenance} />
                <span className={kind === "error_message" ? "font-mono text-2xs" : ""}>
                  {entity.value}
                </span>
              </span>
            </TooltipTrigger>
            <TooltipContent>
              {entity.evidence?.quote
                ? `"${entity.evidence.quote}"`
                : entity.provenance === "stated"
                  ? "Named in the email"
                  : "Maail worked this out from the thread"}
            </TooltipContent>
          </Tooltip>
        ))}
      </div>
    </div>
  );
}

export interface IntelligencePanelProps {
  threadId: string;
  /** Shown as the panel's own heading context. */
  subject?: string | null | undefined;
}

export function IntelligencePanel({ threadId }: IntelligencePanelProps) {
  const [data, setData] = useState<ThreadIntelligence | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [analysing, setAnalysing] = useState(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [resolving, setResolving] = useState<Deadline | null>(null);
  const select = useInbox((state) => state.select);

  const load = useCallback(() => {
    setError(null);
    return intelligenceApi
      .read(threadId)
      .then(setData)
      .catch((caught: unknown) =>
        setError(caught instanceof Error ? caught.message : "Could not read this thread"),
      );
  }, [threadId]);

  useEffect(() => {
    setData(null);
    void load();
  }, [load]);

  const analyse = () => {
    setAnalysing(true);
    void intelligenceApi
      .analyse(threadId)
      .then(setData)
      .catch((caught: unknown) =>
        setError(caught instanceof Error ? caught.message : "Could not analyse this thread"),
      )
      .finally(() => setAnalysing(false));
  };

  const confirmAction = (item: ActionItem) => {
    setBusyAction(item.id);
    void tasksApi
      .confirm(item.id)
      .then(() => load())
      .finally(() => setBusyAction(null));
  };

  const resolveDeadline = (chosen: string) => {
    if (!resolving) return;
    const deadline = resolving;
    setResolving(null);
    void tasksApi
      .resolveDeadline(deadline.id, chosen, deadline.resolution_status !== "ambiguous")
      .then(() => load());
  };

  if (error) return <ErrorState description={error} onRetry={() => void load()} />;

  if (!data) {
    return (
      <div className="flex flex-col gap-s2 p-s2">
        <AiBlockSkeleton kind="summary" />
        <AiBlockSkeleton kind="actions" />
      </div>
    );
  }

  const nothingYet = data.missing.length === 3 && data.summary.status !== "ready";

  return (
    <div className="flex flex-col">
      <div className="flex items-center gap-1.5 border-b border-line px-s2 py-1.5">
        <ProvenanceLegend className="flex-1" />
        {data.missing.length > 0 ? (
          <Button
            size="sm"
            variant="secondary"
            className="h-6 shrink-0 text-2xs"
            disabled={analysing}
            onClick={analyse}
          >
            {analysing ? (
              <Loader2 className="size-3 animate-spin" aria-hidden />
            ) : (
              <RefreshCw className="size-3" aria-hidden />
            )}
            {nothingYet ? "Analyse" : "Finish analysis"}
          </Button>
        ) : null}
      </div>

      {/* 1. Summary */}
      <Section title="Summary" icon={Sparkles} status={data.summary.status}>
        {data.summary.status === "running" || analysing ? (
          <AiBlockSkeleton kind="summary" />
        ) : data.summary.summary ? (
          <>
            <ProvenanceValue provenance="interpreted" evidence={data.summary.evidence}>
              {data.summary.summary}
            </ProvenanceValue>
            {data.summary.stale ? (
              <span className="text-2xs text-warning-fg">
                New mail has arrived since this was written.
              </span>
            ) : null}
            {data.summary.bullet_points.length > 0 ? (
              <ul className="ml-s2 list-disc text-sm text-fg-muted">
                {data.summary.bullet_points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            ) : null}
          </>
        ) : (
          <p className="text-2xs text-fg-subtle">
            {data.summary.status === "pending"
              ? "Not analysed yet."
              : "Nothing could be summarised."}
          </p>
        )}
      </Section>

      <Separator />

      {/* 2. Intent detection */}
      <Section title="What they want" icon={MessageSquareReply} status={data.intent.status}>
        {data.intent.intent ? (
          <ProvenanceValue provenance="interpreted" evidence={data.intent.evidence}>
            <span className="font-medium">
              {INTENT_LABEL[data.intent.intent] ?? data.intent.intent}
            </span>
            {data.intent.reason ? (
              <span className="mt-0.5 block text-sm text-fg-muted">{data.intent.reason}</span>
            ) : null}
            {data.intent.confidence ? (
              <Badge variant="neutral" className="mt-1">
                {data.intent.confidence} confidence
              </Badge>
            ) : null}
          </ProvenanceValue>
        ) : (
          <p className="text-2xs text-fg-subtle">Not determined</p>
        )}
      </Section>

      <Separator />

      {/* 3. Extracted entities */}
      <Section title="What it names" icon={Tags} status={data.summary.status}>
        {data.entities.length === 0 ? (
          <p className="text-2xs text-fg-subtle">Nothing specific was named.</p>
        ) : (
          <div className="flex flex-col gap-1.5">
            {(Object.keys(ENTITY_LABEL) as EntityKind[])
              .map((kind) => ({
                kind,
                items: data.entities.filter((entity) => entity.kind === kind),
              }))
              .filter((group) => group.items.length > 0)
              .map((group) => (
                <EntityGroup key={group.kind} kind={group.kind} items={group.items} />
              ))}
          </div>
        )}
      </Section>

      <Separator />

      {/* 4. Action items, with deadlines beside them */}
      <Section title="What needs to happen" icon={CheckCircle2} status={data.status_actions}>
        {data.action_items.length === 0 ? (
          <p className="text-2xs text-fg-subtle">
            {data.status_actions === "ready" ? "Nothing needs doing here." : "Not analysed yet."}
          </p>
        ) : (
          <div className="flex flex-col gap-1">
            {data.action_items.map((item) => (
              <ActionRow
                key={item.id}
                item={item}
                busy={busyAction === item.id}
                onConfirm={confirmAction}
              />
            ))}
          </div>
        )}
      </Section>

      {(data.deadlines.length > 0 || data.status_deadline !== "not_applicable") && (
        <>
          <Separator />
          <Section title="Dates" icon={CalendarClock} status={data.status_deadline}>
            {data.deadlines.length === 0 ? (
              <p className="text-2xs text-fg-subtle">
                {data.status_deadline === "ready"
                  ? "No deadline in this thread."
                  : "Not analysed yet."}
              </p>
            ) : (
              <div className="flex flex-col gap-1">
                {data.deadlines.map((deadline) => (
                  <DeadlineRow key={deadline.id} deadline={deadline} onResolve={setResolving} />
                ))}
              </div>
            )}
          </Section>
        </>
      )}

      <Separator />

      {/* 5. Related context */}
      <Section title="Related" icon={FileSearch}>
        {data.related.length === 0 ? (
          <p className="text-2xs text-fg-subtle">Nothing else in your mail touches this.</p>
        ) : (
          <div className="flex flex-col gap-1">
            {data.related.map((item) => (
              <button
                key={item.thread_id}
                type="button"
                onClick={() => void select(item.thread_id)}
                className="flex items-start gap-1.5 rounded-sm border border-line bg-surface p-1.5 text-left transition-colors hover:bg-surface-sunken"
              >
                <ProvenanceMark provenance="retrieved" className="mt-0.5" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-base text-fg">
                    {item.subject || "(no subject)"}
                  </span>
                  {/* Never an unexplained chip. */}
                  <span className="block truncate text-2xs text-fg-subtle">{item.because}</span>
                </span>
                <ArrowRight className="mt-1 size-3 shrink-0 text-fg-subtle" aria-hidden />
              </button>
            ))}
          </div>
        )}
      </Section>

      <Separator />

      {/* 6. Suggested response — the slot. */}
      <Section title="Suggested response" icon={Code2}>
        <p className="text-2xs text-fg-subtle">
          Drafting arrives in phase 12, behind approval. Maail will never send anything without you
          reading it first.
        </p>
      </Section>

      {resolving ? (
        <ResolveDialog
          deadline={resolving}
          onCancel={() => setResolving(null)}
          onChoose={resolveDeadline}
        />
      ) : null}
    </div>
  );
}

/**
 * The ambiguity resolver, inline.
 *
 * It quotes the sender and asks. The options are days the backend computed
 * from the message's send date; there is no default and no preselection,
 * because preselecting one would be the guess this whole path exists to
 * avoid.
 */
function ResolveDialog({
  deadline,
  onCancel,
  onChoose,
}: {
  deadline: Deadline;
  onCancel: () => void;
  onChoose: (chosen: string) => void;
}) {
  const [custom, setCustom] = useState("");

  return (
    <div
      role="dialog"
      aria-label="Which date does this mean?"
      className="m-s2 flex flex-col gap-1.5 rounded-sm border border-warning-border bg-warning p-s2"
    >
      <p className="text-base text-warning-fg">
        <q className="italic">{deadline.raw_phrase}</q> &mdash; which day?
      </p>
      <div className="flex flex-wrap gap-1">
        <input
          type="date"
          value={custom}
          onChange={(event) => setCustom(event.target.value)}
          className="rounded-sm border border-line bg-surface px-1.5 py-1 text-sm text-fg"
          aria-label="Pick the date"
        />
        <Button
          size="sm"
          className="h-7 text-2xs"
          disabled={!custom}
          onClick={() => onChoose(custom)}
        >
          That one
        </Button>
        <Button size="sm" variant="ghost" className="h-7 text-2xs" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

export default IntelligencePanel;
