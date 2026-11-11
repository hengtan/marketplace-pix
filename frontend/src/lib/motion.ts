import type { Transition, Variants } from "motion/react";

export const EASE = [0.16, 1, 0.3, 1] as const;
export const SPRING: Transition = { type: "spring", stiffness: 380, damping: 30, mass: 0.8 };
export const SPRING_SOFT: Transition = { type: "spring", stiffness: 160, damping: 22 };
export const SPRING_POP: Transition = { type: "spring", stiffness: 520, damping: 18 };

export const stagger = (step = 0.06, delay = 0): Variants => ({
  hidden: {},
  show: { transition: { staggerChildren: step, delayChildren: delay } },
});

export const rise: Variants = {
  hidden: { opacity: 0, y: 22 },
  show: { opacity: 1, y: 0, transition: { duration: 0.75, ease: EASE } },
};

export const fade: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { duration: 0.6, ease: EASE } },
};

export const pop: Variants = {
  hidden: { opacity: 0, scale: 0.92, y: 12 },
  show: { opacity: 1, scale: 1, y: 0, transition: SPRING },
};

export function prefersReducedMotion(): boolean {
  return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function finePointer(): boolean {
  return (
    typeof matchMedia === "function" && matchMedia("(hover: hover) and (pointer: fine)").matches
  );
}
