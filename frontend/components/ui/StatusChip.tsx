"use client";

import clsx from "clsx";
import type { AlertWorkflowStatus } from "@/types";

export interface StatusChipProps {
  status: AlertWorkflowStatus;
  size?: "sm" | "md";
  className?: string;
}

interface StatusMeta {
  label: string;
  text: string;
  bg: string;
  border: string;
  dot: string;
}

/** Workflow status colors for the triage lifecycle. */
export const WORKFLOW_STATUS_META: Record<AlertWorkflowStatus, StatusMeta> = {
  new: {
    label: "New",
    text: "text-sky-300",
    bg: "bg-sky-400/10",
    border: "border-sky-400/30",
    dot: "bg-sky-400",
  },
  investigating: {
    label: "Investigating",
    text: "text-amber-300",
    bg: "bg-amber-400/10",
    border: "border-amber-400/30",
    dot: "bg-amber-400",
  },
  acknowledged: {
    label: "Acknowledged",
    text: "text-violet-300",
    bg: "bg-violet-400/10",
    border: "border-violet-400/30",
    dot: "bg-violet-400",
  },
  resolved: {
    label: "Resolved",
    text: "text-emerald-300",
    bg: "bg-emerald-400/10",
    border: "border-emerald-400/30",
    dot: "bg-emerald-400",
  },
};

/**
 * Compact workflow-status pill (New / Investigating / Acknowledged / Resolved)
 * used across the threat table, alert cards, and the investigation drawer.
 */
export default function StatusChip({ status, size = "md", className }: StatusChipProps) {
  const meta = WORKFLOW_STATUS_META[status];

  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-md border font-data tracking-wide uppercase",
        meta.text,
        meta.bg,
        meta.border,
        size === "sm" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-1 text-[11px]",
        className,
      )}
    >
      <span
        className={clsx(
          "rounded-full",
          meta.dot,
          size === "sm" ? "h-1 w-1" : "h-1.5 w-1.5",
        )}
        aria-hidden="true"
      />
      {meta.label}
    </span>
  );
}
