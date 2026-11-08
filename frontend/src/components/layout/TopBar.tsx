import { Menu, Search, Sparkles } from "lucide-react";
import { useLocation } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { navItemFor } from "@/components/layout/navigation";
import { useIsDesktop } from "@/hooks/useMediaQuery";
import { useAiPanel } from "@/stores/aiPanel";

interface TopBarProps {
  onOpenNav: () => void;
}

/**
 * The centre region's header. It names the current screen and holds the two
 * controls that follow the user everywhere: search and the AI entry point.
 *
 * Search is wired in phase 2 and the panel fills in phase 5, so both are
 * present and inert here rather than absent — the layout they need is part of
 * what phase 0 is proving.
 */
export function TopBar({ onOpenNav }: TopBarProps) {
  const { pathname } = useLocation();
  const current = navItemFor(pathname);
  const panelState = useAiPanel((state) => state.state);
  const toggle = useAiPanel((state) => state.toggle);
  const isDesktop = useIsDesktop();

  return (
    <header className="flex h-topbar shrink-0 items-center gap-s1 border-b border-line bg-surface px-s2">
      {isDesktop ? null : (
        <Button variant="ghost" size="icon-sm" onClick={onOpenNav} aria-label="Open navigation">
          <Menu aria-hidden />
        </Button>
      )}

      <div className="min-w-0 flex-1">
        <h1 className="truncate font-brand text-md font-semibold text-fg">
          {current?.label ?? "Maail"}
        </h1>
      </div>

      <Button variant="ghost" size="icon-sm" aria-label="Search" disabled>
        <Search aria-hidden />
      </Button>

      {isDesktop ? (
        <Button
          variant={panelState === "collapsed" ? "ghost" : "ai"}
          size="icon-sm"
          onClick={toggle}
          aria-label="AI panel"
          aria-pressed={panelState !== "collapsed"}
        >
          <Sparkles aria-hidden />
        </Button>
      ) : null}
    </header>
  );
}
