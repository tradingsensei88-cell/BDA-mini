"use client";

import type { ReactNode } from "react";
import clsx from "clsx";

export interface SectionHeadingProps {
  title: string;
  /** Optional muted hint rendered after the title. */
  hint?: string;
  /** Optional right-aligned action (buttons, legend chips, filter). */
  action?: ReactNode;
  className?: string;
}

/**
 * Mono-uppercase section label used to introduce every dashboard panel,
 * with an optional right-aligned action slot.
 */
export default function SectionHeading({
  title,
  hint,
  action,
  className,
}: SectionHeadingProps) {
  return (
    <div className={clsx("mb-3 flex flex-wrap items-center justify-between gap-2", className)}>
      <h2 className="flex items-baseline gap-2.5 font-data text-[11px] tracking-[0.22em] text-cyber-muted uppercase">
        {title}
        {hint && (
          <span className="text-[10px] tracking-[0.08em] text-cyber-muted/70 normal-case">
            {hint}
          </span>
        )}
      </h2>
      {action}
    </div>
  );
}
