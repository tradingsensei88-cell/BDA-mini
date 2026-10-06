"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
} from "recharts";
import { BarChart3, Crosshair, Flame, Radar as RadarIcon } from "lucide-react";
import clsx from "clsx";
import PageShell from "@/components/layout/PageShell";
import GlassCard from "@/components/ui/GlassCard";
import SectionHeading from "@/components/ui/SectionHeading";
import TimelineChart from "@/components/charts/TimelineChart";
import ChartTooltip from "@/components/charts/ChartTooltip";
import {
  ATTACK_COLORS,
  CATEGORY_LABELS,
  CATEGORY_RADAR,
  HEATMAP_MATRIX,
  PROTOCOL_BREAKDOWN,
  TOP_TARGETED_SERVICES,
  getTimelineSeries,
} from "@/lib/mock-data";
import {
  formatCompact,
  formatDateTimeUTC,
  formatDayShortUTC,
  formatTimeUTC,
  percentOf,
  riskTextClass,
} from "@/lib/format";
import type { AttackKind, TimelineRange } from "@/types";

/* -------------------------------------------------------------------------- */
/*  Constants                                                                  */
/* -------------------------------------------------------------------------- */

const RANGES: Array<{ id: TimelineRange; label: string }> = [
  { id: "1h", label: "1H" },
  { id: "6h", label: "6H" },
  { id: "24h", label: "24H" },
  { id: "7d", label: "7D" },
];

const TIMELINE_SERIES = [
  { key: "normal", name: "Normal", color: ATTACK_COLORS.normal },
  { key: "dos", name: "DoS", color: ATTACK_COLORS.dos },
  { key: "probe", name: "Probe", color: ATTACK_COLORS.probe },
  { key: "r2l", name: "R2L", color: ATTACK_COLORS.r2l },
  { key: "u2r", name: "U2R", color: ATTACK_COLORS.u2r },
];

const RADAR_KEYS: AttackKind[] = ["dos", "probe", "r2l", "u2r"];

/* -------------------------------------------------------------------------- */
/*  Heatmap color scale                                                        */
/* -------------------------------------------------------------------------- */

const HEAT_MAX = 48;

function lerpChannel(a: number, b: number, t: number): number {
  return Math.round(a + (b - a) * t);
}

/** Deep-teal → amber → red scale for attack frequency. */
function heatColor(value: number): string {
  if (value <= 0) return "rgba(23, 35, 61, 0.45)";
  const t = Math.min(1, value / HEAT_MAX);
  const [r, g, b] =
    t < 0.5
      ? [
          lerpChannel(14, 245, t * 2),
          lerpChannel(116, 158, t * 2),
          lerpChannel(144, 11, t * 2),
        ]
      : [
          lerpChannel(245, 239, (t - 0.5) * 2),
          lerpChannel(158, 68, (t - 0.5) * 2),
          lerpChannel(11, 68, (t - 0.5) * 2),
        ];
  const alpha = 0.14 + t * 0.72;
  return `rgba(${r}, ${g}, ${b}, ${alpha.toFixed(3)})`;
}

const pad2 = (value: number) => String(value).padStart(2, "0");

/* -------------------------------------------------------------------------- */
/*  Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function AnalyticsPage() {
  const [range, setRange] = useState<TimelineRange>("24h");

  const timelineData = useMemo(() => getTimelineSeries(range), [range]);

  return (
    <PageShell
      title="Attack Analytics"
      description="Temporal, spatial, and protocol-level analysis of detected attack traffic."
      icon={BarChart3}
      moduleIndex="05 / 10"
    >
      <div className="space-y-5">
        {/* ---------------------------------------------------------------- */}
        {/* Stacked attack timeline                                           */}
        {/* ---------------------------------------------------------------- */}
        <GlassCard className="p-5">
          <SectionHeading
            title="Attack Distribution Over Time"
            hint={`stacked view · last ${range}`}
            action={
              <div className="flex items-center gap-1 rounded-full border border-cyber-border/70 bg-cyber-surface/60 p-1">
                {RANGES.map((item) => {
                  const active = range === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setRange(item.id)}
                      className={clsx(
                        "relative rounded-full px-3 py-1 font-data text-[10.5px] tracking-wider",
                        active
                          ? "text-cyber-accent-bright"
                          : "text-cyber-muted hover:text-slate-200",
                      )}
                    >
                      {active && (
                        <motion.span
                          layoutId="analytics-range-pill"
                          transition={{ type: "spring", stiffness: 420, damping: 34 }}
                          className="absolute inset-0 rounded-full bg-cyber-accent/15"
                          aria-hidden="true"
                        />
                      )}
                      <span className="relative z-10">{item.label}</span>
                    </button>
                  );
                })}
              </div>
            }
          />
          <TimelineChart
            data={timelineData}
            series={TIMELINE_SERIES}
            height={330}
            xTickFormatter={range === "7d" ? formatDayShortUTC : formatTimeUTC}
            yTickFormatter={formatCompact}
            labelFormatter={(iso) => `${formatDateTimeUTC(iso)} UTC`}
            totalLabel="Total flows"
          />
        </GlassCard>

        {/* ---------------------------------------------------------------- */}
        {/* Heatmap + radar                                                   */}
        {/* ---------------------------------------------------------------- */}
        <section className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <GlassCard className="p-5 xl:col-span-2">
            <SectionHeading
              title="Threat Heatmap"
              hint="attack frequency · source host × hour (UTC)"
              action={
                <span className="flex items-center gap-2 font-data text-[10px] text-cyber-muted">
                  <Flame className="h-3.5 w-3.5 text-severity-high" aria-hidden="true" />
                  peak {HEAT_MAX} attacks/h
                </span>
              }
            />
            <div className="overflow-x-auto pb-1">
              <div className="min-w-[620px]">
                {/* Hour header */}
                <div className="mb-1 grid grid-cols-[76px_repeat(24,minmax(0,1fr))] gap-1">
                  <span aria-hidden="true" />
                  {Array.from({ length: 24 }, (_, hour) => (
                    <span
                      key={hour}
                      className="text-center font-data text-[8.5px] text-cyber-muted"
                    >
                      {hour % 3 === 0 ? pad2(hour) : ""}
                    </span>
                  ))}
                </div>
                {/* Rows */}
                {HEATMAP_MATRIX.map((row) => (
                  <div
                    key={row.host}
                    className="mb-1 grid grid-cols-[76px_repeat(24,minmax(0,1fr))] items-center gap-1"
                  >
                    <span className="truncate font-data text-[10px] text-cyber-muted">
                      {row.host}
                    </span>
                    {row.cells.map((value, hour) => (
                      <div
                        key={hour}
                        title={`${row.host} · ${pad2(hour)}:00 — ${value} attacks`}
                        className="h-5 rounded-[3px] transition-transform duration-150 hover:scale-125 hover:ring-1 hover:ring-cyber-accent/80"
                        style={{ backgroundColor: heatColor(value) }}
                      />
                    ))}
                  </div>
                ))}
                {/* Scale legend */}
                <div className="mt-3 flex items-center gap-2 pl-[80px]">
                  <span className="font-data text-[9.5px] text-cyber-muted">0</span>
                  <span
                    className="h-1.5 w-40 rounded-full"
                    style={{
                      background:
                        "linear-gradient(90deg, rgba(23,35,61,0.6), rgba(14,116,144,0.8), rgba(245,158,11,0.9), rgba(239,68,68,1))",
                    }}
                    aria-hidden="true"
                  />
                  <span className="font-data text-[9.5px] text-cyber-muted">{HEAT_MAX}+</span>
                </div>
              </div>
            </div>
          </GlassCard>

          <GlassCard className="p-5">
            <SectionHeading
              title="Category Breakdown"
              hint="normalized 0-100"
              action={<RadarIcon className="h-3.5 w-3.5 text-cyber-accent" aria-hidden="true" />}
            />
            <div style={{ height: 300 }}>
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={CATEGORY_RADAR} outerRadius="72%">
                  <PolarGrid stroke="#1e293b" />
                  <PolarAngleAxis
                    dataKey="metric"
                    tick={{
                      fill: "#94a3b8",
                      fontSize: 10,
                      fontFamily: "var(--font-jetbrains-mono)",
                    }}
                  />
                  <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                  <RechartsTooltip content={<ChartTooltip />} />
                  {RADAR_KEYS.map((key) => (
                    <Radar
                      key={key}
                      name={CATEGORY_LABELS[key]}
                      dataKey={key}
                      stroke={ATTACK_COLORS[key]}
                      fill={ATTACK_COLORS[key]}
                      fillOpacity={0.12}
                      strokeWidth={1.6}
                      dot={false}
                      animationDuration={750}
                    />
                  ))}
                </RadarChart>
              </ResponsiveContainer>
            </div>
            <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5">
              {RADAR_KEYS.map((key) => (
                <li key={key} className="flex items-center gap-1.5 text-[11px] text-cyber-muted">
                  <span
                    className="h-2 w-2 rounded-[3px]"
                    style={{ backgroundColor: ATTACK_COLORS[key] }}
                    aria-hidden="true"
                  />
                  {CATEGORY_LABELS[key]}
                </li>
              ))}
            </ul>
          </GlassCard>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Protocol distribution + targeted services                         */}
        {/* ---------------------------------------------------------------- */}
        <section className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <GlassCard className="p-5 xl:col-span-2">
            <SectionHeading
              title="Protocol Distribution"
              hint="normal vs attack volume · last 24h"
            />
            <div className="space-y-5">
              {PROTOCOL_BREAKDOWN.map((row, index) => {
                const total = row.normal + row.attacks;
                const attackShare = percentOf(row.attacks, total);
                return (
                  <div key={row.protocol}>
                    <div className="mb-1.5 flex items-baseline justify-between">
                      <span className="font-data text-[12px] font-medium text-slate-100">
                        {row.protocol}
                      </span>
                      <span className="font-data text-[10.5px] tabular text-cyber-muted">
                        {formatCompact(total)} flows
                        <span className="px-1.5 text-cyber-muted/60">·</span>
                        <span className="text-severity-high">{attackShare.toFixed(1)}% attacks</span>
                      </span>
                    </div>
                    <div className="flex h-3 w-full overflow-hidden rounded-full bg-cyber-border/40">
                      <motion.span
                        initial={{ width: 0 }}
                        animate={{ width: `${percentOf(row.normal, total)}%` }}
                        transition={{ duration: 0.8, delay: index * 0.08, ease: [0.22, 1, 0.36, 1] }}
                        className="h-full bg-gradient-to-r from-cyber-accent/70 to-cyber-accent"
                      />
                      <motion.span
                        initial={{ width: 0 }}
                        animate={{ width: `${attackShare}%` }}
                        transition={{ duration: 0.8, delay: 0.15 + index * 0.08, ease: [0.22, 1, 0.36, 1] }}
                        className="h-full bg-gradient-to-r from-severity-high to-severity-critical"
                      />
                    </div>
                    <div className="mt-1.5 flex items-center justify-between font-data text-[10px] tabular text-cyber-muted">
                      <span>
                        Normal{" "}
                        <span className="text-slate-300">{row.normal.toLocaleString("en-US")}</span>
                      </span>
                      <span>
                        Attacks{" "}
                        <span className="text-slate-300">
                          {row.attacks.toLocaleString("en-US")}
                        </span>
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="mt-5 flex items-center gap-4 border-t border-cyber-border/50 pt-3">
              <span className="flex items-center gap-1.5 text-[10.5px] text-cyber-muted">
                <span className="h-2 w-4 rounded-full bg-cyber-accent" aria-hidden="true" />
                Normal traffic
              </span>
              <span className="flex items-center gap-1.5 text-[10.5px] text-cyber-muted">
                <span
                  className="h-2 w-4 rounded-full bg-gradient-to-r from-severity-high to-severity-critical"
                  aria-hidden="true"
                />
                Attack traffic
              </span>
            </div>
          </GlassCard>

          <GlassCard className="p-5">
            <SectionHeading
              title="Top Targeted Services"
              hint="24h"
              action={<Crosshair className="h-3.5 w-3.5 text-severity-critical" aria-hidden="true" />}
            />
            <ul className="divide-y divide-cyber-border/40">
              {TOP_TARGETED_SERVICES.map((service) => (
                <li
                  key={service.name}
                  className="flex items-center justify-between gap-3 py-2.5 first:pt-1"
                >
                  <div className="min-w-0">
                    <p className="truncate font-data text-[12px] text-slate-100">
                      {service.name}
                    </p>
                    <p className="font-data text-[10px] text-cyber-muted">{service.ip}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-4">
                    <span className="font-data text-[11px] tabular text-cyber-muted">
                      {service.events} events
                    </span>
                    <span
                      className={clsx(
                        "w-9 text-right font-data text-[13px] font-semibold tabular",
                        riskTextClass(service.riskScore),
                      )}
                    >
                      {service.riskScore}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </GlassCard>
        </section>
      </div>
    </PageShell>
  );
}
