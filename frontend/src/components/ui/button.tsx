import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Radii stay inside 10-14px, borders carry the elevation instead of shadows,
 * and the transition duration comes from the motion tokens, because
 * `transitionDuration.DEFAULT` is wired to `--motion` in the Tailwind config
 * (08-ui-spec.md §4).
 */
const buttonVariants = cva(
  cn(
    "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-sm",
    "font-body text-base font-medium transition-colors",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
    "focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
    "disabled:pointer-events-none disabled:opacity-50",
    "[&_svg]:size-4 [&_svg]:shrink-0",
  ),
  {
    variants: {
      variant: {
        primary: "bg-violet text-fg-on-violet hover:bg-violet-hover active:bg-violet-active",
        secondary: "border border-line bg-surface text-fg hover:bg-surface-sunken",
        ghost: "text-fg-muted hover:bg-surface-sunken hover:text-fg",
        subtle: "bg-violet-subtle text-violet hover:bg-ai",
        /** For anything the AI produced or proposes. Lavender, never violet. */
        ai: "border border-ai-border bg-ai text-ai-fg hover:bg-ai-hover",
        danger: "border border-danger-border bg-danger text-danger-fg hover:bg-danger/80",
        link: "text-violet underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-8 px-3 text-sm",
        md: "h-10 px-4",
        lg: "h-12 px-6 text-md",
        icon: "size-10",
        "icon-sm": "size-8",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Component = asChild ? Slot : "button";
    return (
      <Component
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { buttonVariants };
