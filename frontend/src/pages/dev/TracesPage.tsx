import { Clock, Coins, Hash, Loader2, Wrench } from "lucide-react";
import { useEffect, useState } from "react";

import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { Skeleton } from "@/components/common/Skeleton";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { runs as runsApi } from "@/services/api";
import type { AgentRun, AgentRunDetail, BudgetStanding } from "@/types/api";

/**
 * The internal traces view. Not a P0 screen, and deliberately not pretty.
 *
 * It exists because the first time an agent says something wrong, the only
 * useful question is "what did it actually do", and the only useful answer
 * is a step list with tokens and cost (gaps C1, B4).
 *
 * Tool results show as a digest and a byte count. Printing the content
 * would make this a second way to read the mailbox, in a screen nobody
 * thinks of as holding mail (gap D8).
 */
function money(micros: number): string {
  return micros === 0 ? "free" : `${(micros / 1_000_000).toFixed(4)}`;
}

const STATUS_VARIANT: Record<AgentRun["status"], "success" | "danger" | "warning" | "neutral"> = {
  queued: "neutral",
  running: "neutral",
  awaiting_approval: "warning",
  succeeded: "success",
  failed: "danger",
  cancelled: "neutral",
  budget_denied: "warning",
  cap_exceeded: "warning",
};

function RunRow({
  run,
  selected,
  onSelect,
}: {
  run: AgentRun;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(run.id)}
      className={`flex w-full items-center gap-2 border-b border-line px-s2 py-1.5 text-left text-sm transition-colors ${
        selected ? "bg-violet-subtle" : "hover:bg-surface-sunken"
      }`}
    >
      <Badge variant={STATUS_VARIANT[run.status]}>{run.status}</Badge>
      <span className="min-w-0 flex-1 truncate font-mono text-xs text-fg">
        {run.agent_id}@{run.agent_version}
      </span>
      <Badge variant="neutral">plane {run.plane}</Badge>
      <span className="shrink-0 text-2xs tabular-nums text-fg-subtle">{run.step_count} steps</span>
      <span className="shrink-0 text-2xs tabular-nums text-fg-subtle">
        {money(run.cost_micros)}
      </span>
    </button>
  );
}

function Trace({ run }: { run: AgentRunDetail }) {
  return (
    <div className="flex flex-col gap-s2 p-s2">
      <div className="flex flex-wrap items-center gap-s1">
        <Badge variant={STATUS_VARIANT[run.status]}>{run.status}</Badge>
        <span className="font-mono text-xs text-fg">
          {run.agent_id}@{run.agent_version}
        </span>
        <Badge variant="neutral">plane {run.plane}</Badge>
        <Badge variant="neutral">{run.trigger}</Badge>
      </div>

      <div className="grid grid-cols-2 gap-s1 sm:grid-cols-4">
        {[
          { icon: Hash, label: "steps", value: String(run.step_count) },
          {
            icon: Coins,
            label: "cost",
            value: money(run.cost_micros),
          },
          {
            icon: Wrench,
            label: "tokens in / out",
            value: `${run.input_tokens} / ${run.output_tokens}`,
          },
          {
            icon: Clock,
            label: "cached in",
            value: String(run.cached_input_tokens),
          },
        ].map(({ icon: Icon, label, value }) => (
          <div key={label} className="rounded-sm border border-line bg-surface-sunken p-1.5">
            <p className="flex items-center gap-1 text-2xs text-fg-subtle">
              <Icon className="size-3" aria-hidden />
              {label}
            </p>
            <p className="font-mono text-sm tabular-nums text-fg">{value}</p>
          </div>
        ))}
      </div>

      {run.error ? (
        <pre className="overflow-x-auto rounded-sm border border-danger-border bg-danger p-1.5 font-mono text-2xs text-danger-fg">
          {JSON.stringify(run.error, null, 2)}
        </pre>
      ) : null}

      {run.output ? (
        <pre className="overflow-x-auto rounded-sm border border-line bg-surface-sunken p-1.5 font-mono text-2xs text-fg">
          {JSON.stringify(run.output, null, 2)}
        </pre>
      ) : null}

      <Separator />

      <ol className="flex flex-col">
        {run.steps.map((step) => (
          <li
            key={step.seq}
            className="flex items-start gap-2 border-b border-line py-1.5 text-2xs"
          >
            <span className="w-6 shrink-0 text-right font-mono tabular-nums text-fg-subtle">
              {step.seq}
            </span>
            <Badge variant={step.kind === "tool" ? "violet" : "ai"}>{step.kind}</Badge>
            <span className="min-w-0 flex-1">
              {step.tool_name ? (
                <>
                  <span className="font-mono text-fg">{step.tool_name}</span>
                  {step.tool_args ? (
                    <span className="ml-1 font-mono text-fg-subtle">
                      {JSON.stringify(step.tool_args).slice(0, 120)}
                    </span>
                  ) : null}
                  {/* A digest, never the result. */}
                  {step.tool_result_digest ? (
                    <span className="ml-1 font-mono text-fg-subtle">
                      → sha256 {step.tool_result_digest.slice(0, 12)} ({step.tool_result_bytes}B)
                    </span>
                  ) : null}
                </>
              ) : (
                <span className="text-fg-muted">
                  model call · {step.input_tokens ?? 0} in / {step.output_tokens ?? 0} out
                </span>
              )}
            </span>
            <span className="shrink-0 tabular-nums text-fg-subtle">{step.latency_ms ?? 0}ms</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function TracesPage() {
  const [list, setList] = useState<AgentRun[] | null>(null);
  const [selected, setSelected] = useState<AgentRunDetail | null>(null);
  const [budget, setBudget] = useState<BudgetStanding | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setError(null);
    void runsApi
      .list()
      .then(setList)
      .catch((caught: unknown) =>
        setError(caught instanceof Error ? caught.message : "Could not load runs"),
      );
    void runsApi
      .budget()
      .then(setBudget)
      .catch(() => undefined);
  };

  useEffect(load, []);

  const open = (id: string) => {
    void runsApi
      .read(id)
      .then(setSelected)
      .catch(() => undefined);
  };

  if (error) return <ErrorState description={error} onRetry={load} />;

  return (
    <div className="mx-auto w-full max-w-4xl px-s3 py-s3">
      <h2 className="font-brand text-xl font-semibold text-fg">Agent runs</h2>
      <p className="mt-1 text-base text-fg-muted">
        Internal. Every run, every step, what it cost. Tool results appear as a hash, never as their
        content.
      </p>

      {budget ? (
        <p className="mt-s2 text-sm text-fg-muted">
          This month: <span className="font-mono">{money(budget.spent_micros)}</span> of{" "}
          <span className="font-mono">{money(budget.hard_cap_micros)}</span>
          {budget.state !== "ok" ? (
            <Badge variant="warning" className="ml-1.5">
              {budget.state}
            </Badge>
          ) : null}
        </p>
      ) : null}

      <Card className="mt-s3 overflow-hidden">
        {list === null ? (
          <div role="status" aria-busy="true" className="p-s2">
            <span className="sr-only">Loading runs</span>
            <Skeleton className="h-6" />
          </div>
        ) : list.length === 0 ? (
          <EmptyState
            icon={Loader2}
            title="No runs yet"
            description="Open a thread and ask Maail to look at it; the trace appears here."
          />
        ) : (
          list.map((run) => (
            <RunRow key={run.id} run={run} selected={selected?.id === run.id} onSelect={open} />
          ))
        )}
      </Card>

      {selected ? (
        <Card className="mt-s3">
          <Trace run={selected} />
        </Card>
      ) : null}
    </div>
  );
}

export default TracesPage;
