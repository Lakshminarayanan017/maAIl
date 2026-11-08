import { describe, expect, it } from "vitest";

import {
  ALL_NAV_ITEMS,
  NAV_GROUPS,
  SETTINGS_ITEM,
  navItemFor,
} from "@/components/layout/navigation";

/**
 * Global navigation is locked (08-ui-spec.md §7). This asserts the list and
 * the grouping against the specification rather than against itself, so a
 * well-meant tidy-up that drops "Priority" or renames a group fails CI.
 */
describe("global navigation", () => {
  const SPECIFIED = [
    "Overview",
    "Inbox",
    "Priority",
    "Developer Hub",
    "AI Companion",
    "Agents",
    "Tasks & Deadlines",
    "Insights",
    "Settings",
  ];

  it("has every specified item", () => {
    const labels = ALL_NAV_ITEMS.map((item) => item.label);
    for (const label of SPECIFIED) {
      expect(labels).toContain(label);
    }
  });

  it("groups the rail as Workspace, Categories, Intelligence", () => {
    expect(NAV_GROUPS.map((group) => group.label)).toEqual([
      "Workspace",
      "Categories",
      "Intelligence",
    ]);
  });

  it("puts Overview, Inbox and Priority in Workspace", () => {
    expect(NAV_GROUPS[0]!.items.map((item) => item.label)).toEqual([
      "Overview",
      "Inbox",
      "Priority",
    ]);
  });

  it("carries the five specified categories", () => {
    expect(NAV_GROUPS[1]!.items.map((item) => item.label)).toEqual([
      "Opportunities",
      "Development",
      "Academics",
      "Announcements",
      "Promotions",
    ]);
  });

  it("keeps Settings outside the three groups", () => {
    const grouped = NAV_GROUPS.flatMap((group) => group.items);
    expect(grouped).not.toContain(SETTINGS_ITEM);
    expect(ALL_NAV_ITEMS).toContain(SETTINGS_ITEM);
  });

  it("gives every item a unique route", () => {
    const routes = ALL_NAV_ITEMS.map((item) => item.to);
    expect(new Set(routes).size).toBe(routes.length);
  });

  it("names the phase that fills each route, so an empty screen is explicable", () => {
    for (const item of ALL_NAV_ITEMS) {
      expect(item.phase).toBeGreaterThan(0);
      expect(item.purpose.length).toBeGreaterThan(0);
    }
  });

  it("maps the eleven screens to the phases the execution plan assigns", () => {
    const byScreen = new Map(
      ALL_NAV_ITEMS.filter((item) => item.screen).map((item) => [item.screen!, item.phase]),
    );
    expect(byScreen.get("03")).toBe(7);
    expect(byScreen.get("04")).toBe(2);
    expect(byScreen.get("06")).toBe(10);
    expect(byScreen.get("07")).toBe(13);
    expect(byScreen.get("08")).toBe(14);
    expect(byScreen.get("09")).toBe(9);
    expect(byScreen.get("10")).toBe(15);
    expect(byScreen.get("11")).toBe(11);
  });
});

describe("navItemFor", () => {
  it("matches an exact route", () => {
    expect(navItemFor("/inbox")?.label).toBe("Inbox");
  });

  it("matches a nested route, so a thread still highlights Inbox", () => {
    expect(navItemFor("/inbox/thread-123")?.label).toBe("Inbox");
  });

  it("does not match a route that merely shares a prefix", () => {
    expect(navItemFor("/inboxes")).toBeUndefined();
  });

  it("returns nothing for an unknown route", () => {
    expect(navItemFor("/nowhere")).toBeUndefined();
  });
});
