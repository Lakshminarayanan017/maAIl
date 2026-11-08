import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { DURATION } from "@/lib/motion";

// `import.meta.url` is an http URL under Vitest, so resolve from the project
// root rather than from this module.
const tokensCss = readFileSync(resolve(process.cwd(), "src/styles/tokens.css"), "utf-8");

/**
 * The palette and the motion range are locked (08-ui-spec.md §2 and §4), so
 * they are asserted rather than trusted. A refactor that drops a token or
 * drifts a duration out of the 150-200ms range fails here.
 */
describe("locked palette", () => {
  const PALETTE = {
    "warm white": "#f7f6f3",
    "pure white": "#ffffff",
    "Maail violet": "#8b70d6",
    charcoal: "#25232b",
    "soft lavender": "#e8e2f5",
    "soft green": "#ddebe2",
  };

  for (const [name, hex] of Object.entries(PALETTE)) {
    it(`keeps ${name} (${hex})`, () => {
      expect(tokensCss.toLowerCase()).toContain(hex);
    });
  }
});

describe("dark theme", () => {
  it("redefines the tokens under the system preference, guarded against a pinned light theme", () => {
    expect(tokensCss).toContain("@media (prefers-color-scheme: dark)");
    expect(tokensCss).toContain(':root:not([data-theme="light"])');
  });

  it("redefines them again for a pinned dark theme", () => {
    expect(tokensCss).toContain(':root[data-theme="dark"]');
  });

  it("uses charcoal as the dark surface rather than inverting the light one", () => {
    const darkBlock = tokensCss.slice(tokensCss.indexOf(':root[data-theme="dark"]'));
    // #25232B is hsl(255 10% 15%)
    expect(darkBlock).toContain("--surface: 255 10% 15%");
  });
});

describe("radii stay inside 10-14px", () => {
  const radii = [...tokensCss.matchAll(/--radius[\w-]*:\s*(\d+)px/g)].map((match) =>
    Number(match[1]),
  );

  it("declares a radius scale", () => {
    expect(radii.length).toBeGreaterThan(0);
  });

  it("has nothing tighter than 10px or looser than 14px, pills aside", () => {
    for (const value of radii) {
      if (value === 999) continue;
      expect(value).toBeGreaterThanOrEqual(10);
      expect(value).toBeLessThanOrEqual(14);
    }
  });
});

describe("the 8px spacing scale", () => {
  it("is every multiple of 8 up to 80, and nothing else", () => {
    const spaces = [...tokensCss.matchAll(/--space-(\d+):\s*(\d+)px/g)].map((match) => ({
      index: Number(match[1]),
      px: Number(match[2]),
    }));
    expect(spaces).toHaveLength(10);
    for (const { index, px } of spaces) {
      expect(px).toBe(index * 8);
    }
  });
});

describe("motion", () => {
  it("declares durations inside the 150-200ms range", () => {
    const durations = [...tokensCss.matchAll(/--motion[\w-]*:\s*(\d+)ms/g)].map((match) =>
      Number(match[1]),
    );
    expect(durations).toEqual([150, 175, 200]);
  });

  it("keeps the Framer Motion mirror in step with the CSS", () => {
    // Framer cannot read a CSS variable for a duration, so motion.ts holds a
    // copy. This is the test that keeps the copy honest.
    expect(DURATION.fast * 1000).toBe(150);
    expect(DURATION.base * 1000).toBe(175);
    expect(DURATION.slow * 1000).toBe(200);
  });
});
