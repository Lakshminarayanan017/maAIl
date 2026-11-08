import { create } from "zustand";

export type ThemePreference = "light" | "dark" | "system";

const STORAGE_KEY = "maail.theme";

/**
 * Light, dark or follow the system (08-ui-spec.md §5).
 *
 * `system` is the absence of `data-theme`, which lets the media query in
 * `tokens.css` decide. Pinning writes `data-theme="light"` or `"dark"`, which
 * the guarded dark block in the same file respects. `index.html` applies the
 * stored value before first paint so a pinned dark theme never flashes white.
 */
function readStored(): ThemePreference {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value === "light" || value === "dark" || value === "system") return value;
  } catch {
    /* private mode or blocked storage: fall through to system */
  }
  return "system";
}

export function applyTheme(preference: ThemePreference): void {
  const root = document.documentElement;
  if (preference === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", preference);
  }
}

function persist(preference: ThemePreference): void {
  try {
    localStorage.setItem(STORAGE_KEY, preference);
  } catch {
    /* the preference still applies for this session */
  }
}

interface ThemeState {
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
}

export const useThemeStore = create<ThemeState>((set) => ({
  preference: readStored(),
  setPreference: (preference) => {
    applyTheme(preference);
    persist(preference);
    set({ preference });
  },
}));

/** True when the page is currently rendering dark, pinned or not. */
export function resolvedIsDark(preference: ThemePreference): boolean {
  if (preference === "dark") return true;
  if (preference === "light") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}
