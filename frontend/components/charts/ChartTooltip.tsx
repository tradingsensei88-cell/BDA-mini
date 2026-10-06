"use client";

import type { ReactNode } from "react";

export interface ChartTooltipItem {
  name?: string | number;
  value?: number | string;
  color?: string;
  dataKey?: string | number;
  payload?: Record<string, unknown>;
}

export interface ChartTooltipProps {
  active?: boolean;
  label?: string | number;
  payload?: ChartTooltipItem[];
  /** Custom header (defaults to the raw label). */
  labelFormatter?: (label: string | number, payload: ChartTooltipItem[]) => ReactNode;
  /** Custom value row (defaults to `name · value`). */
  valueFormatter?: (value: number, name: string, item: ChartTooltipItem) => ReactNode;
  /** Appends a summed total row (useful for stacked areas). */
  totalLabel?: string;
}

/**
 * Glass-morphism tooltip shared by every Recharts chart on the dashboard.
 * Passed as `content` to <Tooltip />, so Recharts injects active/label/payload.
 */
export default function ChartTooltip({
  active,
  label,
  payload,
  labelFormatter,
  valueFormatter,
  totalLabel,
}: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;

  const rows = payload.filter((item) => {
    const value = typeof item.value === "string" ? Number(item.value) : item.value;
    return value !== null && value !== undefined && !Number.isNaN(value) && value !== 0;
  });
  if (rows.length === 0) return null;

  const total = rows.reduce((acc, item) => acc + (Number(item.value) || 0), 0);

  return (
    <div className="glass-inset min-w-[160px] rounded-lg px-3 py-2.5 shadow-panel">
      {label !== undefined && label !== null && (
        <p className="mb-1.5 border-b border-cyber-border/60 pb-1.5 font-data text-[11px] tracking-wide text-slate-200">
          {labelFormatter ? labelFormatter(label, payload) : label}
        </p>
      )}
      <ul className="space-y-1">
        {rows.map((item, index) => {
          const value = Number(item.value) || 0;
          const name = String(item.name ?? item.dataKey ?? "");
          return (
            <li
              key={`${name}-${index}`}
              className="flex items-center justify-between gap-4 text-[11px]"
            >
              <span className="flex items-center gap-1.5 text-cyber-muted">
                <span
                  className="h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{ backgroundColor: item.color ?? "#22d3ee" }}
                  aria-hidden="true"
                />
                {name}
              </span>
              <span className="font-data text-slate-100">
                {valueFormatter ? valueFormatter(value, name, item) : value.toLocaleString("en-US")}
              </span>
            </li>
          );
        })}
      </ul>
      {totalLabel && rows.length > 1 && (
        <p className="mt-1.5 flex items-center justify-between border-t border-cyber-border/60 pt-1.5 text-[11px]">
          <span className="text-cyber-muted">{totalLabel}</span>
          <span className="font-data font-semibold text-slate-50">
            {total.toLocaleString("en-US")}
          </span>
        </p>
      )}
    </div>
  );
}
