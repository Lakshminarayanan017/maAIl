import { AnimatePresence, motion } from "framer-motion";
import { Maximize2, Minimize2, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";

import { CompanionChat } from "@/components/companion/CompanionChat";
import { IntelligencePanel } from "@/components/intelligence/IntelligencePanel";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { panelVariants, transition, transitionFast } from "@/lib/motion";
import { useIsDesktop } from "@/hooks/useMediaQuery";
import { useAiPanel } from "@/stores/aiPanel";
import { cn } from "@/lib/utils";

/**
 * The right region: contextual AI intelligence (08-ui-spec.md §6).
 *
 * Option C, locked: a compact floating entry point, expandable into a
 * contextual side panel, with a full-screen companion for complex
 * conversations. One store holds the state across pages, because the panel
 * "should follow the user throughout the application".
 *
 * Phase 0 builds the three states and the transitions between them. The panel
 * body is an honest empty state until phase 5 gives it something real to say -
 * no placeholder conversation, no sample summary.
 */
function CollapsedAffordance() {
  const open = useAiPanel((state) => state.open);

  return (
    <motion.div
      key="collapsed"
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={transitionFast}
      className="pointer-events-auto fixed bottom-s3 right-s3 z-30"
    >
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            onClick={open}
            size="icon"
            className="size-12 rounded-pill shadow-overlay"
            aria-label="Open AI panel"
          >
            <Sparkles className="size-5" aria-hidden />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="left">Ask Maail</TooltipContent>
      </Tooltip>
    </motion.div>
  );
}

/**
 * What the panel is about decides what it shows.
 *
 * A thread gets screen 05's intelligence sections; anything else gets the
 * companion, which is the one thing that is useful without a selection.
 * The two are not tabs: the panel "adapts its context to the currently
 * selected email, conversation or task" (08-ui-spec.md §6), so the
 * selection is the control.
 */
function PanelBody({ chrome }: { chrome: "panel" | "full" }) {
  const context = useAiPanel((state) => state.context);
  const [tab, setTab] = useState<"intelligence" | "ask">("intelligence");

  // A newly selected thread opens on its intelligence, not on whatever
  // was last looked at.
  useEffect(() => setTab("intelligence"), [context.id]);

  if (context.kind === "thread" && context.id) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex gap-1 border-b border-line px-s2 py-1">
          {(["intelligence", "ask"] as const).map((option) => (
            <Button
              key={option}
              size="sm"
              variant={tab === option ? "secondary" : "ghost"}
              className="h-6 text-2xs"
              onClick={() => setTab(option)}
            >
              {option === "intelligence" ? "Intelligence" : "Ask about this"}
            </Button>
          ))}
        </div>
        {tab === "intelligence" ? (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <IntelligencePanel threadId={context.id} subject={context.label} />
          </div>
        ) : (
          <CompanionChat conversationId={null} threadId={context.id} showSuggestions={false} />
        )}
      </div>
    );
  }

  if (context.kind === "conversation" && context.id) {
    return <CompanionChat conversationId={context.id} />;
  }

  return <CompanionChat conversationId={null} showSuggestions={chrome === "full"} />;
}

function PanelHeader() {
  const state = useAiPanel((store) => store.state);
  const collapse = useAiPanel((store) => store.collapse);
  const expand = useAiPanel((store) => store.expand);
  const open = useAiPanel((store) => store.open);
  const context = useAiPanel((store) => store.context);

  return (
    <div className="flex h-topbar shrink-0 items-center gap-2 border-b border-ai-border bg-ai px-s2 text-ai-fg">
      <Sparkles className="size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="truncate font-brand text-base font-semibold">Maail</p>
        {context.label ? <p className="truncate text-2xs opacity-80">{context.label}</p> : null}
      </div>
      {state === "full" ? (
        <Button variant="ghost" size="icon-sm" onClick={open} aria-label="Shrink to side panel">
          <Minimize2 aria-hidden />
        </Button>
      ) : (
        <Button variant="ghost" size="icon-sm" onClick={expand} aria-label="Full screen companion">
          <Maximize2 aria-hidden />
        </Button>
      )}
      <Button variant="ghost" size="icon-sm" onClick={collapse} aria-label="Close AI panel">
        <X aria-hidden />
      </Button>
    </div>
  );
}

export function AiPanelRegion() {
  const state = useAiPanel((store) => store.state);
  const isDesktop = useIsDesktop();

  return (
    <AnimatePresence>
      {state === "collapsed" ? <CollapsedAffordance /> : null}

      {state === "panel" && isDesktop ? (
        <motion.aside
          key="panel"
          aria-label="AI intelligence"
          variants={panelVariants}
          initial="hidden"
          animate="visible"
          exit="exit"
          transition={transition}
          className={cn(
            "flex w-ai-panel shrink-0 flex-col border-l border-line bg-surface",
            "xl:w-ai-panel-wide",
          )}
        >
          <PanelHeader />
          <PanelBody chrome="panel" />
        </motion.aside>
      ) : null}

      {state === "full" ? (
        <motion.div
          key="full"
          role="dialog"
          aria-modal="true"
          aria-label="AI companion"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={transition}
          className="fixed inset-0 z-40 flex flex-col bg-bg"
        >
          <PanelHeader />
          <div className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col">
            <PanelBody chrome="full" />
          </div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
