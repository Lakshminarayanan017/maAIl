import { Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { featureSettings } from "@/services/api";

/**
 * Entry point C — the contextual suggestion.
 *
 * > contextual suggestions, e.g. "Want Maail to automatically identify
 * > upcoming deadlines?" (08-ui-spec.md §10)
 *
 * It appears where the missing capability would have been useful, which
 * is the only place a suggestion like this is not an interruption: on the
 * tasks screen when deadline detection is off, not as a banner on every
 * page.
 *
 * Two rules it keeps:
 *
 * **It never appears for something already on**, so it checks before it
 * renders and shows nothing while it is checking. A card that flickers in
 * and out is worse than no card.
 *
 * **"Not now" means not now.** Dismissal is remembered per browser so the
 * same question is not asked on every visit. It is deliberately not
 * stored server-side: a permanent record of a declined suggestion is a
 * setting the user never asked to create.
 */
const DISMISSED_KEY = "maail.suggestions.dismissed";

function readDismissed(): Set<string> {
  try {
    const raw = window.localStorage.getItem(DISMISSED_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    // Private windows and blocked storage both land here. Showing the
    // suggestion is the safe failure: the user can dismiss it again.
    return new Set();
  }
}

function remember(featureId: string): void {
  try {
    const all = readDismissed();
    all.add(featureId);
    window.localStorage.setItem(DISMISSED_KEY, JSON.stringify([...all]));
  } catch {
    /* nothing to do; the card simply returns next visit */
  }
}

export interface FeatureSuggestionProps {
  featureId: string;
  /** The question, in the user's terms. */
  question: string;
  className?: string;
  onEnabled?: () => void;
}

export function FeatureSuggestion({
  featureId,
  question,
  className,
  onEnabled,
}: FeatureSuggestionProps) {
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [alsoChanged, setAlsoChanged] = useState<string[]>([]);

  const check = useCallback(() => {
    if (readDismissed().has(featureId)) return;
    void featureSettings.read().then((settings) => {
      const feature = settings.groups
        .flatMap((group) => group.features)
        .find((item) => item.id === featureId);
      // Only offered when it is genuinely off and genuinely available.
      setShow(Boolean(feature && !feature.enabled && feature.live));
    });
  }, [featureId]);

  useEffect(check, [check]);

  if (!show) return null;

  const enable = () => {
    setBusy(true);
    void featureSettings
      .set(featureId, { enabled: true })
      .then((change) => {
        setAlsoChanged(change.also_changed);
        setShow(false);
        onEnabled?.();
      })
      .finally(() => setBusy(false));
  };

  const dismiss = () => {
    remember(featureId);
    setShow(false);
  };

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2 rounded-sm border border-ai-border bg-ai px-s2 py-1.5",
        className,
      )}
    >
      <Sparkles className="size-3.5 shrink-0 text-ai-fg" aria-hidden />
      <p className="min-w-0 flex-1 text-base text-ai-fg">{question}</p>
      {alsoChanged.length > 0 ? (
        <span className="text-2xs text-ai-fg/80">
          Also turned on {alsoChanged.length} related feature
          {alsoChanged.length === 1 ? "" : "s"}.
        </span>
      ) : null}
      <Button size="sm" className="h-7 text-2xs" disabled={busy} onClick={enable}>
        Turn it on
      </Button>
      <Button
        size="icon-sm"
        variant="ghost"
        aria-label="Not now"
        onClick={dismiss}
        className="text-ai-fg"
      >
        <X aria-hidden />
      </Button>
    </div>
  );
}

export default FeatureSuggestion;
