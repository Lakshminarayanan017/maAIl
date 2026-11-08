import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-pill border px-2 py-0.5 text-2xs font-medium",
  {
    variants: {
      variant: {
        neutral: "border-line bg-surface-sunken text-fg-muted",
        /** AI-derived. Soft lavender is reserved for this (08-ui-spec.md §2). */
        ai: "border-ai-border bg-ai text-ai-fg",
        success: "border-success-border bg-success text-success-fg",
        warning: "border-warning-border bg-warning text-warning-fg",
        danger: "border-danger-border bg-danger text-danger-fg",
        info: "border-info-border bg-info text-info-fg",
        violet: "border-violet/30 bg-violet-subtle text-violet",
      },
    },
    defaultVariants: { variant: "neutral" },
  },
);

export type BadgeProps = React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>;

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { badgeVariants };
