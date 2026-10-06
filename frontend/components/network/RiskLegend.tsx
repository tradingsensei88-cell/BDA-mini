"use client";

import clsx from "clsx";
import type { RiskLevel } from "@/types/network";
import { RISK_COLORS, RISK_LABELS } from "@/lib/network-data";

export interface RiskLegendProps {
  className?: string;
}

/** Most severe first - commander's reading order. */
const LEVELS: RiskLevel[] = ["critical", "high", "suspicious", "normal"];

/**
 * Bottom-left legend: risk color key plus the three interaction hints for the
 * 3D viewport.
 */
export default function RiskLegend({ className }: RiskLegendProps) {
  return (
    <div
      className={clsx(
        "glass-panel-strong pointer-events-auto rounded-xl border border-cyber-border/90 px-3.5 py-3 shadow-panel",
        className,
      )}
    >
      <p className="font-data text-[9px] tracking-[0.2em] text-cyber-muted uppercase">
        Risk level
      </p>
      <ul className="mt-2 space-y-1.5">
        {LEVELS.map((level) => (
          <li key={level} className="flex items-center gap-2">
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{
                backgroundColor: RISK_COLORS[level],
                boxShadow: `0 0 6px ${RISK_COLORS[level]}`,
              }}
              aria-hidden="true"
            />
            <span className="font-data text-[10px] text-slate-300">
              {RISK_LABELS[level]}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2.5 border-t border-cyber-border/60 pt-2 font-data text-[9px] leading-relaxed text-cyber-muted/80">
        drag orbit · scroll zoom
        <br />
        click asset or flow to inspect
      </p>
    </div>
  );
}
