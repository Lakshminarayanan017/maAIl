import { MotionConfig } from "framer-motion";
import { Route, Routes } from "react-router-dom";

import { EmptyState } from "@/components/common/EmptyState";
import { RequireSession, RootRoute } from "@/components/common/RequireSession";
import { AppShell } from "@/components/layout/AppShell";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ALL_NAV_ITEMS } from "@/components/layout/navigation";
import { transition } from "@/lib/motion";
import { CompanionPage } from "@/pages/companion/CompanionPage";
import { TracesPage } from "@/pages/dev/TracesPage";
import { InboxPage } from "@/pages/inbox/InboxPage";
import { OverviewPage } from "@/pages/overview/OverviewPage";
import { PriorityPage } from "@/pages/priority/PriorityPage";
import { ConnectPage } from "@/pages/onboarding/ConnectPage";
import { PermissionsPage } from "@/pages/onboarding/PermissionsPage";
import { PersonalizePage } from "@/pages/onboarding/PersonalizePage";
import { WelcomePage } from "@/pages/onboarding/WelcomePage";
import { RouteStub } from "@/pages/RouteStub";
import { SettingsPage } from "@/pages/settings/SettingsPage";
import { TasksPage } from "@/pages/tasks/TasksPage";

/**
 * Two route groups. Onboarding is outside the shell, because screens 01 and
 * 02 have no sidebar and no AI panel; everything else is inside it and
 * behind a session.
 *
 * The application routes are generated from the navigation definition, so a
 * nav item without a route (or the reverse) is impossible rather than a bug
 * to find later. `SCREENS` is where a phase swaps a stub for the real thing.
 *
 * `MotionConfig` applies the 150-200ms default to every animation that does
 * not state its own, and honours the reduced-motion setting globally.
 */
const SCREENS: Record<string, React.ComponentType> = {
  "/overview": OverviewPage,
  "/inbox": InboxPage,
  "/priority": PriorityPage,
  "/settings": SettingsPage,
  "/tasks": TasksPage,
  "/companion": CompanionPage,
};

export default function App() {
  return (
    <MotionConfig transition={transition} reducedMotion="user">
      {/*
        At the root rather than inside AppShell. Onboarding renders
        outside the shell and now shows the feature controls, which
        use tooltips -- a provider only the shell had made step 3 of 3
        throw on mount.
      */}
      <TooltipProvider delayDuration={300}>
        <Routes>
          {/* Public: no shell, no session required. */}
          <Route path="/" element={<RootRoute welcome={<WelcomePage />} />} />
          <Route path="/onboarding/connect" element={<ConnectPage />} />
          <Route path="/permissions" element={<PermissionsPage />} />
          {/* Step 3 of 3 — entry point A for the feature controls. */}
          <Route path="/onboarding/personalize" element={<PersonalizePage />} />

          {/* The application. */}
          <Route element={<RequireSession />}>
            <Route element={<AppShell />}>
              {ALL_NAV_ITEMS.map((item) => {
                const Screen = SCREENS[item.to];
                return (
                  <Route
                    key={item.to}
                    path={item.to}
                    element={Screen ? <Screen /> : <RouteStub />}
                  />
                );
              })}
              {/*
              Internal, not a nav item. The traces view is for whoever is
              debugging an agent, which is why it is reachable by URL and
              not by a sidebar entry (09-execution-plan.md, phase 5).
            */}
              <Route path="/dev/traces" element={<TracesPage />} />
              <Route
                path="*"
                element={
                  <EmptyState
                    title="No such page"
                    description="That route does not exist in Maail."
                  />
                }
              />
            </Route>
          </Route>
        </Routes>
      </TooltipProvider>
    </MotionConfig>
  );
}
