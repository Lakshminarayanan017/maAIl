import type { Meta, StoryObj } from "@storybook/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { ALL_NAV_ITEMS } from "@/components/layout/navigation";
import { RouteStub } from "@/pages/RouteStub";

/**
 * The three regions, end to end. Change the viewport in the toolbar: below the
 * desktop breakpoint the rail becomes a drawer and the AI panel becomes a
 * full-screen view, because the spec forbids squeezing three desktop panes
 * into one narrow column (08-ui-spec.md §8).
 */
const meta: Meta<typeof AppShell> = {
  title: "Layout/AppShell",
  component: AppShell,
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => (
      <MemoryRouter initialEntries={["/inbox"]}>
        <Routes>
          <Route element={<Story />}>
            {ALL_NAV_ITEMS.map((item) => (
              <Route key={item.to} path={item.to} element={<RouteStub />} />
            ))}
          </Route>
        </Routes>
      </MemoryRouter>
    ),
  ],
};
export default meta;

export const Desktop: StoryObj<typeof AppShell> = {};
