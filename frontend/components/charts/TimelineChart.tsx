"use client";

import { useId } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import clsx from "clsx";
import ChartTooltip from "@/components/charts/ChartTooltip";

export interface TimelineSeries {
  key: string;
  name: string;
  color: string;
}

export interface TimelineChartProps {
  data: Array<Record<string, string | number>>;
  series: TimelineSeries[];
  /** Key of the x-axis field. */
  xKey?: string;
  height?: number;
  /** Formats x-axis tick labels (receives the raw value). */
  xTickFormatter?: (value: string) => string;
  yTickFormatter?: (value: number) => string;
  /** Formats tooltip header labels. */
  labelFormatter?: (value: string) => string;
  /** Appends a total row to the tooltip. */
  totalLabel?: string;
  showLegend?: boolean;
  className?: string;
}

/**
 * Reusable dark-theme stacked area chart used by the attack timeline
 * (overview) and the attack analytics time-series panels.
 */
export default function TimelineChart({
  data,
  series,
  xKey = "time",
  height = 280,
  xTickFormatter,
  yTickFormatter,
  labelFormatter,
  totalLabel,
  showLegend = true,
  className,
}: TimelineChartProps) {
  /* Unique gradient ids so multiple instances on one page never collide. */
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");

  return (
    <div className={clsx("flex flex-col", className)}>
      <div className="w-full" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <defs>
              {series.map((s) => (
                <linearGradient
                  key={s.key}
                  id={`${uid}-${s.key}`}
                  x1="0"
                  y1="0"
                  x2="0"
                  y2="1"
                >
                  <stop offset="0%" stopColor={s.color} stopOpacity={0.42} />
                  <stop offset="100%" stopColor={s.color} stopOpacity={0.03} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid
              stroke="#1e293b"
              strokeDasharray="3 3"
              vertical={false}
            />
            <XAxis
              dataKey={xKey}
              tickFormatter={(value: string) =>
                xTickFormatter ? xTickFormatter(value) : value
              }
              tick={{ fill: "#94a3b8", fontSize: 10, fontFamily: "var(--font-jetbrains-mono)" }}
              axisLine={{ stroke: "#1e293b" }}
              tickLine={false}
              minTickGap={42}
              dy={6}
            />
            <YAxis
              tickFormatter={(value: number) =>
                yTickFormatter ? yTickFormatter(value) : String(value)
              }
              tick={{ fill: "#94a3b8", fontSize: 10, fontFamily: "var(--font-jetbrains-mono)" }}
              axisLine={false}
              tickLine={false}
              width={46}
            />
            <Tooltip
              cursor={{ stroke: "rgba(34, 211, 238, 0.35)", strokeDasharray: "3 3" }}
              content={
                <ChartTooltip
                  totalLabel={totalLabel}
                  labelFormatter={(label) =>
                    labelFormatter ? labelFormatter(String(label)) : String(label)
                  }
                />
              }
            />
            {series.map((s) => (
              <Area
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.name}
                stackId="timeline"
                stroke={s.color}
                strokeWidth={1.6}
                fill={`url(#${uid}-${s.key})`}
                activeDot={{ r: 2.5, strokeWidth: 0 }}
                animationDuration={800}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {showLegend && (
        <ul className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
          {series.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5 text-[11px] text-cyber-muted">
              <span
                className="h-1.5 w-3 rounded-full"
                style={{ backgroundColor: s.color }}
                aria-hidden="true"
              />
              {s.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
