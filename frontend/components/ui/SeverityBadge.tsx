"use client";

import clsx from "clsx";
import {
  AlertCircle,
  AlertTriangle,
  Info,
  Shield,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { SeverityLevel } from "@/types";

export interface SeverityBadgeProps {
  level: SeverityLevel;
  /** Override the default level name (e.g. "Critical" -> "P1"). */
  label?: string;
  size?: "sm" | "md";
  className?: string;
}

interface SeverityStyle {
  icon: LucideIcon;
  text: string;
  bg: string;
  border: string;
  dot: string;
}

/**
 * Color + icon mapping is aligned with the `severity.*` scale in
 * tailwind.config.ts so badges, charts, and sparklines stay consistent.
 */
const severityStyles: Record<SeverityLevel, SeverityStyle> = {
  critical: {
    icon: AlertTriangle,
    text: "text-severity-critical",
    bg: "bg-severity-critical/10",
    border: "border-severity-critical/35",
    dot: "bg-severity-critical",
  },
  high: {
    icon: AlertCircle,
    text: "text-severity-high",
    bg: "bg-severity-high/10",
    border: "border-severity-high/35",
    dot: "bg-severity-high",
  },
  medium: {
    icon: Info,
    text: "text-severity-medium",
    bg: "bg-severity-medium/10",
    border: "border-severity-medium/35",
    dot: "bg-severity-medium",
  },
  low: {
    icon: Shield,
    text: "text-severity-low",
    bg: "bg-severity-low/10",
    border: "border-severity-low/35",
    dot: "bg-severity-low",
  },
  info: {
    icon: Info,
    text: "text-severity-info",
    bg: "bg-severity-info/10",
    border: "border-severity-info/35",
    dot: "bg-severity-info",
  },
};

const defaultLabels: Record<SeverityLevel, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  info: "Info",
};

/**
 * Compact severity chip used on alerts, threat feeds, and event tables.
 */
export default function SeverityBadge({
  level,
  label,
  size = "md",
  className,
}: SeverityBadgeProps) {
  const style = severityStyles[level];
  const Icon = style.icon;
  const resolvedLabel = label ?? defaultLabels[level];

  const isCritical = level === "critical";

  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-md border font-data font-medium tracking-wide uppercase",
        style.text,
        style.bg,
        style.border,
        isCritical && "shadow-[0_0_16px_-6px_rgba(255,59,92,0.6)]",
        size === "sm" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-1 text-[11px]",
        className,
      )}
    >
      <Icon
        className={clsx(size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5")}
        strokeWidth={2.25}
        aria-hidden="true"
      />
      {resolvedLabel}
    </span>
  );
}
