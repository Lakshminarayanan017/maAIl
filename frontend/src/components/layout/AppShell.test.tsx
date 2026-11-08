import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { ALL_NAV_ITEMS } from "@/components/layout/navigation";
import { RouteStub } from "@/pages/RouteStub";
import { useAiPanel } from "@/stores/aiPanel";
import { setViewport } from "@/test/setup";

function renderShell(path = "/inbox") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell />}>
          {ALL_NAV_ITEMS.map((item) => (
            <Route key={item.to} path={item.to} element={<RouteStub />} />
          ))}
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppShell", () => {
  beforeEach(() => {
    useAiPanel.setState({ state: "collapsed", context: { kind: "none" } });
  });

  it("renders the three sidebar groups", () => {
    renderShell();
    const nav = screen.getAllByRole("navigation", { name: "Main" })[0]!;
    expect(within(nav).getByText("Workspace")).toBeInTheDocument();
    expect(within(nav).getByText("Categories")).toBeInTheDocument();
    expect(within(nav).getByText("Intelligence")).toBeInTheDocument();
  });

  it("names the current screen in the header", () => {
    renderShell("/tasks");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Tasks & Deadlines");
  });

  it("navigates between routes", async () => {
    const user = userEvent.setup();
    renderShell("/inbox");
    const nav = screen.getAllByRole("navigation", { name: "Main" })[0]!;

    await user.click(within(nav).getByRole("link", { name: "Insights" }));

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Insights");
  });

  it("shows an honest stub rather than sample data", () => {
    renderShell("/overview");
    expect(screen.getByText(/stays empty until its data source exists/i)).toBeInTheDocument();
    expect(screen.getByText("Phase 7")).toBeInTheDocument();
  });

  it("adapts the AI panel context to the current screen", () => {
    renderShell("/companion");
    expect(useAiPanel.getState().context).toMatchObject({
      kind: "route",
      label: "AI Companion",
    });
  });

  it("opens the AI panel from the collapsed affordance and closes it again", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Open AI panel" }));
    expect(useAiPanel.getState().state).toBe("panel");
    expect(screen.getByRole("complementary", { name: "AI intelligence" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close AI panel" }));
    expect(useAiPanel.getState().state).toBe("collapsed");
  });

  it("expands the panel to the full-screen companion", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Open AI panel" }));
    await user.click(screen.getByRole("button", { name: "Full screen companion" }));

    expect(useAiPanel.getState().state).toBe("full");
    expect(screen.getByRole("dialog", { name: "AI companion" })).toBeInTheDocument();
  });

  it("collapses the rail and remembers it", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Collapse navigation" }));
    expect(localStorage.getItem("maail.rail.collapsed")).toBe("1");
  });
});

describe("AppShell at phone width", () => {
  beforeEach(() => {
    useAiPanel.setState({ state: "collapsed", context: { kind: "none" } });
    setViewport(390);
  });

  it("does not squeeze the AI panel into a column, it goes full screen", async () => {
    // "On smaller screens, we should never squeeze the three desktop panels
    // into one narrow view." (08-ui-spec.md §8)
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Open AI panel" }));

    expect(useAiPanel.getState().state).toBe("full");
    expect(screen.getByRole("dialog", { name: "AI companion" })).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "AI intelligence" })).toBeNull();
  });

  it("puts navigation behind a menu button", async () => {
    const user = userEvent.setup();
    renderShell();

    expect(screen.queryByRole("navigation", { name: "Main" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Open navigation" }));

    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
  });
});
