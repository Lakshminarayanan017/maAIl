import { Link2, Quote, Sparkles } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { Evidence, Provenance as ProvenanceKind } from "@/types/api";

/**
 * The three provenance classes, as three visibly different things.
 *
 * > The user should always be able to distinguish: Information explicitly
 * > present in the email. AI-generated interpretations. Information
 * > retrieved from external integrations.
 * > (08-ui-spec.md, screen 05)
 *
 * Three classes need three treatments, not one treatment with three
 * labels — a reader scanning the panel should be able to tell them apart
 * without reading the word:
 *
 * `stated`       neutral surface, quote mark. The email says this.
 * `interpreted`  soft lavender, sparkle. A model concluded this.
 * `retrieved`    blue, link. This came from somewhere else.
 *
 * Soft lavender stays reserved for `interpreted` (08-ui-spec.md §2), which
 * is why a fact lifted out of the email does not wear it and an
 * interpretation cannot avoid it.
 */
const PROVENANCE_LABEL: Record<ProvenanceKind, string> = {
  stated: "Said in the email",
  interpreted: "Maail worked this out",
  retrieved: "From elsewhere in your mail",
};

const PROVENANCE_STYLE: Record<ProvenanceKind, string> = {
  stated: "border-line bg-surface-sunken text-fg",
  interpreted: "border-ai-border bg-ai text-ai-fg",
  retrieved: "border-info-border bg-info text-info-fg",
};

const PROVENANCE_ICON: Record<ProvenanceKind, typeof Quote> = {
  stated: Quote,
  interpreted: Sparkles,
  retrieved: Link2,
};

export function ProvenanceMark({
  provenance,
  className,
}: {
  provenance: ProvenanceKind;
  className?: string;
}) {
  const Icon = PROVENANCE_ICON[provenance];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "inline-flex size-4 shrink-0 items-center justify-center rounded-sm border",
            PROVENANCE_STYLE[provenance],
            className,
          )}
          aria-label={PROVENANCE_LABEL[provenance]}
        >
          <Icon className="size-2.5" aria-hidden />
        </span>
      </TooltipTrigger>
      <TooltipContent>{PROVENANCE_LABEL[provenance]}</TooltipContent>
    </Tooltip>
  );
}

/**
 * A value with its provenance and its source affordance.
 *
 * The rule the whole panel rests on: **no evidence, no value**. When
 * `evidence` is empty and the provenance claims the email said it, there
 * is nothing to show, so it shows nothing rather than a claim. An
 * interpretation with no span is still rendered — it is honestly labelled
 * as a conclusion — but it cannot pretend to be a quotation.
 */
export function ProvenanceValue({
  children,
  provenance,
  evidence = [],
  className,
}: {
  children: React.ReactNode;
  provenance: ProvenanceKind;
  evidence?: Evidence[];
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const quotable = evidence.filter((item) => item.quote);

  if (provenance === "stated" && quotable.length === 0) {
    // Claimed to be in the email, and nothing points at it. The honest
    // render is an absence.
    return <span className="text-2xs text-fg-subtle">Not determined</span>;
  }

  return (
    <span className={cn("flex min-w-0 flex-col gap-1", className)}>
      <span className="flex min-w-0 items-start gap-1.5">
        <ProvenanceMark provenance={provenance} className="mt-0.5" />
        <span className="min-w-0 flex-1 text-base text-fg">{children}</span>
      </span>

      {quotable.length > 0 ? (
        <>
          <Button
            size="sm"
            variant="ghost"
            className="h-5 self-start px-1 text-2xs"
            aria-expanded={open}
            onClick={() => setOpen((previous) => !previous)}
          >
            <Quote aria-hidden className="size-3" />
            {open ? "Hide source" : `Source${quotable.length > 1 ? ` (${quotable.length})` : ""}`}
          </Button>

          {open ? (
            <span className="flex flex-col gap-1 rounded-sm border border-line bg-surface-sunken p-1.5">
              {quotable.map((item) => (
                <span
                  key={`${item.message_id}-${item.char_start}`}
                  className="border-l-2 border-ai-border pl-1.5 text-2xs text-fg-muted"
                >
                  <q className="italic">{item.quote}</q>
                  {/* The offsets are shown because they are checkable.
                      A reader who wants to find the words can. */}
                  <span className="ml-1 font-mono text-fg-subtle">
                    {item.char_start}&ndash;{item.char_end}
                  </span>
                </span>
              ))}
            </span>
          ) : null}
        </>
      ) : null}
    </span>
  );
}

/** The legend. Three classes are only useful if the reader learns them once. */
export function ProvenanceLegend({ className }: { className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-center gap-x-s2 gap-y-1", className)}>
      {(["stated", "interpreted", "retrieved"] as ProvenanceKind[]).map((kind) => (
        <span key={kind} className="inline-flex items-center gap-1 text-2xs text-fg-subtle">
          <ProvenanceMark provenance={kind} />
          {PROVENANCE_LABEL[kind]}
        </span>
      ))}
    </div>
  );
}
