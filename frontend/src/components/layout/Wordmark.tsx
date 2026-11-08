import { cn } from "@/lib/utils";

/**
 * The brand mark, set as the spec draws it on screens 01 and 02: `maail.`
 * lowercase, with the full stop in Maail violet.
 *
 * `badge` renders the square M used in the collapsed rail, where a wordmark
 * would not fit.
 */
export function Wordmark({
  size = "md",
  badge = false,
  compact = false,
  className,
}: {
  size?: "md" | "lg";
  badge?: boolean;
  /** Collapsed rail: the badge alone. */
  compact?: boolean;
  className?: string;
}) {
  const showBadge = badge || compact;

  return (
    <span
      className={cn("flex select-none items-center gap-2 font-brand", className)}
      aria-label="Maail"
    >
      {showBadge ? (
        <span
          aria-hidden
          className="flex size-7 shrink-0 items-center justify-center rounded-sm bg-violet text-sm font-bold text-fg-on-violet"
        >
          M
        </span>
      ) : null}
      {compact ? null : (
        <span
          aria-hidden
          className={cn("font-bold tracking-tight text-fg", size === "lg" ? "text-2xl" : "text-lg")}
        >
          maail<span className="text-violet">.</span>
        </span>
      )}
    </span>
  );
}
