"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import clsx from "clsx";
import type { CategorySlice } from "@/types";
import { formatCompact, percentOf } from "@/lib/format";
import ChartTooltip from "@/components/charts/ChartTooltip";

export interface AttackDistributionChartProps {
  data: CategorySlice[];
  height?: number;
  /** Renders the donut hole with a centered label. */
  centerTitle?: string;
  centerValue?: string;
  /** Shows the dot-legend under the chart (default true). */
  showLegend?: boolean;
  className?: string;
}

/**
 * Reusable dark-theme donut chart for the attack distribution
 * (Normal vs DoS vs Probe vs R2L vs U2R) with a glass tooltip and legend.
 */
export default function AttackDistributionChart({
  data,
  height = 240,
  centerTitle,
  centerValue,
  showLegend = true,
  className,
}: AttackDistributionChartProps) {
  const total = data.reduce((acc, slice) => acc + slice.value, 0);

  return (
    <div className={clsx("flex flex-col", className)}>
      <div className="relative w-full" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
            <Tooltip
              cursor={false}
              content={
                <ChartTooltip
                  valueFormatter={(value) =>
                    `${formatCompact(value)} · ${percentOf(value, total).toFixed(1)}%`
                  }
                />
              }
            />
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              innerRadius="62%"
              outerRadius="90%"
              paddingAngle={2.5}
              cornerRadius={5}
              stroke="none"
              animationDuration={900}
              animationBegin={150}
            >
              {data.map((slice) => (
                <Cell key={slice.category} fill={slice.color} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>

        {(centerTitle || centerValue) && (
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            {centerValue && (
              <p className="font-data text-xl font-semibold tabular text-slate-50">
                {centerValue}
              </p>
            )}
            {centerTitle && (
              <p className="mt-0.5 font-data text-[9px] tracking-[0.2em] text-cyber-muted uppercase">
                {centerTitle}
              </p>
            )}
          </div>
        )}
      </div>

      {showLegend && (
        <ul className="mt-4 grid grid-cols-1 gap-x-4 gap-y-1.5 sm:grid-cols-2">
          {data.map((slice) => (
            <li key={slice.category} className="flex items-center justify-between gap-2 text-[11px]">
              <span className="flex items-center gap-1.5 text-cyber-muted">
                <span
                  className="h-2 w-2 shrink-0 rounded-[3px]"
                  style={{ backgroundColor: slice.color }}
                  aria-hidden="true"
                />
                {slice.name}
              </span>
              <span className="font-data text-slate-200">
                {percentOf(slice.value, total).toFixed(1)}%
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
