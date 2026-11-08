import type { Meta, StoryObj } from "@storybook/react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * The locked design system, rendered. Switch the theme in the toolbar: every
 * swatch below reads its value from the same CSS variable the app does, so if
 * dark mode is wrong here it is wrong everywhere.
 */
const meta: Meta = {
  title: "Design system/Tokens",
  parameters: { layout: "fullscreen" },
};
export default meta;

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-s2 border-b border-line px-s3 py-s3">
      <div>
        <h2 className="font-brand text-xl font-bold text-fg">{title}</h2>
        {note ? <p className="mt-1 max-w-2xl text-base text-fg-muted">{note}</p> : null}
      </div>
      {children}
    </section>
  );
}

const PALETTE = [
  { hex: "#F7F6F3", name: "Warm white", role: "Light background", token: "bg" },
  { hex: "#FFFFFF", name: "Pure white", role: "Cards and panels", token: "surface" },
  { hex: "#8B70D6", name: "Maail violet", role: "Primary actions", token: "violet" },
  { hex: "#25232B", name: "Charcoal", role: "Dark theme surfaces", token: "fg" },
  { hex: "#E8E2F5", name: "Soft lavender", role: "AI highlights", token: "ai" },
  { hex: "#DDEBE2", name: "Soft green", role: "Success states", token: "success" },
] as const;

// Written out rather than interpolated. Tailwind scans source for literal
// class names, so `bg-${token}` would compile to nothing at all.
const SEMANTIC = [
  ["bg", "bg-bg"],
  ["surface", "bg-surface"],
  ["surface-raised", "bg-surface-raised"],
  ["surface-sunken", "bg-surface-sunken"],
  ["violet", "bg-violet"],
  ["violet-subtle", "bg-violet-subtle"],
  ["ai", "bg-ai"],
  ["success", "bg-success"],
  ["warning", "bg-warning"],
  ["danger", "bg-danger"],
  ["info", "bg-info"],
] as const;

export const Palette: StoryObj = {
  render: () => (
    <Section
      title="Colour palette"
      note="The six locked values, and the semantic tokens derived from them. The hex is the specification; the token is what components use, because it changes with the theme."
    >
      <div className="grid gap-s2 sm:grid-cols-2 lg:grid-cols-3">
        {PALETTE.map((entry) => (
          <div key={entry.hex} className="overflow-hidden rounded-md border border-line">
            <div className="h-20 w-full" style={{ backgroundColor: entry.hex }} />
            <div className="flex flex-col gap-0.5 bg-surface p-s2">
              <p className="font-brand text-base font-semibold text-fg">{entry.name}</p>
              <p className="font-mono text-xs text-fg-muted">{entry.hex}</p>
              <p className="text-sm text-fg-muted">{entry.role}</p>
            </div>
          </div>
        ))}
      </div>

      <h3 className="mt-s2 font-brand text-md font-semibold text-fg">Semantic tokens</h3>
      <div className="flex flex-wrap gap-s1">
        {SEMANTIC.map(([token, swatch]) => (
          <div key={token} className="flex items-center gap-2 rounded-sm border border-line p-1.5">
            <span className={cn("size-8 rounded-sm border border-line", swatch)} />
            <code className="font-mono text-xs text-fg-muted">{token}</code>
          </div>
        ))}
      </div>
    </Section>
  ),
};

export const Typography: StoryObj = {
  render: () => (
    <Section
      title="Typography"
      note="Plus Jakarta Sans for brand and major headings, Inter for body and email content, JetBrains Mono for technical information."
    >
      <div className="flex flex-col gap-s2">
        <div>
          <p className="text-2xs uppercase tracking-wide text-fg-subtle">
            Plus Jakarta Sans / brand
          </p>
          <p className="font-brand text-4xl font-bold text-fg">Your inbox deserves a brain.</p>
          <p className="font-brand text-2xl font-semibold text-fg">Understand more. Manage less.</p>
        </div>
        <div>
          <p className="text-2xs uppercase tracking-wide text-fg-subtle">Inter / body and email</p>
          <p className="email-prose">
            Thanks for the quick turnaround. Could you confirm whether the migration window is still
            Friday evening? If it slips we will need to tell the on-call rotation.
          </p>
        </div>
        <div>
          <p className="text-2xs uppercase tracking-wide text-fg-subtle">
            JetBrains Mono / technical
          </p>
          <pre className="rounded-sm border border-line bg-surface-sunken p-s2 font-mono text-xs text-fg">
            {
              'Traceback (most recent call last):\n  File "sync/engine.py", line 118\n    HttpError 404: historyId not found'
            }
          </pre>
        </div>
      </div>
    </Section>
  ),
};

const SPACES = [
  ["s1", "w-s1"],
  ["s2", "w-s2"],
  ["s3", "w-s3"],
  ["s4", "w-s4"],
  ["s5", "w-s5"],
  ["s6", "w-s6"],
  ["s7", "w-s7"],
  ["s8", "w-s8"],
] as const;

export const SpacingAndRadii: StoryObj = {
  render: () => (
    <Section
      title="Spacing and radii"
      note="A consistent 8px scale, and radii from 10px to 14px. Nothing in the app rounds tighter or looser than that range."
    >
      <div className="flex flex-col gap-1">
        {SPACES.map(([space, width], index) => (
          <div key={space} className="flex items-center gap-s2">
            <code className="w-10 font-mono text-xs text-fg-muted">{space}</code>
            <div className={cn("h-3 rounded-sm bg-violet", width)} />
            <span className="text-xs text-fg-subtle">{(index + 1) * 8}px</span>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-s2">
        {(
          [
            ["rounded-sm", "10px"],
            ["rounded-md", "12px"],
            ["rounded-lg", "14px"],
            ["rounded-pill", "999px"],
          ] as const
        ).map(([radius, label]) => (
          <div key={radius} className="flex flex-col items-center gap-1">
            <div className={cn("size-20 border border-line bg-surface", radius)} />
            <code className="font-mono text-2xs text-fg-muted">{label}</code>
          </div>
        ))}
      </div>
    </Section>
  ),
};

export const Motion: StoryObj = {
  render: () => (
    <Section
      title="Motion"
      note="Smooth 150-200ms interactions. Hover a card: the duration comes from the token, so reduced-motion settings clamp all of it in one place."
    >
      <div className="flex flex-wrap gap-s2">
        {(
          [
            ["duration-fast", "150ms"],
            ["duration", "175ms"],
            ["duration-slow", "200ms"],
          ] as const
        ).map(([duration, label]) => (
          <div
            key={label}
            className={cn(
              "flex size-28 cursor-pointer items-center justify-center rounded-md border",
              "border-line bg-surface text-sm text-fg-muted transition-colors",
              "hover:bg-ai hover:text-ai-fg",
              duration,
            )}
          >
            {label}
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-s1">
        <Badge variant="ai">AI highlight</Badge>
        <Badge variant="success">Success</Badge>
        <Badge variant="warning">Needs attention</Badge>
        <Badge variant="danger">Failed</Badge>
        <Badge variant="info">Info</Badge>
        <Badge>Neutral</Badge>
      </div>
    </Section>
  ),
};
