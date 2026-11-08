import {
  Bot,
  Code2,
  GraduationCap,
  Inbox,
  LayoutDashboard,
  Lightbulb,
  Megaphone,
  MessageSquare,
  Settings,
  Sparkles,
  Star,
  Tag,
  Terminal,
  ListChecks,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

/**
 * Global navigation, exactly as specified (08-ui-spec.md §7).
 *
 * Three groups: Workspace, Categories, Intelligence. Settings sits outside
 * them, at the foot of the rail.
 *
 * `phase` is the phase of 09-execution-plan.md that fills the route in. It is
 * shown on the stub, so a route that is deliberately empty cannot be mistaken
 * for a route that is broken.
 */
export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** The screen number in 08-ui-spec.md §9, when the route is a screen. */
  screen?: string;
  phase: number;
  purpose: string;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      {
        to: "/overview",
        label: "Overview",
        icon: LayoutDashboard,
        screen: "03",
        phase: 7,
        purpose: "Personal command center",
      },
      {
        to: "/inbox",
        label: "Inbox",
        icon: Inbox,
        screen: "04",
        phase: 2,
        purpose: "Complete email workspace",
      },
      {
        to: "/priority",
        label: "Priority",
        icon: Star,
        phase: 6,
        purpose: "Important messages",
      },
    ],
  },
  {
    label: "Categories",
    items: [
      {
        to: "/categories/opportunities",
        label: "Opportunities",
        icon: Sparkles,
        phase: 14,
        purpose: "Internships, roles and openings",
      },
      {
        to: "/categories/development",
        label: "Development",
        icon: Code2,
        phase: 13,
        purpose: "Technical threads",
      },
      {
        to: "/categories/academics",
        label: "Academics",
        icon: GraduationCap,
        phase: 6,
        purpose: "Coursework and institutional mail",
      },
      {
        to: "/categories/announcements",
        label: "Announcements",
        icon: Megaphone,
        phase: 6,
        purpose: "Broadcast mail worth keeping",
      },
      {
        to: "/categories/promotions",
        label: "Promotions",
        icon: Tag,
        phase: 6,
        purpose: "Marketing, kept out of the way",
      },
    ],
  },
  {
    label: "Intelligence",
    items: [
      {
        to: "/companion",
        label: "AI Companion",
        icon: MessageSquare,
        screen: "06",
        phase: 10,
        purpose: "Conversational assistant",
      },
      {
        to: "/developer",
        label: "Developer Hub",
        icon: Terminal,
        screen: "07",
        phase: 13,
        purpose: "Technical email intelligence",
      },
      {
        to: "/agents",
        label: "Agents",
        icon: Bot,
        screen: "08",
        phase: 14,
        purpose: "Specialized AI agents",
      },
      {
        to: "/tasks",
        label: "Tasks & Deadlines",
        icon: ListChecks,
        screen: "09",
        phase: 9,
        purpose: "Extracted action items",
      },
      {
        to: "/insights",
        label: "Insights",
        icon: Lightbulb,
        screen: "10",
        phase: 15,
        purpose: "Communication intelligence",
      },
    ],
  },
];

export const SETTINGS_ITEM: NavItem = {
  to: "/settings",
  label: "Settings",
  icon: Settings,
  screen: "11",
  phase: 11,
  purpose: "Personalization and integrations",
};

export const ALL_NAV_ITEMS: NavItem[] = [
  ...NAV_GROUPS.flatMap((group) => group.items),
  SETTINGS_ITEM,
];

export function navItemFor(pathname: string): NavItem | undefined {
  return ALL_NAV_ITEMS.find((item) => pathname === item.to || pathname.startsWith(`${item.to}/`));
}
