import { useEffect, useState } from "react";

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window === "undefined" ? false : window.matchMedia(query).matches,
  );

  useEffect(() => {
    const list = window.matchMedia(query);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    setMatches(list.matches);
    list.addEventListener("change", onChange);
    return () => list.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

/**
 * The desktop/mobile split from §8. Below this the three panes become one, and
 * the AI companion becomes a separate view rather than a squeezed panel -
 * "we should never squeeze the three desktop panels into one narrow view".
 */
export const useIsDesktop = () => useMediaQuery("(min-width: 1024px)");
export const useIsWide = () => useMediaQuery("(min-width: 1440px)");
