import { MessageSquare, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { CompanionChat } from "@/components/companion/CompanionChat";
import { ErrorState } from "@/components/common/ErrorState";
import { Skeleton } from "@/components/common/Skeleton";
import { Button } from "@/components/ui/button";
import { companion as companionApi } from "@/services/api";
import { cn } from "@/lib/utils";
import type { Conversation } from "@/types/api";

/**
 * Screen 06 — AI Companion.
 *
 *     Conversations │ Maail Companion
 *     New chat      │ What would you like to
 *                   │ understand today?
 *     Recent chats  │
 *     Internship    │ ...
 *     preparation   │ Ask anything about emails... [↑]
 *
 * The sidebar lists real conversations. `New chat` does not create one:
 * the conversation is created when the first question is asked, so the
 * list is topics the user has actually discussed rather than a row per
 * visit. Titles come from the first question, which is why they read like
 * subjects.
 */
export function CompanionPage() {
  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [active, setActive] = useState<string | null>(null);
  //: Changes only when the user picks a different chat or starts a new
  //: one. Remounting the chat is how a half-typed draft is discarded,
  //: and that should happen on their action, never on ours.
  const [chatKey, setChatKey] = useState("new");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    (select?: string) =>
      companionApi
        .conversations()
        .then((listed) => {
          setConversations(listed);
          setActive((current) => select ?? current ?? listed[0]?.id ?? null);
        })
        .catch((caught: unknown) =>
          setError(caught instanceof Error ? caught.message : "Could not load your chats"),
        ),
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const remove = (id: string) => {
    void companionApi.remove(id).then(() => {
      setActive((current) => (current === id ? null : current));
      setChatKey((current) => (current === id ? `new-${Date.now()}` : current));
      void load();
    });
  };

  if (error) return <ErrorState description={error} onRetry={() => void load()} />;

  return (
    <div className="flex min-h-0 flex-1">
      <aside
        aria-label="Conversations"
        className="hidden w-56 shrink-0 flex-col border-r border-line bg-surface md:flex"
      >
        <div className="p-s2">
          <Button size="sm" variant="secondary" className="w-full" onClick={() => setActive(null)}>
            <Plus aria-hidden />
            New chat
          </Button>
        </div>

        <p className="px-s2 text-2xs uppercase tracking-wide text-fg-subtle">Recent chats</p>

        <nav className="min-h-0 flex-1 overflow-y-auto p-s1">
          {!conversations ? (
            <div className="flex flex-col gap-1 p-1">
              <Skeleton className="h-7" />
              <Skeleton className="h-7" />
            </div>
          ) : conversations.length === 0 ? (
            <p className="p-s2 text-2xs text-fg-subtle">
              Nothing yet. Ask something and it will appear here.
            </p>
          ) : (
            conversations.map((conversation) => (
              <div
                key={conversation.id}
                className={cn(
                  "group flex items-center gap-1 rounded-sm px-1.5 py-1 transition-colors",
                  active === conversation.id ? "bg-ai text-ai-fg" : "hover:bg-surface-sunken",
                )}
              >
                <button
                  type="button"
                  onClick={() => {
                    setActive(conversation.id);
                    setChatKey(conversation.id);
                  }}
                  className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
                >
                  <MessageSquare className="size-3 shrink-0 opacity-70" aria-hidden />
                  <span className="truncate text-sm">{conversation.title ?? "Untitled chat"}</span>
                </button>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label={`Delete ${conversation.title ?? "this chat"}`}
                  className="size-5 opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100"
                  onClick={() => remove(conversation.id)}
                >
                  <Trash2 aria-hidden />
                </Button>
              </div>
            ))
          )}
        </nav>
      </aside>

      <div className="flex min-h-0 flex-1 flex-col">
        <header className="shrink-0 px-s3 pb-1 pt-s3">
          <h2 className="font-brand text-2xl font-bold text-fg">Maail Companion</h2>
          <p className="mt-0.5 text-md text-fg-muted">
            Ask about your own mail. Every claim comes with the words behind it.
          </p>
        </header>

        <div className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col">
          <CompanionChat
            // Keyed on what the *user* chose, not on which conversation
            // is active. The chat creates its conversation when the first
            // question is asked, so keying on `active` remounted it
            // mid-stream and threw away the answer it was receiving.
            // Seen on the very first question asked.
            key={chatKey}
            conversationId={active}
            onConversation={(id) => {
              // Update the sidebar; do not disturb the running chat.
              setActive(id);
              void companionApi.conversations().then(setConversations);
            }}
            // A conversation is named after its first question, which is
            // written while the answer is being produced -- so the list
            // fetched at creation time still says "Untitled chat".
            onAnswered={() => void companionApi.conversations().then(setConversations)}
          />
        </div>
      </div>
    </div>
  );
}

export default CompanionPage;
