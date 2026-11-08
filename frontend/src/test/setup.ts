import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

/**
 * jsdom has no `matchMedia`, and the shell asks for it on mount to decide
 * between the three-pane desktop layout and the single-pane mobile one.
 *
 * A stub that always answers `false` would silently run every test at phone
 * width, which is how a desktop layout ends up untested. So this one answers
 * from `window.innerWidth` and defaults to a desktop viewport; `setViewport`
 * lets a test ask for the mobile behaviour on purpose.
 */
const DESKTOP_WIDTH = 1280;

export function setViewport(width: number): void {
  Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: width });
  window.dispatchEvent(new Event("resize"));
}

function evaluate(query: string): boolean {
  const min = /\(min-width:\s*(\d+)px\)/.exec(query);
  if (min) return window.innerWidth >= Number(min[1]);
  const max = /\(max-width:\s*(\d+)px\)/.exec(query);
  if (max) return window.innerWidth <= Number(max[1]);
  if (query.includes("prefers-color-scheme: dark")) return false;
  if (query.includes("prefers-reduced-motion")) return false;
  return false;
}

Object.defineProperty(window, "matchMedia", {
  writable: true,
  configurable: true,
  value: (query: string): MediaQueryList => {
    const listeners = new Set<(event: MediaQueryListEvent) => void>();
    const list = {
      get matches() {
        return evaluate(query);
      },
      media: query,
      onchange: null,
      addEventListener: (_: string, listener: (event: MediaQueryListEvent) => void) => {
        listeners.add(listener);
      },
      removeEventListener: (_: string, listener: (event: MediaQueryListEvent) => void) => {
        listeners.delete(listener);
      },
      addListener: (listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
      removeListener: (listener: (event: MediaQueryListEvent) => void) =>
        listeners.delete(listener),
      dispatchEvent: () => true,
    };
    return list as unknown as MediaQueryList;
  },
});

/**
 * jsdom refuses to navigate and logs "Not implemented" for every attempt.
 * The OAuth flow navigates the whole page on purpose, so the call is
 * captured instead: tests can assert where the browser was sent, and the
 * output stays readable.
 */
export const navigations: string[] = [];

const realLocation = window.location;
Object.defineProperty(window, "location", {
  configurable: true,
  value: {
    ...realLocation,
    href: realLocation.href,
    origin: realLocation.origin,
    pathname: realLocation.pathname,
    search: realLocation.search,
    hash: realLocation.hash,
    assign: (url: string) => void navigations.push(url),
    replace: (url: string) => void navigations.push(url),
    reload: () => undefined,
    toString: () => realLocation.href,
  },
});

// Radix measures and scrolls; jsdom implements neither.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn();
}
if (!window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

beforeEach(() => {
  setViewport(DESKTOP_WIDTH);
  navigations.length = 0;
});

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("data-theme");
  localStorage.clear();
});
