import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { beforeEach, describe, expect, it } from "vitest";

import { applyTheme, useThemeStore } from "@/stores/theme";

describe("theme preference", () => {
  beforeEach(() => {
    document.documentElement.removeAttribute("data-theme");
    localStorage.clear();
    useThemeStore.setState({ preference: "system" });
  });

  it("pins light by writing the attribute", () => {
    useThemeStore.getState().setPreference("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("pins dark by writing the attribute", () => {
    useThemeStore.getState().setPreference("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("removes the attribute for system, so the media query decides", () => {
    useThemeStore.getState().setPreference("dark");
    useThemeStore.getState().setPreference("system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("persists the choice", () => {
    useThemeStore.getState().setPreference("dark");
    expect(localStorage.getItem("maail.theme")).toBe("dark");
  });

  it("survives blocked storage", () => {
    const original = localStorage.setItem.bind(localStorage);
    localStorage.setItem = () => {
      throw new Error("blocked");
    };
    try {
      expect(() => applyTheme("dark")).not.toThrow();
      expect(() => useThemeStore.getState().setPreference("dark")).not.toThrow();
      expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    } finally {
      localStorage.setItem = original;
    }
  });
});

describe("the pre-paint script in index.html", () => {
  const html = readFileSync(resolve(process.cwd(), "index.html"), "utf-8");

  it("reads the same storage key the store writes", () => {
    // The script runs before React, to stop a pinned dark theme flashing a
    // warm-white page. If the key drifts, the flash comes back silently.
    expect(html).toContain('localStorage.getItem("maail.theme")');
  });

  it("sets data-theme for a pinned theme and removes it for system", () => {
    expect(html).toContain('setAttribute("data-theme", stored)');
    expect(html).toContain('removeAttribute("data-theme")');
  });
});
