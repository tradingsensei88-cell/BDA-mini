"use client";

import { useEffect } from "react";
import { animate, motion, useMotionValue, useTransform } from "framer-motion";
import clsx from "clsx";

export interface AnimatedCounterProps {
  value: number;
  /** Animation duration in seconds. */
  duration?: number;
  prefix?: string;
  suffix?: string;
  /** Fixed number of fraction digits. */
  decimals?: number;
  className?: string;
}

/**
 * Smoothly tweens from the previous value to the next one - used for KPI
 * tiles (events/sec, detected attacks, model precision, ...).
 */
export default function AnimatedCounter({
  value,
  duration = 1.4,
  prefix = "",
  suffix = "",
  decimals = 0,
  className,
}: AnimatedCounterProps) {
  const motionValue = useMotionValue(0);

  const display = useTransform(motionValue, (latest) =>
    `${prefix}${latest.toLocaleString("en-US", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    })}${suffix}`,
  );

  useEffect(() => {
    const controls = animate(motionValue, value, {
      duration,
      ease: [0.22, 1, 0.36, 1],
    });
    return () => controls.stop();
  }, [motionValue, value, duration]);

  return (
    <motion.span
      className={clsx("font-data tabular", className)}
      aria-live="polite"
      aria-atomic="true"
    >
      {display}
    </motion.span>
  );
}
