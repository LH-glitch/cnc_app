"use client";

import { motion, type HTMLMotionProps } from "framer-motion";

// ── Shared easing ──────────────────────────────────────────────────────────────

const EASE = [0.25, 0.46, 0.45, 0.94] as const;

// ── Variants ───────────────────────────────────────────────────────────────────

export const fadeUpVariants = {
  hidden: { opacity: 0, y: 60 },
  show:   { opacity: 1, y: 0, transition: { duration: 0.9, ease: EASE } },
};

export const staggerContainerVariants = {
  hidden: {},
  show:   { transition: { staggerChildren: 0.15, delayChildren: 0.1 } },
};

// ── FadeIn ─────────────────────────────────────────────────────────────────────
// Single element: fades up independently (use outside a FadeInGroup).

type DivMotionProps = Omit<HTMLMotionProps<"div">, "variants" | "initial" | "animate">;

interface FadeInProps extends DivMotionProps {
  delay?: number;
  children: React.ReactNode;
}

export function FadeIn({ delay = 0, children, style, ...rest }: FadeInProps) {
  return (
    <motion.div
      initial="hidden"
      animate="show"
      variants={{
        hidden: { opacity: 0, y: 60 },
        show:   { opacity: 1, y: 0, transition: { duration: 0.9, delay, ease: EASE } },
      }}
      style={style}
      {...rest}
    >
      {children}
    </motion.div>
  );
}

// ── FadeInGroup ────────────────────────────────────────────────────────────────
// Stagger container — cascades FadeInItem children in sequence.
// Accepts any div style/className via spread.

interface FadeInGroupProps extends DivMotionProps {
  children: React.ReactNode;
}

export function FadeInGroup({ children, style, ...rest }: FadeInGroupProps) {
  return (
    <motion.div
      initial="hidden"
      animate="show"
      variants={staggerContainerVariants}
      style={style}
      {...rest}
    >
      {children}
    </motion.div>
  );
}

// ── FadeInItem ─────────────────────────────────────────────────────────────────
// Stagger child — must be a direct child of FadeInGroup.
// Picks up the parent's stagger automatically via variants.

type FadeInItemProps = Omit<HTMLMotionProps<"div">, "variants"> & {
  children: React.ReactNode;
};

export function FadeInItem({ children, style, ...rest }: FadeInItemProps) {
  return (
    <motion.div variants={fadeUpVariants} style={style} {...rest}>
      {children}
    </motion.div>
  );
}
