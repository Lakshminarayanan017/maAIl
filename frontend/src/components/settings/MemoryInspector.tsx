import { Brain, Check, ShieldAlert, Trash2, TriangleAlert, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/common/EmptyState";
import { Skeleton } from "@/components/common/Skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { memory as memoryApi } from "@/services/api";
import type { Fact, MemoryConflict, MemoryRejection } from "@/types/api";

/**
 * The memory inspector (08-ui-spec.md, screen 10; phase 10).
 *
 * > Users must be able to inspect, edit and delete these stored
 * > preferences and memories.
 *
 * Every row shows what is remembered, where it came from, the words it
 * came from, whether it has been confirmed, and when it expires. A memory
 * whose provenance the user cannot see is one they have to either trust
 * blindly or wipe wholesale.
 *
 * Three sections, and the third is the one worth having:
 *
 * **Conflicts** — a new observation contradicting a stored fact. Nothing
 * was written; the two are shown side by side and the user picks.
 * Silently replacing what they confirmed with what an email implied is
 * how memory stops being theirs.
 *
 * **Refused** — what the promoter rejected and why. A run of "reads as an
 * instruction" is an email trying to write itself into the user's memory,
 * and this is where that becomes visible instead of vanishing.
 */
const TYPE_LABEL: Record<Fact["fact_type"], string> = {
  preference: "How you like things",
  interest: "What you work with",
  relationship: "Who you deal with",
  project_fact: "About your projects",
};

const REJECTION_LABEL: Record<string, string> = {
  rejected_policy: "Not a storable kind of fact",
  rejected_no_evidence: "Nothing to point at",
  rejected_duplicate: "Already known",
};

function FactRow({
  fact,
  onConfirm,
  onReject,
  onDelete,
  busy,
}: {
  fact: Fact;
  onConfirm: (fact: Fact) => void;
  onReject: (fact: Fact) => void;
  onDelete: (fact: Fact) => void;
  busy: boolean;
}) {
  const confirmed = fact.confirmation_status === "user_confirmed";
  const rejected = fact.confirmation_status === "user_rejected";

  return (
    <div className="flex items-start gap-2 rounded-sm border border-line bg-surface px-s2 py-1.5">
      <div className="min-w-0 flex-1">
        <p className={rejected ? "text-base text-fg-subtle line-through" : "text-base text-fg"}>
          {fact.content}
        </p>

        <p className="mt-0.5 flex flex-wrap items-center gap-1">
          {/* Confirmed facts are the user's, so they are violet rather
              than lavender: once a person has decided, it stops being an
              estimate and must stop looking like one. */}
          {confirmed ? (
            <Badge variant="violet">
              <Check className="size-2.5" aria-hidden />
              You confirmed this
            </Badge>
          ) : rejected ? (
            <Badge variant="neutral">You rejected this</Badge>
          ) : (
            <Badge variant="ai">Maail inferred this</Badge>
          )}
          <span className="text-2xs text-fg-subtle">
            {fact.observation_count === 1 ? "seen once" : `seen ${fact.observation_count} times`}
            {" · "}
            {fact.confidence_band} confidence
            {fact.expires_at
              ? ` · forgotten ${new Date(fact.expires_at).toLocaleDateString(undefined, {
                  day: "numeric",
                  month: "short",
                })} unless seen again`
              : " · kept indefinitely"}
          </span>
        </p>

        {fact.quote ? (
          <q className="mt-0.5 block border-l-2 border-ai-border pl-1.5 text-2xs italic text-fg-muted">
            {fact.quote}
          </q>
        ) : fact.source === "agent_inferred" ? (
          // The span was stored and no longer points anywhere — the
          // message was deleted, or the offsets were wrong. Saying so is
          // better than showing nothing.
          <p className="mt-0.5 text-2xs text-fg-subtle">
            The message this came from is no longer available.
          </p>
        ) : null}
      </div>

      <div className="flex shrink-0 gap-0.5">
        {!confirmed ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label="Confirm this"
                disabled={busy}
                onClick={() => onConfirm(fact)}
              >
                <Check aria-hidden />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Confirm — it will stop expiring</TooltipContent>
          </Tooltip>
        ) : null}
        {!rejected ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label="Reject this"
                disabled={busy}
                onClick={() => onReject(fact)}
              >
                <X aria-hidden />
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              Wrong — Maail stops using it and will not infer it again
            </TooltipContent>
          </Tooltip>
        ) : null}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size="icon-sm"
              variant="ghost"
              aria-label="Forget this entirely"
              disabled={busy}
              onClick={() => onDelete(fact)}
            >
              <Trash2 aria-hidden />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Forget it entirely — Maail may learn it again</TooltipContent>
        </Tooltip>
      </div>
    </div>
  );
}

export function MemoryInspector() {
  const [facts, setFacts] = useState<Fact[] | null>(null);
  const [conflicts, setConflicts] = useState<MemoryConflict[]>([]);
  const [rejections, setRejections] = useState<MemoryRejection[]>([]);
  const [showRejected, setShowRejected] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    void Promise.all([
      memoryApi.facts(showRejected),
      memoryApi.conflicts(),
      memoryApi.rejections(),
    ]).then(([listed, conflicted, refused]) => {
      setFacts(listed);
      setConflicts(conflicted);
      setRejections(refused);
    });
  }, [showRejected]);

  useEffect(load, [load]);

  const act = (id: string, work: Promise<unknown>) => {
    setBusy(id);
    void work.then(() => load()).finally(() => setBusy(null));
  };

  const grouped = (Object.keys(TYPE_LABEL) as Fact["fact_type"][])
    .map((kind) => ({
      kind,
      items: (facts ?? []).filter((fact) => fact.fact_type === kind),
    }))
    .filter((group) => group.items.length > 0);

  return (
    <section>
      <h2 className="flex items-center gap-1.5 font-brand text-xl font-semibold text-fg">
        <Brain className="size-4 text-violet" aria-hidden />
        What Maail remembers
      </h2>
      <p className="mt-1 text-base text-fg-muted">
        Things about you, not instructions about what Maail does. Nothing here can change how it
        behaves.
      </p>

      {conflicts.length > 0 ? (
        <div className="mt-s3 flex flex-col gap-1.5">
          <h3 className="flex items-center gap-1.5 font-brand text-base font-semibold text-warning-fg">
            <TriangleAlert className="size-3.5" aria-hidden />
            Maail needs you to choose
          </h3>
          {conflicts.map((conflict) => (
            <div
              key={conflict.proposal_id}
              className="flex flex-col gap-1.5 rounded-sm border border-warning-border bg-warning px-s2 py-1.5"
            >
              <p className="text-2xs uppercase tracking-wide text-warning-fg/80">
                {conflict.subject}
              </p>
              <p className="text-base text-warning-fg">
                Stored: <q className="italic">{conflict.stored_content}</q>
              </p>
              <p className="text-base text-warning-fg">
                New: <q className="italic">{conflict.proposed_content}</q>
              </p>
              <div className="flex gap-1">
                <Button
                  size="sm"
                  variant="secondary"
                  className="h-7 text-2xs"
                  onClick={() =>
                    act(
                      conflict.proposal_id,
                      memoryApi.resolveConflict(conflict.proposal_id, "stored"),
                    )
                  }
                >
                  Keep the stored one
                </Button>
                <Button
                  size="sm"
                  className="h-7 text-2xs"
                  onClick={() =>
                    act(
                      conflict.proposal_id,
                      memoryApi.resolveConflict(conflict.proposal_id, "proposed"),
                    )
                  }
                >
                  Take the new one
                </Button>
              </div>
            </div>
          ))}
        </div>
      ) : null}

      <div className="mt-s3 flex flex-col gap-s2">
        {!facts ? (
          <div className="flex flex-col gap-1.5">
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
          </div>
        ) : grouped.length === 0 ? (
          <EmptyState
            icon={Brain}
            title="Nothing remembered yet"
            description="Maail notes things like how you prefer replies written, and only when it can point at where it saw them."
          />
        ) : (
          grouped.map((group) => (
            <div key={group.kind} className="flex flex-col gap-1">
              <h3 className="text-2xs uppercase tracking-wide text-fg-subtle">
                {TYPE_LABEL[group.kind]}
              </h3>
              {group.items.map((fact) => (
                <FactRow
                  key={fact.id}
                  fact={fact}
                  busy={busy === fact.id}
                  onConfirm={(target) => act(target.id, memoryApi.confirm(target.id))}
                  onReject={(target) => act(target.id, memoryApi.reject(target.id))}
                  onDelete={(target) => act(target.id, memoryApi.remove(target.id))}
                />
              ))}
            </div>
          ))
        )}
      </div>

      <Button
        size="sm"
        variant="ghost"
        className="mt-s2"
        onClick={() => setShowRejected((previous) => !previous)}
      >
        {showRejected ? "Hide rejected" : "Show what you rejected"}
      </Button>

      {rejections.length > 0 ? (
        <div className="mt-s3">
          <h3 className="flex items-center gap-1.5 font-brand text-base font-semibold text-fg">
            <ShieldAlert className="size-3.5 text-fg-muted" aria-hidden />
            Refused
          </h3>
          <p className="mt-0.5 text-sm text-fg-muted">
            Things Maail was asked to remember and would not. Mostly text in emails trying to change
            what it does.
          </p>
          <div className="mt-s2 flex flex-col gap-1">
            {rejections.slice(0, 10).map((rejection) => (
              <div
                key={rejection.id}
                className="rounded-sm border border-line bg-surface-sunken px-s2 py-1.5"
              >
                <p className="text-sm text-fg-muted">
                  <q className="italic">{rejection.content}</q>
                </p>
                <p className="mt-0.5 text-2xs text-fg-subtle">
                  {REJECTION_LABEL[rejection.status] ?? rejection.status}
                  {rejection.rejection_reason ? ` — ${rejection.rejection_reason}` : ""}
                </p>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

export default MemoryInspector;
