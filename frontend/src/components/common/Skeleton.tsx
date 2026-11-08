import type * as React from "react";

import { cn } from "@/lib/utils";

/**
 * A skeleton is a shape, not a spinner. The spec asks for skeleton loaders
 * specifically for email synchronization (08-ui-spec.md §4), because sync is
 * the one wait long enough that a spinner would read as a hang.
 */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded-sm bg-surface-sunken", className)}
      {...props}
    />
  );
}

export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-2", className)} aria-hidden>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton
          key={index}
          className="h-3.5"
          style={{ width: index === lines - 1 ? "62%" : "100%" }}
        />
      ))}
    </div>
  );
}

/**
 * A loading region that announces itself. Screen readers get the label;
 * everyone else gets the shapes.
 */
export function SkeletonRegion({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div role="status" aria-busy="true" aria-live="polite" className={className}>
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}
