"use client";

import { motion } from "framer-motion";
import clsx from "clsx";
import type { ReactNode } from "react";

export type GlassCardVariant = "default" | "danger" | "warning" | "success";

export interface GlassCardProps {
  children: ReactNode;
  className?: string;
  /** Enables the hover lift + border brightening micro-interaction. */
  hover?: boolean;
  /** Adds an outer glow matching the variant color. */
  glow?: boolean;
  variant?: GlassCardVariant;
}

const variantStyles: Record<
  GlassCardVariant,
  { border: string; glow: string; hoverBorder: string }
> = {
  default: {
    border: "border-cyber-border/90",
    glow: "shadow-[0_0_32px_-12px_rgba(34,211,238,0.35)]",
    hoverBorder: "hover:border-cyber-accent/35",
  },
  danger: {
    border: "border-severity-critical/30",
    glow: "shadow-[0_0_32px_-10px_rgba(255,59,92,0.4)]",
    hoverBorder: "hover:border-severity-critical/60",
  },
  warning: {
    border: "border-severity-medium/30",
    glow: "shadow-[0_0_32px_-10px_rgba(255,209,102,0.35)]",
    hoverBorder: "hover:border-severity-medium/60",
  },
  success: {
    border: "border-severity-low/30",
    glow: "shadow-[0_0_32px_-10px_rgba(52,211,153,0.35)]",
    hoverBorder: "hover:border-severity-low/60",
  },
};

/**
 * Reusable glass morphism surface - the fundamental panel of the SOC UI.
 */
export default function GlassCard({
  children,
  className,
  hover = false,
  glow = false,
  variant = "default",
}: GlassCardProps) {
  const v = variantStyles[variant];

  return (
    <motion.div
      whileHover={hover ? { y: -3 } : undefined}
      transition={{ type: "spring", stiffness: 320, damping: 26 }}
      className={clsx(
        "glass-panel hairline-top relative rounded-xl p-5",
        v.border,
        glow && v.glow,
        hover && clsx("cursor-default transition-colors", v.hoverBorder),
        className,
      )}
    >
      {children}
    </motion.div>
  );
}
