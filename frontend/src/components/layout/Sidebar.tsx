import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { NavLink } from "react-router-dom";

import { ThemeSwitcher } from "@/components/common/ThemeSwitcher";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { NAV_GROUPS, SETTINGS_ITEM, type NavItem } from "@/components/layout/navigation";
import { Wordmark } from "@/components/layout/Wordmark";
import { cn } from "@/lib/utils";

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  /** Set on mobile, where the rail lives in a drawer and must close on navigate. */
  onNavigate?: (() => void) | undefined;
  className?: string | undefined;
}

function Item({
  item,
  collapsed,
  onNavigate,
}: {
  item: NavItem;
  collapsed: boolean;
  onNavigate?: (() => void) | undefined;
}) {
  const Icon = item.icon;

  const link = (
    <NavLink
      to={item.to}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          "group flex items-center gap-2 rounded-sm px-2 py-1.5 text-base transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          collapsed && "justify-center px-0",
          isActive
            ? "bg-violet-subtle font-medium text-violet"
            : "text-fg-muted hover:bg-surface-sunken hover:text-fg",
        )
      }
    >
      <Icon className="size-4 shrink-0" aria-hidden />
      {collapsed ? <span className="sr-only">{item.label}</span> : <span>{item.label}</span>}
    </NavLink>
  );

  if (!collapsed) return link;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">{item.label}</TooltipContent>
    </Tooltip>
  );
}

/**
 * The left region: navigation and workspaces (08-ui-spec.md §6).
 *
 * Groups are Workspace / Categories / Intelligence, as originally sketched
 * (§7). Settings sits at the foot, beside the theme control.
 */
export function Sidebar({ collapsed, onToggleCollapsed, onNavigate, className }: SidebarProps) {
  return (
    <nav
      aria-label="Main"
      className={cn(
        "flex h-full flex-col border-r border-line bg-surface",
        collapsed ? "w-rail-collapsed" : "w-rail",
        className,
      )}
    >
      <div
        className={cn(
          "flex h-topbar shrink-0 items-center border-b border-line",
          collapsed ? "justify-center px-2" : "justify-between px-s2",
        )}
      >
        <Wordmark badge compact={collapsed} />
        {collapsed ? null : (
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onToggleCollapsed}
            aria-label="Collapse navigation"
          >
            <PanelLeftClose aria-hidden />
          </Button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-s2">
        {NAV_GROUPS.map((group, index) => (
          <div key={group.label} className={cn(index > 0 && "mt-s2")}>
            {collapsed ? (
              index > 0 ? (
                <div className="mx-auto my-2 h-px w-6 bg-line" />
              ) : null
            ) : (
              <p className="px-2 pb-1 text-2xs font-semibold uppercase tracking-wide text-fg-subtle">
                {group.label}
              </p>
            )}
            <ul className="flex flex-col gap-0.5">
              {group.items.map((item) => (
                <li key={item.to}>
                  <Item item={item} collapsed={collapsed} onNavigate={onNavigate} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div
        className={cn(
          "flex shrink-0 flex-col gap-1 border-t border-line p-2",
          collapsed && "items-center",
        )}
      >
        <Item item={SETTINGS_ITEM} collapsed={collapsed} onNavigate={onNavigate} />
        <ThemeSwitcher collapsed={collapsed} />
        {collapsed ? (
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onToggleCollapsed}
            aria-label="Expand navigation"
          >
            <PanelLeftOpen aria-hidden />
          </Button>
        ) : null}
      </div>
    </nav>
  );
}
