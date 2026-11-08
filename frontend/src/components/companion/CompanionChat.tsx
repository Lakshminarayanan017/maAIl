import { ArrowUp, Database, Loader2, Quote, RefreshCw, Sparkles, Zap } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ErrorState } from "@/components/common/ErrorState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { companion as companionApi } from "@/services/api";
import type { AskRouteInfo } from "@/services/api";
import { useInbox } from "@/stores/inbox";
import { cn } from "@/lib/utils";
import type { AskDone, Citation, ThreadReference, Turn } from "@/types/api";

/**
 * Screen 06's conversation, usable in all three panel states.
 *
 * Two things here are the product rather than the chrome.
 *
 * **The route is shown.** "Answered from results already stored" and
 * "Worked out just now" are different claims about where an answer came
 * from, and a reader deciding how much to trust it should be told which
 * they got. It is also the honest face of the cost architecture: most
 * questions do not reach a model, and that is visible rather than merely
 * true.
 *
 * **Citations are chips that resolve.** Every claim about email content
 * arrives with a `message_id` and a span the backend has already checked
 * against the message. Clicking one opens that thread. A claim whose
 * citation failed never reaches this component as a claim.
 */
const ROUTE_ICON: Record<string, typeof Zap> = {
  sql: Zap,
  cached: Database,
  model: Sparkles,
};

function RouteChip({ route, label }: { route: string; label: string }) {
  const Icon = ROUTE_ICON[route] ?? Sparkles;
  // Lavender only for the model route. An answer that came from a SQL
  // count is not AI-derived and must not be dressed as it.
  const variant = route === "model" ? "ai" : "neutral";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span>
          <Badge variant={variant}>
            <Icon className="size-2.5" aria-hidden />
            {label}
          </Badge>
        </span>
      </TooltipTrigger>
      <TooltipContent>
        {route === "model"
          ? "A model read your mail to answer this."
          : "Answered from your own data, with no model involved."}
      </TooltipContent>
    </Tooltip>
  );
}

function CitationChips({
  citations,
  references,
}: {
  citations: Citation[];
  references?: ThreadReference[] | undefined;
}) {
  const select = useInbox((state) => state.select);
  if (citations.length === 0 && (references?.length ?? 0) === 0) return null;

  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {citations.map((citation) => (
        <Tooltip key={`${citation.message_id}-${citation.char_start}`}>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={() => citation.thread_id && void select(citation.thread_id)}
              className="inline-flex max-w-full items-center gap-1 rounded-pill border border-ai-border bg-ai px-1.5 py-0.5 text-2xs text-ai-fg transition-colors hover:bg-ai-hover"
            >
              <Quote className="size-2.5 shrink-0" aria-hidden />
              <span className="truncate">
                {citation.quote ?? `characters ${citation.char_start}–${citation.char_end}`}
              </span>
            </button>
          </TooltipTrigger>
          <TooltipContent>
            {citation.quote
              ? "From this message. Click to open the thread."
              : "Click to open the message this came from."}
          </TooltipContent>
        </Tooltip>
      ))}

      {references?.map((reference) => (
        <button
          key={reference.thread_id}
          type="button"
          onClick={() => void select(reference.thread_id)}
          className="inline-flex max-w-full items-center gap-1 rounded-pill border border-info-border bg-info px-1.5 py-0.5 text-2xs text-info-fg transition-colors hover:brightness-95"
        >
          <span className="truncate">{reference.subject || "(no subject)"}</span>
          {reference.detail ? (
            <span className="truncate opacity-70">&middot; {reference.detail}</span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

function TurnBubble({
  turn,
  references,
}: {
  turn: Turn;
  references?: ThreadReference[] | undefined;
}) {
  const mine = turn.role === "user";
  return (
    <div className={cn("flex flex-col gap-0.5", mine ? "items-end" : "items-start")}>
      <div
        className={cn(
          "max-w-[92%] whitespace-pre-wrap rounded-md px-s2 py-1.5 text-base",
          mine ? "bg-violet text-fg-on-violet" : "border border-line bg-surface text-fg",
        )}
      >
        {turn.content}
      </div>
      {!mine ? (
        <>
          {turn.route ? (
            <RouteChip
              route={turn.route}
              label={
                {
                  sql: "From your mailbox directly",
                  cached: "From results already stored",
                  model: "Worked out just now",
                }[turn.route]
              }
            />
          ) : null}
          <CitationChips citations={turn.citations} references={references} />
        </>
      ) : null}
    </div>
  );
}

export interface CompanionChatProps {
  conversationId: string | null;
  /** Set when the chat is scoped to one thread. */
  threadId?: string | null;
  /** Called with a new conversation id when this component had to make one. */
  onConversation?: (id: string) => void;
  /** Called when a turn finishes. The conversation's title is written
   *  from its first question, so the sidebar is stale until then. */
  onAnswered?: () => void;
  /** Hidden in the contextual panel, where there is no room. */
  showSuggestions?: boolean;
  className?: string;
}

export function CompanionChat({
  conversationId,
  threadId = null,
  onConversation,
  onAnswered,
  showSuggestions = true,
  className,
}: CompanionChatProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [prompts, setPrompts] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [partial, setPartial] = useState("");
  const [route, setRoute] = useState<AskRouteInfo | null>(null);
  const [lastDone, setLastDone] = useState<AskDone | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [id, setId] = useState<string | null>(conversationId);

  const abort = useRef<(() => void) | null>(null);
  const bottom = useRef<HTMLDivElement | null>(null);

  useEffect(() => setId(conversationId), [conversationId]);

  const load = useCallback((target: string) => {
    void companionApi
      .read(target)
      .then((detail) => {
        setTurns(detail.turns);
        setPrompts(detail.suggested_prompts);
      })
      .catch((caught: unknown) =>
        setError(caught instanceof Error ? caught.message : "Could not open this chat"),
      );
  }, []);

  useEffect(() => {
    if (id) load(id);
    else setTurns([]);
  }, [id, load]);

  // Stop the reader when this unmounts, so navigating away does not leave
  // a stream running against an answer nobody will see.
  useEffect(() => () => abort.current?.(), []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length, partial]);

  const send = async (question: string, regenerate = false) => {
    const asked = question.trim();
    if (!asked || streaming) return;

    let target = id;
    if (!target) {
      // A conversation is created on the first question, not on opening
      // the panel: an empty chat per visit would fill the sidebar with
      // nothing.
      try {
        const created = await companionApi.create({ thread_id: threadId });
        target = created.conversation.id;
        setId(target);
        setPrompts(created.suggested_prompts);
        onConversation?.(target);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Could not start a chat");
        return;
      }
    }

    setError(null);
    setDraft("");
    setPartial("");
    setRoute(null);
    setLastDone(null);
    setStreaming(true);

    if (!regenerate) {
      setTurns((previous) => [
        ...previous,
        {
          id: `pending-${Date.now()}`,
          role: "user",
          content: asked,
          citations: [],
          route: null,
          created_at: new Date().toISOString(),
        },
      ]);
    }

    abort.current = companionApi.ask(
      target,
      asked,
      {
        onRoute: setRoute,
        onDelta: (text) => setPartial((previous) => previous + text),
        onDone: (done) => {
          setLastDone(done);
          setStreaming(false);
          setPartial("");
          load(target);
          onAnswered?.();
        },
        onFailed: (message) => {
          setStreaming(false);
          setPartial("");
          setError(message);
        },
      },
      { regenerate },
    );
  };

  const lastQuestion = [...turns].reverse().find((turn) => turn.role === "user")?.content;

  if (error && turns.length === 0) {
    return <ErrorState description={error} onRetry={() => id && load(id)} />;
  }

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col", className)}>
      <div className="flex-1 overflow-y-auto px-s2 py-s2">
        {turns.length === 0 ? (
          <div className="flex flex-col gap-s2">
            <h2 className="font-brand text-lg font-semibold text-fg">
              What would you like to understand today?
            </h2>
            {showSuggestions ? (
              <div className="flex flex-col gap-1">
                {(prompts.length > 0 ? prompts : DEFAULT_PROMPTS).map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    onClick={() => void send(prompt)}
                    className="rounded-sm border border-line bg-surface px-s2 py-1.5 text-left text-base text-fg transition-colors hover:bg-surface-sunken"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="flex flex-col gap-s2">
            {turns.map((turn, index) => (
              <TurnBubble
                key={turn.id}
                turn={turn}
                references={
                  // References belong to the newest answer only: the
                  // earlier ones were stored with their citations, and
                  // re-attaching this turn's chips to them would be a lie
                  // about where they came from.
                  index === turns.length - 1 ? lastDone?.references : undefined
                }
              />
            ))}

            {streaming ? (
              <div className="flex flex-col items-start gap-0.5">
                {route ? <RouteChip route={route.route} label={route.label} /> : null}
                <div className="max-w-[92%] whitespace-pre-wrap rounded-md border border-line bg-surface px-s2 py-1.5 text-base text-fg">
                  {partial || (
                    <span className="inline-flex items-center gap-1.5 text-fg-subtle">
                      <Loader2 className="size-3 animate-spin" aria-hidden />
                      Looking
                    </span>
                  )}
                </div>
              </div>
            ) : null}

            {!streaming && lastDone ? (
              <div className="flex flex-wrap items-center gap-1">
                {lastDone.follow_ups.map((follow) => (
                  <Button
                    key={follow}
                    size="sm"
                    variant="secondary"
                    className="h-6 text-2xs"
                    onClick={() => void send(follow)}
                  >
                    {follow}
                  </Button>
                ))}
                {lastQuestion ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 text-2xs"
                    onClick={() => void send(lastQuestion, true)}
                  >
                    <RefreshCw className="size-3" aria-hidden />
                    Regenerate
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>
        )}
        <div ref={bottom} />
      </div>

      {error && turns.length > 0 ? (
        <p role="alert" className="px-s2 pb-1 text-2xs text-danger-fg">
          {error}
        </p>
      ) : null}

      <form
        className="flex items-end gap-1 border-t border-line bg-surface p-s2"
        onSubmit={(event) => {
          event.preventDefault();
          void send(draft);
        }}
      >
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send(draft);
            }
          }}
          rows={1}
          placeholder={threadId ? "Ask about this thread..." : "Ask anything about emails..."}
          aria-label="Ask Maail"
          className="max-h-24 min-h-9 flex-1 resize-none rounded-sm border border-line bg-bg px-1.5 py-2 text-base text-fg outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <Button
          type="submit"
          size="icon"
          aria-label="Send"
          disabled={streaming || draft.trim().length === 0}
        >
          {streaming ? <Loader2 className="animate-spin" aria-hidden /> : <ArrowUp aria-hidden />}
        </Button>
      </form>
    </div>
  );
}

/** The specified examples, used until the server sends its own list. */
const DEFAULT_PROMPTS = [
  "Find pending internship emails",
  "What did my teammate say about the API?",
  "Summarize my technical conversations",
  "Draft a response to the recruiter",
  "Which emails need my attention?",
];

export default CompanionChat;
