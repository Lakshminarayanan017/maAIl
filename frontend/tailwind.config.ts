import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

/**
 * Every colour resolves to a CSS variable holding HSL channels, which is what
 * makes `bg-violet/10` work. The variables themselves live in
 * `src/styles/tokens.css`, where the locked palette is also kept verbatim.
 *
 * `dark:` is wired to the same two rules the tokens use — a pinned
 * `[data-theme="dark"]`, or the system preference when the user has not pinned
 * light. Most components need no `dark:` at all, because the token they read
 * has already changed.
 */
const withAlpha = (variable: string) => `hsl(var(${variable}) / <alpha-value>)`;

export default {
  darkMode: [
    "variant",
    [
      '&:is([data-theme="dark"] *)',
      '@media (prefers-color-scheme: dark) { &:is(:root:not([data-theme="light"]) *) }',
    ],
  ],
  content: ["./index.html", "./src/**/*.{ts,tsx}", "./.storybook/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: withAlpha("--bg"),
        surface: {
          DEFAULT: withAlpha("--surface"),
          raised: withAlpha("--surface-raised"),
          sunken: withAlpha("--surface-sunken"),
        },
        fg: {
          DEFAULT: withAlpha("--fg"),
          muted: withAlpha("--fg-muted"),
          subtle: withAlpha("--fg-subtle"),
          "on-violet": withAlpha("--fg-on-violet"),
        },
        // `border-line` rather than `border-border`, which reads badly.
        line: {
          DEFAULT: withAlpha("--border"),
          strong: withAlpha("--border-strong"),
        },
        ring: withAlpha("--ring"),
        violet: {
          DEFAULT: withAlpha("--violet"),
          hover: withAlpha("--violet-hover"),
          active: withAlpha("--violet-active"),
          subtle: withAlpha("--violet-subtle"),
        },
        // AI highlights. Soft lavender, and nothing else uses it.
        ai: {
          DEFAULT: withAlpha("--ai-surface"),
          hover: withAlpha("--ai-surface-hover"),
          border: withAlpha("--ai-border"),
          fg: withAlpha("--ai-fg"),
        },
        success: {
          DEFAULT: withAlpha("--success"),
          fg: withAlpha("--success-fg"),
          border: withAlpha("--success-border"),
        },
        warning: {
          DEFAULT: withAlpha("--warning"),
          fg: withAlpha("--warning-fg"),
          border: withAlpha("--warning-border"),
        },
        danger: {
          DEFAULT: withAlpha("--danger"),
          fg: withAlpha("--danger-fg"),
          border: withAlpha("--danger-border"),
        },
        info: {
          DEFAULT: withAlpha("--info"),
          fg: withAlpha("--info-fg"),
          border: withAlpha("--info-border"),
        },
      },

      // 10-14px, and nothing outside it.
      borderRadius: {
        sm: "var(--radius-sm)",
        DEFAULT: "var(--radius)",
        md: "var(--radius)",
        lg: "var(--radius-lg)",
        pill: "var(--radius-pill)",
      },

      // The 8px scale. `p-s2` is 16px. Tailwind's own scale stays available
      // for the sub-8px cases a chip or an icon gap genuinely needs.
      spacing: {
        s1: "var(--space-1)",
        s2: "var(--space-2)",
        s3: "var(--space-3)",
        s4: "var(--space-4)",
        s5: "var(--space-5)",
        s6: "var(--space-6)",
        s7: "var(--space-7)",
        s8: "var(--space-8)",
        s9: "var(--space-9)",
        s10: "var(--space-10)",
        rail: "var(--rail-width)",
        "rail-collapsed": "var(--rail-width-collapsed)",
        "ai-panel": "var(--ai-panel-width)",
        "ai-panel-wide": "var(--ai-panel-width-wide)",
        topbar: "var(--topbar-height)",
      },

      fontFamily: {
        brand: "var(--font-brand)",
        body: "var(--font-body)",
        mono: "var(--font-mono)",
      },

      fontSize: {
        "2xs": ["11px", { lineHeight: "16px", letterSpacing: "0.01em" }],
        xs: ["12px", { lineHeight: "16px" }],
        sm: ["13px", { lineHeight: "20px" }],
        base: ["14px", { lineHeight: "22px" }],
        md: ["15px", { lineHeight: "24px" }],
        lg: ["17px", { lineHeight: "26px" }],
        xl: ["20px", { lineHeight: "28px", letterSpacing: "-0.01em" }],
        "2xl": ["24px", { lineHeight: "32px", letterSpacing: "-0.015em" }],
        "3xl": ["30px", { lineHeight: "38px", letterSpacing: "-0.02em" }],
        "4xl": ["38px", { lineHeight: "44px", letterSpacing: "-0.025em" }],
        "5xl": ["48px", { lineHeight: "54px", letterSpacing: "-0.03em" }],
      },

      boxShadow: {
        rest: "var(--shadow-rest)",
        raised: "var(--shadow-raised)",
        overlay: "var(--shadow-overlay)",
      },

      transitionDuration: {
        fast: "var(--motion-fast)",
        DEFAULT: "var(--motion)",
        slow: "var(--motion-slow)",
      },

      transitionTimingFunction: {
        DEFAULT: "var(--ease)",
        out: "var(--ease-out)",
      },

      keyframes: {
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-in-right": {
          from: { transform: "translateX(8px)", opacity: "0" },
          to: { transform: "translateX(0)", opacity: "1" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },

      animation: {
        "fade-in": "fade-in var(--motion) var(--ease-out)",
        "slide-in-right": "slide-in-right var(--motion) var(--ease-out)",
      },
    },
  },
  plugins: [animate],
} satisfies Config;
