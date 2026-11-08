import { AlertTriangle, ChevronDown, ChevronRight, Code2, Image, Loader2 } from "lucide-react";
import { useState } from "react";

import { SandboxedHtml } from "@/components/thread/SandboxedHtml";
import { Button } from "@/components/ui/button";
import { SkeletonText } from "@/components/common/Skeleton";
import { threads as threadsApi } from "@/services/api";
import { cn } from "@/lib/utils";
import type { Message, MessageBody as MessageBodyPayload } from "@/types/api";

/**
 * One message's content, three ways.
 *
 * **Stripped text first.** It is what the agents read, it needs no Gmail
 * call, and it cannot execute anything. The quoted chain it removed is one
 * click away rather than gone.
 *
 * **Original formatting on request.** Fetched then, not on open: raw HTML
 * is never stored (gap E6), so each view costs a Gmail call, and most
 * messages never need one.
 *
 * **Images on request after that.** A remote image is a read receipt the
 * sender did not ask permission for.
 */
export interface MessageBodyProps {
  threadId: string;
  message: Message;
}

/** Code and stack traces get the mono face, as the spec requires (§3). */
const CODE_LINE = /^(?:\s{4,}|\t|[>$#]\s|(?:File "|Traceback|\s+at\s|Caused by:|\w+Error:))/;

function looksLikeCode(block: string): boolean {
  const lines = block.split("\n");
  if (lines.length < 2) return false;
  const hits = lines.filter((line) => CODE_LINE.test(line)).length;
  return hits / lines.length >= 0.5;
}

function TextBody({ text }: { text: string }) {
  // Split on blank lines so a traceback can take the mono face without
  // the prose around it going monospaced too.
  const blocks = text.split(/\n{2,}/);
  return (
    <div className="email-prose">
      {blocks.map((block, index) =>
        looksLikeCode(block) ? (
          <pre
            key={index}
            className="my-2 overflow-x-auto rounded-sm border border-line bg-surface-sunken p-2 font-mono text-xs leading-relaxed text-fg"
          >
            {block}
          </pre>
        ) : (
          <p key={index} className="my-2 whitespace-pre-wrap">
            {block}
          </p>
        ),
      )}
    </div>
  );
}

export function MessageBody({ threadId, message }: MessageBodyProps) {
  const [showQuoted, setShowQuoted] = useState(false);
  const [rich, setRich] = useState<MessageBodyPayload | null>(null);
  const [loadingRich, setLoadingRich] = useState(false);
  const [richError, setRichError] = useState<string | null>(null);

  if (!message.has_body) {
    return (
      <div className="mt-s2" role="status" aria-busy="true">
        <span className="sr-only">Fetching this message</span>
        <p className="mb-1.5 text-sm text-fg-subtle">
          {message.snippet ? `${message.snippet}…` : "Still fetching this message."}
        </p>
        <SkeletonText lines={3} />
      </div>
    );
  }

  const stripped = message.body_text_stripped ?? message.body_text ?? "";
  const full = message.body_text ?? "";
  const hasQuoted = full.length > stripped.length + 8;
  const savedPercent = message.stripped_ratio ? Math.round(message.stripped_ratio * 100) : 0;

  const loadRich = (images: "blocked" | "allowed") => {
    setLoadingRich(true);
    setRichError(null);
    void threadsApi
      .body(threadId, message.id, images)
      .then(setRich)
      .catch((error: unknown) =>
        setRichError(error instanceof Error ? error.message : "Could not load the original"),
      )
      .finally(() => setLoadingRich(false));
  };

  return (
    <div className="mt-s2">
      {rich ? (
        <>
          {rich.link_warnings.length > 0 ? (
            <ul className="mb-2 flex flex-col gap-1">
              {rich.link_warnings.map((warning) => (
                <li
                  key={`${warning.text}-${warning.href}`}
                  className="flex items-start gap-1.5 rounded-sm border border-warning-border bg-warning px-2 py-1 text-2xs text-warning-fg"
                >
                  <AlertTriangle className="mt-0.5 size-3 shrink-0" aria-hidden />
                  <span>
                    A link reading <strong>{warning.claimed_host}</strong> actually goes to{" "}
                    <strong>{warning.actual_host}</strong>.
                  </span>
                </li>
              ))}
            </ul>
          ) : null}

          <SandboxedHtml html={rich.html} imagesLoaded={rich.images_loaded} />

          <div className="mt-1.5 flex flex-wrap items-center gap-1">
            {rich.blocked_images > 0 ? (
              <Button size="sm" variant="secondary" onClick={() => loadRich("allowed")}>
                <Image aria-hidden />
                Load {rich.blocked_images} image{rich.blocked_images === 1 ? "" : "s"}
              </Button>
            ) : null}
            <Button size="sm" variant="ghost" onClick={() => setRich(null)}>
              Back to text
            </Button>
            {rich.blocked_images > 0 ? (
              <span className="text-2xs text-fg-subtle">
                Images are blocked until you ask, so a sender cannot tell you opened this.
              </span>
            ) : null}
          </div>
        </>
      ) : (
        <>
          <TextBody text={showQuoted ? full : stripped} />

          <div className="mt-1.5 flex flex-wrap items-center gap-1">
            {hasQuoted ? (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setShowQuoted((previous) => !previous)}
                aria-expanded={showQuoted}
              >
                {showQuoted ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
                {showQuoted ? "Hide quoted history" : "Show quoted history"}
                {savedPercent > 0 && !showQuoted ? (
                  <span className="text-2xs text-fg-subtle">({savedPercent}% hidden)</span>
                ) : null}
              </Button>
            ) : null}

            <Button
              size="sm"
              variant="ghost"
              onClick={() => loadRich("blocked")}
              disabled={loadingRich}
            >
              {loadingRich ? (
                <Loader2 className="animate-spin" aria-hidden />
              ) : (
                <Code2 aria-hidden />
              )}
              Original formatting
            </Button>
          </div>

          {richError ? (
            <p role="alert" className={cn("mt-1 text-sm text-danger-fg")}>
              {richError}
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
