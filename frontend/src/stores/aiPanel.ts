import { create } from "zustand";

/**
 * The AI panel's three states, option C, locked (08-ui-spec.md §6):
 *
 *   collapsed -> a compact floating entry point
 *   panel     -> a contextual side panel
 *   full      -> a full-screen companion for long conversations
 *
 * One store, held across pages rather than per page, because the panel
 * "should follow the user throughout the application and adapt its context to
 * the currently selected email, conversation or task."
 *
 * `context` is what it is currently about. Phase 0 sets it from the route;
 * phase 5 fills the panel itself and phase 8 attaches thread intelligence.
 */
export type AiPanelState = "collapsed" | "panel" | "full";

export type AiContextKind = "none" | "route" | "thread" | "task" | "conversation";

export interface AiContext {
  kind: AiContextKind;
  /** Stable id of the subject, when there is one. */
  id?: string;
  /** What to show as the panel's subtitle. */
  label?: string;
}

interface AiPanelStore {
  state: AiPanelState;
  context: AiContext;
  open: () => void;
  collapse: () => void;
  expand: () => void;
  toggle: () => void;
  setContext: (context: AiContext) => void;
}

export const useAiPanel = create<AiPanelStore>((set, get) => ({
  state: "collapsed",
  context: { kind: "none" },
  open: () => set({ state: "panel" }),
  collapse: () => set({ state: "collapsed" }),
  expand: () => set({ state: "full" }),
  toggle: () => set({ state: get().state === "collapsed" ? "panel" : "collapsed" }),
  setContext: (context) => set({ context }),
}));
