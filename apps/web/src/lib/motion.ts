import { type Variants, type Transition, useReducedMotion } from "framer-motion";

// ── Spring configs ────────────────────────────────────────────────────────
export const spring = {
  snappy: { type: "spring", stiffness: 300, damping: 30 } as Transition,
  gentle: { type: "spring", stiffness: 200, damping: 25 } as Transition,
  bouncy: { type: "spring", stiffness: 400, damping: 15 } as Transition,
} as const;

export const duration = {
  fast: 0.15,
  normal: 0.25,
  slow: 0.4,
} as const;

// ── Reusable variants ─────────────────────────────────────────────────────
export const fadeInUp: Variants = {
  hidden: { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0, transition: spring.gentle },
  exit: { opacity: 0, y: -8, transition: { duration: duration.fast } },
};

export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: duration.normal } },
  exit: { opacity: 0, transition: { duration: duration.fast } },
};

export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.95 },
  visible: { opacity: 1, scale: 1, transition: spring.snappy },
  exit: { opacity: 0, scale: 0.95, transition: { duration: duration.fast } },
};

export const slideInRight: Variants = {
  hidden: { opacity: 0, x: 20 },
  visible: { opacity: 1, x: 0, transition: spring.gentle },
  exit: { opacity: 0, x: -20, transition: { duration: duration.fast } },
};

// ── Stagger container ─────────────────────────────────────────────────────
export function staggerContainer(staggerDelay = 0.05): Variants {
  return {
    hidden: {},
    visible: {
      transition: {
        staggerChildren: staggerDelay,
        delayChildren: 0.05,
      },
    },
  };
}

export const staggerItem: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: spring.gentle },
};

// ── Button interactions ───────────────────────────────────────────────────
export const buttonHover = { scale: 1.02, transition: spring.snappy };
export const buttonTap = { scale: 0.97, transition: spring.snappy };

// ── Pulse ring for active states ──────────────────────────────────────────
export const pulseRing: Variants = {
  animate: {
    scale: [1, 1.15, 1],
    opacity: [0.5, 0, 0.5],
    transition: { duration: 2, repeat: Infinity, ease: "easeInOut" },
  },
};

// ── Reduced motion hook ───────────────────────────────────────────────────
export { useReducedMotion };
