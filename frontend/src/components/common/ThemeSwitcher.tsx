import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { applyTheme, useThemeStore, type ThemePreference } from "@/stores/theme";

const OPTIONS: ReadonlyArray<{ value: ThemePreference; label: string; icon: typeof Sun }> = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

/**
 * Light / dark / system (08-ui-spec.md §5).
 *
 * `system` removes `data-theme` so the media query in `tokens.css` decides;
 * the other two pin it. The store is the source of truth, but the attribute is
 * applied on mount as well, because `index.html` runs before React and the two
 * must agree.
 */
export function ThemeSwitcher({ collapsed = false }: { collapsed?: boolean }) {
  const preference = useThemeStore((state) => state.preference);
  const setPreference = useThemeStore((state) => state.setPreference);

  useEffect(() => {
    applyTheme(preference);
  }, [preference]);

  const active = OPTIONS.find((option) => option.value === preference) ?? OPTIONS[2]!;
  const ActiveIcon = active.icon;

  const trigger = (
    <Button
      variant="ghost"
      size={collapsed ? "icon-sm" : "sm"}
      className={collapsed ? "" : "w-full justify-start gap-2"}
      aria-label={`Theme: ${active.label}`}
    >
      <ActiveIcon aria-hidden />
      {collapsed ? null : <span className="text-fg-muted">{active.label}</span>}
    </Button>
  );

  return (
    <DropdownMenu>
      {collapsed ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
          </TooltipTrigger>
          <TooltipContent side="right">Theme</TooltipContent>
        </Tooltip>
      ) : (
        <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      )}
      <DropdownMenuContent align={collapsed ? "start" : "end"} side="top">
        <DropdownMenuLabel>Appearance</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={preference}
          onValueChange={(value) => setPreference(value as ThemePreference)}
        >
          {OPTIONS.map(({ value, label, icon: Icon }) => (
            <DropdownMenuRadioItem key={value} value={value}>
              <Icon aria-hidden className="text-fg-muted" />
              {label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
