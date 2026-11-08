import type { Preview } from "@storybook/react";

import "../src/styles/index.css";

/**
 * Storybook is where mocks live (execution plan, rule 1). The running app gets
 * real data or an empty state; a story gets whatever it needs to show a
 * component in every state it has.
 *
 * The theme toolbar writes `data-theme` on <html>, which is exactly what the
 * app does, so a story proves the token layer rather than a Storybook-only
 * approximation of it.
 */
const preview: Preview = {
  parameters: {
    layout: "centered",
    controls: { expanded: true },
    backgrounds: { disable: true },
    a11y: { test: "todo" },
  },
  globalTypes: {
    theme: {
      description: "Theme",
      defaultValue: "system",
      toolbar: {
        title: "Theme",
        icon: "paintbrush",
        items: [
          { value: "light", title: "Light" },
          { value: "dark", title: "Dark" },
          { value: "system", title: "System" },
        ],
        dynamicTitle: true,
      },
    },
  },
  decorators: [
    (Story, context) => {
      const theme = context.globals.theme as string;
      const root = document.documentElement;
      if (theme === "system") root.removeAttribute("data-theme");
      else root.setAttribute("data-theme", theme);
      document.body.classList.add("bg-bg", "text-fg");
      return Story();
    },
  ],
};

export default preview;
