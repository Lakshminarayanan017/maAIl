import type { Transition } from "framer-motion";

/**
 * Smooth 150-200ms interactions (08-ui-spec.md §4). The numbers live in
 * `tokens.css` as well; these mirror them for Framer Motion, which cannot read
 * a CSS variable for a duration.
 *
 * A test asserts the two stay in step.
 */
export const DURATION = {
  fast: 0.15,
  base: 0.175,
  slow: 0.2,
} as const;

export const EASE = [0.32, 0.72, 0, 1] as const;
export const EASE_OUT = [0.16, 1, 0.3, 1] as const;

export const transition: Transition = {
  duration: DURATION.base,
  ease: EASE,
};

export const transitionFast: Transition = {
  duration: DURATION.fast,
  ease: EASE_OUT,
};

/** The AI panel slides in from the right; nothing in the app moves further. */
export const panelVariants = {
  hidden: { x: 12, opacity: 0 },
  visible: { x: 0, opacity: 1 },
  exit: { x: 12, opacity: 0 },
} as const;

export const fade = {
  hidden: { opacity: 0 },
  visible: { opacity: 1 },
  exit: { opacity: 0 },
} as const;
