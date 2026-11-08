import {
  Bell,
  CalendarClock,
  Check,
  CircleHelp,
  ListChecks,
  Mail,
  Plus,
  Sparkles,
  StickyNote,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { Skeleton } from "@/components/common/Skeleton";
import { ProvenanceMark } from "@/components/intelligence/Provenance";
import { FeatureSuggestion } from "@/components/settings/FeatureSuggestion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { tasks as tasksApi } from "@/services/api";
import { useInbox } from "@/stores/inbox";
import type { AmbiguousDeadline, Suggestion, Task, TaskPage } from "@/types/api";

/**
 * Screen 09 — Tasks & Deadlines.
 *
 *     [All] [Today] [Upcoming] [Completed]
 *
 *     TODAY
 *     □ Reply to internship recruiter
 *       From: Recruitment Team · Due: Today
 *
 * Three distinctions this screen exists to hold, each of which a simpler
 * task list would collapse:
 *
 * **A suggestion is not a task.** Extracted action items sit in their own
 * section until someone accepts one. A list that mixed them would be
 * Maail deciding what the user owes other people.
 *
 * **An ambiguous date is a question.** *"'by Friday' — which Friday?"*,
 * with the sender's phrase quoted and no date shown, because none was
 * resolved and inventing one is the failure that makes the whole feature
 * untrustworthy.
 *
 * **Stated and inferred stay apart.** A request someone actually wrote
 * and Maail's reading of what follows are different claims, marked
 * differently, everywhere they appear.
 *
 * No model runs to open, filter or complete anything here. The judgements
 * were made when the thread was analysed; this is a query over them.
 */
const FILTERS: { value: "all" | "today" | "upcoming" | "completed"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "today", label: "Today" },
  { value: "upcoming", label: "Upcoming" },
  { value: "completed", label: "Completed" },
];

function dueLabel(due: string | null): string {
  if (!due) return "no date";
  const date = new Date(due);
  const today = new Date();
  const sameDay =
    date.getFullYear() === today.getFullYear() &&
    date.getMonth() === today.getMonth() &&
    date.getDate() === today.getDate();
  if (sameDay) return "Today";
  return date.toLocaleDateString(undefined, { day: "numeric", month: "long" });
}

function TaskRow({
  task,
  onToggle,
  onNote,
  onRemind,
}: {
  task: Task;
  onToggle: (task: Task) => void;
  onNote: (task: Task) => void;
  onRemind: (task: Task) => void;
}) {
  const select = useInbox((state) => state.select);
  const navigate = useNavigate();
  const done = task.status === "done";

  const openSource = () => {
    if (!task.thread_id) return;
    void select(task.thread_id);
    void navigate("/inbox");
  };

  return (
    <div className="flex items-start gap-2 rounded-sm border border-line bg-surface px-s2 py-1.5">
      <button
        type="button"
        role="checkbox"
        aria-checked={done}
        aria-label={done ? `Reopen ${task.title}` : `Complete ${task.title}`}
        onClick={() => onToggle(task)}
        className="border-border-strong mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-sm border bg-surface transition-colors hover:border-violet"
      >
        {done ? <Check className="size-3 text-violet" aria-hidden /> : null}
      </button>

      <div className="min-w-0 flex-1">
        <p className={done ? "text-base text-fg-subtle line-through" : "text-base text-fg"}>
          {task.title}
        </p>

        <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-2xs text-fg-subtle">
          {task.thread_subject ? (
            <button
              type="button"
              onClick={openSource}
              className="inline-flex items-center gap-1 underline-offset-2 hover:underline"
            >
              <Mail className="size-2.5" aria-hidden />
              From: {task.source_sender ?? task.thread_subject}
            </button>
          ) : null}
          <span aria-hidden>&middot;</span>
          <span>Due: {dueLabel(task.due_at)}</span>

          {/* Where the date came from. A date lifted from a sender's
              sentence and one the user typed are not the same thing. */}
          {task.deadline_phrase ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex items-center gap-1">
                  <ProvenanceMark
                    provenance={
                      task.deadline_resolution === "user_confirmed" ||
                      task.deadline_resolution === "user_corrected"
                        ? "stated"
                        : "interpreted"
                    }
                  />
                  <q className="italic">{task.deadline_phrase}</q>
                </span>
              </TooltipTrigger>
              <TooltipContent>
                {task.deadline_resolution === "user_corrected"
                  ? "You corrected this date."
                  : task.deadline_resolution === "user_confirmed"
                    ? "You confirmed this date."
                    : "Maail read this date out of the email."}
              </TooltipContent>
            </Tooltip>
          ) : null}

          {task.origin === "ai_suggestion" ? (
            <Badge variant="violet">You accepted this</Badge>
          ) : null}
        </p>

        {task.notes ? (
          <p className="mt-0.5 rounded-sm bg-surface-sunken px-1.5 py-1 text-2xs text-fg-muted">
            {task.notes}
          </p>
        ) : null}
        {task.remind_at ? (
          <p className="mt-0.5 inline-flex items-center gap-1 text-2xs text-fg-subtle">
            <Bell className="size-2.5" aria-hidden />
            Reminder set for{" "}
            {new Date(task.remind_at).toLocaleString(undefined, {
              day: "numeric",
              month: "short",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </p>
        ) : null}
      </div>

      <div className="flex shrink-0 gap-0.5">
        <Button size="icon-sm" variant="ghost" aria-label="Add a note" onClick={() => onNote(task)}>
          <StickyNote aria-hidden />
        </Button>
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label="Set a reminder"
          onClick={() => onRemind(task)}
        >
          <Bell aria-hidden />
        </Button>
      </div>
    </div>
  );
}

function SuggestionRow({
  suggestion,
  onAccept,
  onDismiss,
  busy,
}: {
  suggestion: Suggestion;
  onAccept: (suggestion: Suggestion) => void;
  onDismiss: (suggestion: Suggestion) => void;
  busy: boolean;
}) {
  return (
    <div className="flex items-start gap-2 rounded-sm border border-ai-border bg-ai/40 px-s2 py-1.5">
      <ProvenanceMark
        provenance={suggestion.source === "stated" ? "stated" : "interpreted"}
        className="mt-0.5"
      />
      <div className="min-w-0 flex-1">
        <p className="text-base text-fg">{suggestion.description}</p>
        <p className="mt-0.5 text-2xs text-fg-subtle">
          {/* Never merged. */}
          {suggestion.source === "stated"
            ? "They asked for this"
            : "Maail inferred this from the thread"}
          {suggestion.sender ? ` · ${suggestion.sender}` : ""}
        </p>
        {suggestion.quote ? (
          <q className="mt-0.5 block border-l-2 border-ai-border pl-1.5 text-2xs italic text-fg-muted">
            {suggestion.quote}
          </q>
        ) : null}
      </div>
      <div className="flex shrink-0 gap-1">
        <Button
          size="sm"
          className="h-6 text-2xs"
          disabled={busy}
          onClick={() => onAccept(suggestion)}
        >
          <Plus className="size-3" aria-hidden />
          Add
        </Button>
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label="Not a task"
          onClick={() => onDismiss(suggestion)}
        >
          <X aria-hidden />
        </Button>
      </div>
    </div>
  );
}

/**
 * The deadline ambiguity resolver.
 *
 * It quotes and asks. The options were computed from the message's send
 * date by code; none of them is preselected, because a default here is
 * the guess this component exists to avoid.
 */
function AmbiguousRow({
  deadline,
  onResolve,
}: {
  deadline: AmbiguousDeadline;
  onResolve: (deadline: AmbiguousDeadline, chosen: string) => void;
}) {
  const [custom, setCustom] = useState("");

  return (
    <div className="flex flex-col gap-1.5 rounded-sm border border-warning-border bg-warning px-s2 py-1.5">
      <p className="flex items-start gap-1.5 text-base text-warning-fg">
        <CircleHelp className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        <span>
          <q className="italic">{deadline.raw_phrase}</q> &mdash; which one?
        </span>
      </p>
      <p className="text-2xs text-warning-fg/80">
        {deadline.sender ? `${deadline.sender} · ` : ""}
        {deadline.thread_subject ?? "a thread in your mail"}
      </p>

      <div className="flex flex-wrap items-center gap-1">
        {deadline.options.map((option) => (
          <Button
            key={option}
            size="sm"
            variant="secondary"
            className="h-7 text-2xs"
            onClick={() => onResolve(deadline, option)}
          >
            {new Date(`${option}T12:00:00`).toLocaleDateString(undefined, {
              weekday: "short",
              day: "numeric",
              month: "short",
            })}
          </Button>
        ))}
        <input
          type="date"
          value={custom}
          onChange={(event) => setCustom(event.target.value)}
          aria-label={`Pick a date for "${deadline.raw_phrase}"`}
          className="rounded-sm border border-line bg-surface px-1.5 py-1 text-sm text-fg"
        />
        {custom ? (
          <Button size="sm" className="h-7 text-2xs" onClick={() => onResolve(deadline, custom)}>
            That one
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export function TasksPage() {
  const [filter, setFilter] = useState<"all" | "today" | "upcoming" | "completed">("all");
  const [page, setPage] = useState<TaskPage | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [ambiguous, setAmbiguous] = useState<AmbiguousDeadline[]>([]);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");

  const load = useCallback(() => {
    setError(null);
    return Promise.all([tasksApi.list(filter), tasksApi.suggestions(), tasksApi.ambiguous()])
      .then(([listed, suggested, unclear]) => {
        setPage(listed);
        setSuggestions(suggested);
        setAmbiguous(unclear);
      })
      .catch((caught: unknown) =>
        setError(caught instanceof Error ? caught.message : "Could not load your tasks"),
      );
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = (task: Task) => {
    void tasksApi
      .update(task.id, { status: task.status === "done" ? "pending" : "done" })
      .then(() => load());
  };

  const accept = (suggestion: Suggestion) => {
    setBusy(suggestion.action_item_id);
    void tasksApi
      .confirm(suggestion.action_item_id)
      .then(() => load())
      .finally(() => setBusy(null));
  };

  const dismiss = (suggestion: Suggestion) => {
    // Hidden locally rather than written away. Dismissing a suggestion is
    // not the same as marking the sender's request done, and there is no
    // endpoint for the first yet, so this does not pretend there is.
    setDismissed((previous) => new Set(previous).add(suggestion.action_item_id));
  };

  const note = (task: Task) => {
    const text = window.prompt("Note for this task", task.notes ?? "");
    if (text === null) return;
    void tasksApi.update(task.id, { notes: text }).then(() => load());
  };

  const remind = (task: Task) => {
    const when = window.prompt(
      "Remind me on (YYYY-MM-DD)",
      task.remind_at ? task.remind_at.slice(0, 10) : "",
    );
    if (!when) return;
    void tasksApi
      .update(task.id, { remind_at: new Date(`${when}T09:00:00`).toISOString() })
      .then(() => load());
  };

  const resolve = (deadline: AmbiguousDeadline, chosen: string) => {
    void tasksApi.resolveDeadline(deadline.deadline_id, chosen, false).then(() => load());
  };

  const create = () => {
    const title = newTitle.trim();
    if (!title) return;
    setNewTitle("");
    void tasksApi.create({ title }).then(() => load());
  };

  if (error) return <ErrorState description={error} onRetry={() => void load()} />;

  const visible = suggestions.filter((item) => !dismissed.has(item.action_item_id));

  return (
    <div className="mx-auto w-full max-w-3xl px-s3 py-s3">
      <h2 className="font-brand text-2xl font-bold text-fg">Tasks &amp; Deadlines</h2>
      <p className="mt-0.5 text-md text-fg-muted">Your pending actions</p>

      {/* Entry point C, and the spec's own example. It appears here
          because this is the screen where the missing capability would
          have helped, not as a banner on every page. */}
      <FeatureSuggestion
        className="mt-s3"
        featureId="deadline_detection"
        question="Want Maail to automatically identify upcoming deadlines?"
        onEnabled={() => void load()}
      />

      <div className="mt-s3 flex flex-wrap gap-1">
        {FILTERS.map((option) => (
          <Button
            key={option.value}
            size="sm"
            variant={filter === option.value ? "secondary" : "ghost"}
            onClick={() => setFilter(option.value)}
          >
            {option.label}
            {page ? (
              <span className="ml-1 tabular-nums text-fg-subtle">{page.counts[option.value]}</span>
            ) : null}
          </Button>
        ))}
      </div>

      {/* The resolver sits at the top because an unanswered question is
          the one thing here that blocks the rest from being right. */}
      {ambiguous.length > 0 ? (
        <section className="mt-s3">
          <h3 className="font-brand text-lg font-semibold text-fg">
            Maail needs you to say which day
          </h3>
          <p className="mt-0.5 text-sm text-fg-muted">
            These phrases name a day, and more than one day fits. Nothing was guessed.
          </p>
          <div className="mt-s2 flex flex-col gap-1.5">
            {ambiguous.map((deadline) => (
              <AmbiguousRow key={deadline.deadline_id} deadline={deadline} onResolve={resolve} />
            ))}
          </div>
        </section>
      ) : null}

      {visible.length > 0 ? (
        <section className="mt-s3">
          <h3 className="flex items-center gap-1.5 font-brand text-lg font-semibold text-fg">
            <Sparkles className="size-4 text-violet" aria-hidden />
            Maail found these in your mail
          </h3>
          <p className="mt-0.5 text-sm text-fg-muted">Not on your list until you add them.</p>
          <div className="mt-s2 flex flex-col gap-1.5">
            {visible.map((suggestion) => (
              <SuggestionRow
                key={suggestion.action_item_id}
                suggestion={suggestion}
                busy={busy === suggestion.action_item_id}
                onAccept={accept}
                onDismiss={dismiss}
              />
            ))}
          </div>
        </section>
      ) : null}

      <Separator className="my-s3" />

      <form
        className="flex gap-1"
        onSubmit={(event) => {
          event.preventDefault();
          create();
        }}
      >
        <input
          value={newTitle}
          onChange={(event) => setNewTitle(event.target.value)}
          placeholder="Add a task of your own"
          aria-label="Add a task"
          className="flex-1 rounded-sm border border-line bg-surface px-s2 py-1.5 text-base text-fg outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <Button type="submit" size="sm" disabled={newTitle.trim().length === 0}>
          <Plus aria-hidden />
          Add
        </Button>
      </form>

      <section className="mt-s3">
        {!page ? (
          <div className="flex flex-col gap-1.5">
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </div>
        ) : page.items.length === 0 ? (
          <EmptyState
            icon={filter === "completed" ? Check : ListChecks}
            title={filter === "completed" ? "Nothing completed yet" : "Nothing on your list"}
            description={
              filter === "completed"
                ? "Tasks you finish will collect here."
                : "Add one above, or accept something Maail found in your mail."
            }
          />
        ) : (
          <div className="flex flex-col gap-1.5">
            <h3 className="text-2xs uppercase tracking-wide text-fg-subtle">
              {filter === "completed"
                ? "Completed"
                : filter === "today"
                  ? "Today"
                  : filter === "upcoming"
                    ? "Upcoming"
                    : "All pending"}
            </h3>
            {page.items.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                onToggle={toggle}
                onNote={note}
                onRemind={remind}
              />
            ))}
          </div>
        )}
      </section>

      {page && page.counts.all === 0 && visible.length === 0 && ambiguous.length === 0 ? (
        <p className="mt-s3 inline-flex items-center gap-1.5 text-2xs text-fg-subtle">
          <CalendarClock className="size-3" aria-hidden />
          Deadlines and action items appear here once a thread has been analysed.
        </p>
      ) : null}
    </div>
  );
}

export default TasksPage;
