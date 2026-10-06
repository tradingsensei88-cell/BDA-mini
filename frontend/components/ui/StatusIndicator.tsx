"use client";

import clsx from "clsx";
import type { ServiceStatus } from "@/types";

export interface StatusIndicatorProps {
  status: ServiceStatus;
  label?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const dotSize: Record<NonNullable<StatusIndicatorProps["size"]>, string> = {
  sm: "h-1.5 w-1.5",
  md: "h-2.5 w-2.5",
  lg: "h-3.5 w-3.5",
};

const statusConfig: Record<
  ServiceStatus,
  { color: string; ring: string; text: string; label: string }
> = {
  online: {
    color: "bg-emerald-400 text-emerald-400",
    ring: "bg-emerald-400/60",
    text: "text-emerald-300",
    label: "Online",
  },
  warning: {
    color: "bg-amber-400 text-amber-400",
    ring: "bg-amber-400/60",
    text: "text-amber-300",
    label: "Warning",
  },
  offline: {
    color: "bg-rose-500 text-rose-500",
    ring: "bg-rose-500/50",
    text: "text-rose-300",
    label: "Offline",
  },
  connecting: {
    color: "bg-sky-400 text-sky-400",
    ring: "bg-sky-400/50",
    text: "text-sky-300",
    label: "Connecting",
  },
};

/**
 * Pulsing status dot used across service grids, the header, and pipeline nodes.
 * `connecting` renders an animated spinner ring instead of a static pulse.
 */
export default function StatusIndicator({
  status,
  label,
  size = "md",
  className,
}: StatusIndicatorProps) {
  const config = statusConfig[status];
  const resolvedLabel = label ?? config.label;

  return (
    <span className={clsx("inline-flex items-center gap-2", className)}>
      <span className="relative inline-flex items-center justify-center">
        {status === "connecting" ? (
          <span
            className={clsx(
              "inline-block animate-spin rounded-full border-2 border-current/30 border-t-current",
              dotSize[size],
              config.text,
            )}
            aria-hidden="true"
          />
        ) : (
          <>
            {status !== "offline" && (
              <span
                className={clsx(
                  "absolute inline-flex h-full w-full animate-ping rounded-full opacity-60",
                  config.ring,
                )}
                style={{ animationDuration: status === "warning" ? "1.6s" : "2.2s" }}
                aria-hidden="true"
              />
            )}
            <span
              className={clsx(
                "relative inline-flex rounded-full",
                dotSize[size],
                config.color,
                status === "offline"
                  ? "shadow-[0_0_8px_-1px_rgba(244,63,94,0.9)]"
                  : "shadow-[0_0_10px_-1px_currentColor]",
              )}
              aria-hidden="true"
            />
          </>
        )}
      </span>
      {resolvedLabel && (
        <span
          className={clsx(
            "font-data text-xs tracking-wide",
            config.text,
          )}
        >
          {resolvedLabel}
        </span>
      )}
    </span>
  );
}
