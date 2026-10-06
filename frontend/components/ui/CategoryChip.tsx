"use client";

import clsx from "clsx";
import { ATTACK_COLORS, CATEGORY_FULL_NAMES, CATEGORY_LABELS } from "@/lib/mock-data";
import type { AttackCategory } from "@/types";

export interface CategoryChipProps {
  category: AttackCategory;
  size?: "sm" | "md";
  /** Renders the full category name (e.g. "Denial of Service"). */
  verbose?: boolean;
  showDot?: boolean;
  className?: string;
}

/**
 * Attack-category pill (Normal / DoS / Probe / R2L / U2R) tinted with the
 * shared chart palette so tables and charts read consistently.
 */
export default function CategoryChip({
  category,
  size = "md",
  verbose = false,
  showDot = true,
  className,
}: CategoryChipProps) {
  const color = ATTACK_COLORS[category];
  const label = verbose ? CATEGORY_FULL_NAMES[category] : CATEGORY_LABELS[category];

  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-md border font-data tracking-wide uppercase",
        size === "sm" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-1 text-[11px]",
        className,
      )}
      style={{
        color,
        backgroundColor: `${color}14`,
        borderColor: `${color}4d`,
      }}
    >
      {showDot && (
        <span
          className={clsx("rounded-full", size === "sm" ? "h-1 w-1" : "h-1.5 w-1.5")}
          style={{ backgroundColor: color }}
          aria-hidden="true"
        />
      )}
      {label}
    </span>
  );
}
