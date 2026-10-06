"use client";

import { motion } from "framer-motion";
import clsx from "clsx";
import AnimatedCounter from "@/components/ui/AnimatedCounter";

export interface MetricGaugeProps {
  /** 0-100 metric value. */
  value: number;
  label: string;
  /** Small caption under the numeric value. */
  sublabel?: string;
  /** Stroke color (hex). */
  color?: string;
  size?: number;
  strokeWidth?: number;
  decimals?: number;
  className?: string;
}

/**
 * Animated circular gauge (custom SVG) used for the ML performance metrics
 * and the investigation drawer confidence / risk dials.
 */
export default function MetricGauge({
  value,
  label,
  sublabel,
  color = "#22d3ee",
  size = 148,
  strokeWidth = 10,
  decimals = 1,
  className,
}: MetricGaugeProps) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.min(100, Math.max(0, value));
  const dashOffset = circumference * (1 - clamped / 100);

  /* End-cap dot position (SVG is rotated -90deg so 0% starts at 12 o'clock). */
  const angle = (clamped / 100) * Math.PI * 2;
  const dotX = size / 2 + radius * Math.cos(angle);
  const dotY = size / 2 + radius * Math.sin(angle);

  return (
    <div className={clsx("flex flex-col items-center", className)}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          className="-rotate-90"
          role="img"
          aria-label={`${label}: ${value}${sublabel ? ` ${sublabel}` : ""}`}
        >
          {/* Track */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="rgba(23, 35, 61, 0.9)"
            strokeWidth={strokeWidth}
          />
          {/* Progress arc */}
          <motion.circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={circumference}
            initial={{ strokeDashoffset: circumference }}
            animate={{ strokeDashoffset: dashOffset }}
            transition={{ duration: 1.5, ease: [0.22, 1, 0.36, 1], delay: 0.15 }}
            style={{ filter: `drop-shadow(0 0 6px ${color}59)` }}
          />
          {/* Leading edge dot */}
          <motion.circle
            cx={dotX}
            cy={dotY}
            r={strokeWidth / 2 - 1}
            fill="#04070F"
            stroke={color}
            strokeWidth={2}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 1.25 }}
          />
        </svg>

        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <AnimatedCounter
            value={value}
            decimals={decimals}
            suffix="%"
            duration={1.5}
            className="text-[22px] font-semibold text-slate-50"
          />
          {sublabel && (
            <span className="mt-0.5 font-data text-[9px] tracking-[0.18em] text-cyber-muted uppercase">
              {sublabel}
            </span>
          )}
        </div>
      </div>

      <p className="mt-3 font-data text-[11px] tracking-[0.18em] text-cyber-muted uppercase">
        {label}
      </p>
    </div>
  );
}
