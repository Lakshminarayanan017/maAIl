import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";

import { ErrorBoundary } from "@/components/common/ErrorState";
import { OfflineBanner } from "@/components/common/OfflineBanner";
import { ReconnectBanner } from "@/components/common/ReconnectBanner";
import { AiPanelRegion } from "@/components/layout/AiPanelRegion";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { navItemFor } from "@/components/layout/navigation";
import { useIsDesktop } from "@/hooks/useMediaQuery";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useAccounts } from "@/stores/accounts";
import { useInbox } from "@/stores/inbox";
import { useAiPanel } from "@/stores/aiPanel";

const RAIL_KEY = "maail.rail.collapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Three regions (08-ui-spec.md §6): sidebar, centre, right panel.
 *
 * Below the desktop breakpoint the three panes do not shrink into one narrow
 * view, which §8 forbids. The rail becomes a drawer and the AI panel becomes a
 * full-screen view instead of a 380px column squeezed against the content.
 */
export function AppShell() {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [navOpen, setNavOpen] = useState(false);
  const isDesktop = useIsDesktop();
  const { pathname } = useLocation();

  const panelState = useAiPanel((state) => state.state);
  const expand = useAiPanel((state) => state.expand);
  const setContext = useAiPanel((state) => state.setContext);
  const loadAccounts = useAccounts((state) => state.load);
  const selectedId = useInbox((state) => state.selectedId);
  const threadSubject = useInbox((state) => state.thread?.subject ?? null);

  // Account status drives the reconnect banner, which has to be able to
  // appear on any screen rather than only on the one that fetched it.
  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  // The panel follows the user and "adapts its context to the currently
  // selected email" (08-ui-spec.md §6). A selected thread outranks the
  // route, because the thread is the more specific thing the reader is
  // looking at — and it is what the intelligence sections are about.
  //
  // One effect here rather than a setContext call in each page: a page
  // that forgot to make it would silently show the wrong panel, which is
  // exactly what happened the first time this was tried.
  useEffect(() => {
    if (selectedId) return;
    const item = navItemFor(pathname);
    setContext({ kind: "route", id: pathname, label: item?.label ?? "Maail" });
  }, [pathname, selectedId, setContext]);

  useEffect(() => {
    if (!selectedId) return;
    setContext({
      kind: "thread",
      id: selectedId,
      label: threadSubject ?? "Thread",
    });
  }, [selectedId, threadSubject, setContext]);

  // On a phone there is no side panel to open into, so the contextual state
  // resolves to the full-screen companion instead of a squeezed column.
  useEffect(() => {
    if (!isDesktop && panelState === "panel") expand();
  }, [isDesktop, panelState, expand]);

  const toggleCollapsed = () => {
    setCollapsed((previous) => {
      const next = !previous;
      try {
        localStorage.setItem(RAIL_KEY, next ? "1" : "0");
      } catch {
        /* the choice still applies for this session */
      }
      return next;
    });
  };

  return (
    // Also provided at the root, because onboarding renders outside
    // this shell and uses tooltips too. Kept here as well so the
    // shell stands up on its own in tests and Storybook; nesting a
    // Radix provider costs nothing and a layout that only works
    // inside one particular parent is a layout that breaks quietly.
    <TooltipProvider delayDuration={300}>
      <div className="flex h-dvh flex-col overflow-hidden bg-bg text-fg">
        <OfflineBanner />
        <ReconnectBanner />

        <div className="flex min-h-0 flex-1">
          {/*
            Left region. The two layouts are mounted conditionally rather than
            hidden with a media query, because a drawer and a rail are
            different structures, not one structure reflowed. It also means
            only one <nav> is ever in the accessibility tree.
          */}
          {isDesktop ? (
            <Sidebar collapsed={collapsed} onToggleCollapsed={toggleCollapsed} />
          ) : (
            <Dialog.Root open={navOpen} onOpenChange={setNavOpen}>
              <Dialog.Portal>
                <Dialog.Overlay className="fixed inset-0 z-40 bg-fg/20 backdrop-blur-sm data-[state=open]:animate-fade-in" />
                <Dialog.Content
                  aria-label="Navigation"
                  className="fixed inset-y-0 left-0 z-50 data-[state=open]:animate-slide-in-right"
                >
                  <Dialog.Title className="sr-only">Navigation</Dialog.Title>
                  <Sidebar
                    collapsed={false}
                    onToggleCollapsed={toggleCollapsed}
                    onNavigate={() => setNavOpen(false)}
                    className="shadow-overlay"
                  />
                </Dialog.Content>
              </Dialog.Portal>
            </Dialog.Root>
          )}

          {/* Centre region. */}
          <div className="flex min-w-0 flex-1 flex-col">
            <TopBar onOpenNav={() => setNavOpen(true)} />
            <main className="min-h-0 flex-1 overflow-y-auto">
              <ErrorBoundary>
                <Outlet />
              </ErrorBoundary>
            </main>
          </div>

          {/* Right region. */}
          <AiPanelRegion />
        </div>
      </div>
    </TooltipProvider>
  );
}
