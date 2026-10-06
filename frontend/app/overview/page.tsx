"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import type { Variants } from "framer-motion";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ChevronDown,
  ChevronUp,
  ChevronsUpDown,
  Download,
  HeartPulse,
  LayoutDashboard,
  Minus,
  Radar,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import clsx from "clsx";
import PageShell from "@/components/layout/PageShell";
import GlassCard from "@/components/ui/GlassCard";
import AnimatedCounter from "@/components/ui/AnimatedCounter";
import SectionHeading from "@/components/ui/SectionHeading";
import StatusIndicator from "@/components/ui/StatusIndicator";
import CategoryChip from "@/components/ui/CategoryChip";
import ThreatFeed from "@/components/features/ThreatFeed";
import InvestigationDrawer from "@/components/features/InvestigationDrawer";
import AttackDistributionChart from "@/components/charts/AttackDistributionChart";
import TimelineChart from "@/components/charts/TimelineChart";
import ChartTooltip from "@/components/charts/ChartTooltip";
import {
  ATTACK_COLORS,
  ATTACK_DISTRIBUTION_24H,
  BASE_TIME,
  HOURLY_ATTACK_BUCKETS,
  OVERVIEW_KPIS,
  THREAT_FEED_EVENTS,
  THREAT_SOURCES,
  getTimelineSeries,
} from "@/lib/mock-data";
import {
  clamp,
  formatClockUTC,
  formatCompact,
  formatDateTimeUTC,
  formatTimeUTC,
  riskTextClass,
} from "@/lib/format";
import type { SourceDisposition, ThreatEvent, ThreatSourceRow } from "@/types";

/* -------------------------------------------------------------------------- */
/*  Constants                                                                  */
/* -------------------------------------------------------------------------- */

const TIMELINE_SERIES = [
  { key: "normal", name: "Normal", color: ATTACK_COLORS.normal },
  { key: "dos", name: "DoS", color: ATTACK_COLORS.dos },
  { key: "probe", name: "Probe", color: ATTACK_COLORS.probe },
  { key: "r2l", name: "R2L", color: ATTACK_COLORS.r2l },
  { key: "u2r", name: "U2R", color: ATTACK_COLORS.u2r },
];

const STACKED_KEYS = ["dos", "probe", "r2l", "u2r"] as const;

const DISPOSITION_META: Record<
  SourceDisposition,
  { label: string; text: string; bg: string; border: string; dot: string }
> = {
  blocked: { label: "Blocked", text: "text-rose-300", bg: "bg-rose-400/10", border: "border-rose-400/30", dot: "bg-rose-400" },
  quarantined: { label: "Quarantined", text: "text-orange-300", bg: "bg-orange-400/10", border: "border-orange-400/30", dot: "bg-orange-400" },
  watchlist: { label: "Watchlist", text: "text-yellow-300", bg: "bg-yellow-400/10", border: "border-yellow-400/30", dot: "bg-yellow-400" },
  monitoring: { label: "Monitoring", text: "text-sky-300", bg: "bg-sky-400/10", border: "border-sky-400/30", dot: "bg-sky-400" },
  cleared: { label: "Cleared", text: "text-emerald-300", bg: "bg-emerald-400/10", border: "border-emerald-400/30", dot: "bg-emerald-400" },
};

type SourceSortKey = "id" | "events" | "threats" | "riskScore" | "topAttack" | "lastSeen" | "status";

const SOURCE_COLUMNS: Array<{ key: SourceSortKey; label: string; align?: "right" }> = [
  { key: "id", label: "Source ID" },
  { key: "events", label: "Events", align: "right" },
  { key: "threats", label: "Threats", align: "right" },
  { key: "riskScore", label: "Risk Score" },
  { key: "topAttack", label: "Top Attack" },
  { key: "lastSeen", label: "Last Seen" },
  { key: "status", label: "Status" },
];

const gridVariants: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.055, delayChildren: 0.08 } },
};

const cardVariants: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.45, ease: [0.22, 1, 0.36, 1] },
  },
};

/* -------------------------------------------------------------------------- */
/*  Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function OverviewPage() {
  const [selected, setSelected] = useState<ThreatEvent | null>(null);
  const [eps, setEps] = useState(247);
  const [sortKey, setSortKey] = useState<SourceSortKey>("riskScore");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const timelineData = useMemo(() => getTimelineSeries("6h"), []);
  const distributionTotal = useMemo(
    () => ATTACK_DISTRIBUTION_24H.reduce((acc, slice) => acc + slice.value, 0),
    [],
  );

  /* Live-jittered events/sec counter. */
  useEffect(() => {
    const timer = window.setInterval(() => {
      setEps((prev) => clamp(prev + Math.round((Math.random() - 0.48) * 16), 190, 320));
    }, 2200);
    return () => window.clearInterval(timer);
  }, []);

  const sortedSources = useMemo(() => {
    const rows = [...THREAT_SOURCES].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "number" && typeof bv === "number") return av - bv;
      return String(av).localeCompare(String(bv));
    });
    return sortDir === "desc" ? rows.reverse() : rows;
  }, [sortKey, sortDir]);

  const toggleSort = (key: SourceSortKey) => {
    if (key === sortKey) {
      setSortDir((dir) => (dir === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  return (
    <PageShell
      title="SOC Overview"
      description="Real-time command view of streaming telemetry, active detections, and platform KPIs."
      icon={LayoutDashboard}
      moduleIndex="01 / 10"
    >
      <div className="space-y-6">
        {/* ---------------------------------------------------------------- */}
        {/* KPI row                                                           */}
        {/* ---------------------------------------------------------------- */}
        <section aria-label="Mission metrics">
          <SectionHeading
            title="Mission Metrics"
            hint="rolling 24h window · live stream"
          />
          <motion.div
            variants={gridVariants}
            initial="hidden"
            animate="show"
            className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
          >
            {OVERVIEW_KPIS.map((kpi) => {
              const Icon = kpi.icon;
              const value = kpi.live ? eps : kpi.value;
              const isUp = kpi.trend === "up";
              const isDown = kpi.trend === "down";
              const TrendIcon = isUp ? TrendingUp : isDown ? TrendingDown : Minus;
              const isGood =
                kpi.positive === undefined
                  ? null
                  : isDown
                    ? kpi.positive
                    : isUp && kpi.positive;
              const toneClass =
                isGood === null
                  ? "text-cyber-muted"
                  : isGood
                    ? "text-severity-low"
                    : "text-severity-critical";

              return (
                <motion.div key={kpi.id} variants={cardVariants} className="h-full">
                  <GlassCard hover className="h-full p-5">
                    <div className="flex items-start justify-between gap-3">
                      <p className="font-data text-[10px] tracking-[0.16em] text-cyber-muted uppercase">
                        {kpi.title}
                      </p>
                      <span className={clsx("rounded-lg border p-2", kpi.chip)}>
                        <Icon className="h-4 w-4" strokeWidth={1.9} aria-hidden="true" />
                      </span>
                    </div>
                    <div className="mt-3 flex items-baseline gap-2">
                      <AnimatedCounter
                        value={value}
                        decimals={kpi.decimals}
                        suffix={kpi.unit}
                        className="text-[26px] font-semibold tracking-tight text-slate-50"
                      />
                      {kpi.live && (
                        <span
                          className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyber-accent shadow-[0_0_8px_rgba(34,211,238,0.9)]"
                          aria-hidden="true"
                        />
                      )}
                    </div>
                    <p className="mt-2 flex items-center gap-1.5 font-data text-[11px]">
                      <TrendIcon className={clsx("h-3 w-3", toneClass)} aria-hidden="true" />
                      <span className={toneClass}>
                        {kpi.change > 0 ? "+" : ""}
                        {kpi.change}%
                      </span>
                      <span className="text-cyber-muted">vs prev 24h</span>
                    </p>
                  </GlassCard>
                </motion.div>
              );
            })}

            {/* System health tile */}
            <motion.div variants={cardVariants} className="h-full">
              <GlassCard hover className="h-full p-5">
                <div className="flex items-start justify-between gap-3">
                  <p className="font-data text-[10px] tracking-[0.16em] text-cyber-muted uppercase">
                    System Health
                  </p>
                  <span className="rounded-lg border border-severity-low/25 bg-severity-low/10 p-2 text-severity-low">
                    <HeartPulse className="h-4 w-4" strokeWidth={1.9} aria-hidden="true" />
                  </span>
                </div>
                <div className="mt-3.5 flex items-center gap-2.5">
                  <StatusIndicator status="online" size="lg" label="" />
                  <span className="text-lg font-semibold tracking-tight text-emerald-300">
                    Healthy
                  </span>
                </div>
                <p className="mt-2 font-data text-[11px] text-cyber-muted">
                  7 / 7 services reporting
                  <span className="px-1.5 text-cyber-muted/60">·</span>
                  <span className="text-severity-low">99.94% uptime</span>
                </p>
              </GlassCard>
            </motion.div>
          </motion.div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Charts + live feed                                                */}
        {/* ---------------------------------------------------------------- */}
        <section
          aria-label="Attack analytics and live feed"
          className="grid grid-cols-1 gap-4 xl:grid-cols-3"
        >
          <div className="space-y-4 xl:col-span-2">
            {/* Attack timeline */}
            <GlassCard className="p-5">
              <SectionHeading
                title="Attack Timeline"
                hint="last 6 hours · 10-min buckets"
                action={
                  <span className="flex items-center gap-2 font-data text-[10px] text-cyber-muted">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
                    streaming
                  </span>
                }
              />
              <TimelineChart
                data={timelineData}
                series={TIMELINE_SERIES}
                height={264}
                xTickFormatter={formatTimeUTC}
                yTickFormatter={formatCompact}
                labelFormatter={(iso) => `${formatDateTimeUTC(iso)} UTC`}
                totalLabel="Total flows"
              />
            </GlassCard>

            {/* Distribution + hourly load */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <GlassCard className="p-5">
                <SectionHeading title="Attack Distribution" hint="last 24h" />
                <AttackDistributionChart
                  data={ATTACK_DISTRIBUTION_24H}
                  height={212}
                  centerValue={formatCompact(distributionTotal)}
                  centerTitle="flows · 24h"
                />
              </GlassCard>

              <GlassCard className="p-5">
                <SectionHeading title="Hourly Attack Load" hint="attacks per hour" />
                <div style={{ height: 212 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={HOURLY_ATTACK_BUCKETS}
                      margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
                    >
                      <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false} />
                      <XAxis
                        dataKey="hour"
                        tick={{
                          fill: "#94a3b8",
                          fontSize: 9.5,
                          fontFamily: "var(--font-jetbrains-mono)",
                        }}
                        axisLine={{ stroke: "#1e293b" }}
                        tickLine={false}
                        minTickGap={28}
                        dy={6}
                      />
                      <YAxis
                        tick={{
                          fill: "#94a3b8",
                          fontSize: 10,
                          fontFamily: "var(--font-jetbrains-mono)",
                        }}
                        axisLine={false}
                        tickLine={false}
                        width={34}
                      />
                      <RechartsTooltip
                        cursor={{ fill: "rgba(34, 211, 238, 0.05)" }}
                        content={
                          <ChartTooltip
                            totalLabel="Attacks"
                            labelFormatter={(label) => `${label} UTC`}
                          />
                        }
                      />
                      {STACKED_KEYS.map((key, index) => (
                        <Bar
                          key={key}
                          dataKey={key}
                          name={key.toUpperCase()}
                          stackId="attacks"
                          fill={ATTACK_COLORS[key]}
                          radius={index === STACKED_KEYS.length - 1 ? [3, 3, 0, 0] : 0}
                          animationDuration={750}
                        />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <ul className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
                  {STACKED_KEYS.map((key) => (
                    <li
                      key={key}
                      className="flex items-center gap-1.5 text-[11px] text-cyber-muted"
                    >
                      <span
                        className="h-2 w-2 rounded-[3px]"
                        style={{ backgroundColor: ATTACK_COLORS[key] }}
                        aria-hidden="true"
                      />
                      {key.toUpperCase()}
                    </li>
                  ))}
                </ul>
              </GlassCard>
            </div>
          </div>

          {/* Live threat feed */}
          <GlassCard className="flex h-[560px] flex-col p-0 xl:h-auto xl:min-h-0">
            <ThreatFeed
              events={THREAT_FEED_EVENTS}
              maxItems={16}
              onSelect={setSelected}
              className="flex-1"
            />
          </GlassCard>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Top threat sources                                                */}
        {/* ---------------------------------------------------------------- */}
        <section aria-label="Top threat sources">
          <GlassCard className="overflow-hidden p-0">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-cyber-border/60 px-5 py-4">
              <div className="flex items-center gap-2.5">
                <span className="rounded-lg border border-cyber-accent/25 bg-cyber-accent/10 p-2 text-cyber-accent">
                  <Radar className="h-4 w-4" strokeWidth={1.9} aria-hidden="true" />
                </span>
                <div>
                  <h2 className="font-data text-[11px] tracking-[0.22em] text-cyber-muted uppercase">
                    Top Threat Sources
                  </h2>
                  <p className="mt-0.5 font-data text-[10px] text-cyber-muted/70">
                    anonymized source hosts · ranked by composite risk
                  </p>
                </div>
              </div>
              <button
                type="button"
                title="Mock action - CSV export wires to the API later"
                className="flex items-center gap-2 rounded-lg border border-cyber-border/70 bg-cyber-surface/60 px-3 py-1.5 font-data text-[11px] text-cyber-muted hover:border-cyber-accent/30 hover:text-slate-100"
              >
                <Download className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden="true" />
                Export
              </button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[880px] border-collapse text-left">
                <thead>
                  <tr className="border-b border-cyber-border/60">
                    {SOURCE_COLUMNS.map((column) => {
                      const active = sortKey === column.key;
                      const SortIcon = !active
                        ? ChevronsUpDown
                        : sortDir === "desc"
                          ? ChevronDown
                          : ChevronUp;
                      return (
                        <th
                          key={column.key}
                          className={clsx(
                            "px-5 py-3 first:pl-5",
                            column.align === "right" && "text-right",
                          )}
                        >
                          <button
                            type="button"
                            onClick={() => toggleSort(column.key)}
                            className={clsx(
                              "inline-flex items-center gap-1.5 font-data text-[10px] tracking-[0.16em] uppercase",
                              active
                                ? "text-cyber-accent"
                                : "text-cyber-muted hover:text-slate-200",
                              column.align === "right" && "flex-row-reverse",
                            )}
                          >
                            {column.label}
                            <SortIcon className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
                          </button>
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody className="divide-y divide-cyber-border/40">
                  {sortedSources.map((source) => (
                    <SourceRow key={source.id} source={source} />
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between border-t border-cyber-border/60 px-5 py-3">
              <p className="font-data text-[10px] text-cyber-muted">
                {sortedSources.length} sources · updated {formatClockUTC(new Date(BASE_TIME).toISOString())} UTC
              </p>
              <p className="font-data text-[10px] text-cyber-muted/70">
                Click column headers to sort
              </p>
            </div>
          </GlassCard>
        </section>
      </div>

      <InvestigationDrawer event={selected} onClose={() => setSelected(null)} />
    </PageShell>
  );
}

/* -------------------------------------------------------------------------- */
/*  Row                                                                        */
/* -------------------------------------------------------------------------- */

function SourceRow({ source }: { source: ThreatSourceRow }) {
  const meta = DISPOSITION_META[source.status];

  return (
    <tr className="transition-colors hover:bg-cyber-overlay/35">
      <td className="px-5 py-3">
        <span className="font-data text-[12px] font-medium text-slate-100">{source.id}</span>
        <p className="mt-0.5 font-data text-[10px] text-cyber-muted">
          first seen {formatDateTimeUTC(source.firstSeen)}
        </p>
      </td>
      <td className="px-5 py-3 text-right font-data text-[12px] tabular text-slate-200">
        {source.events.toLocaleString("en-US")}
      </td>
      <td className="px-5 py-3 text-right font-data text-[12px] tabular text-slate-200">
        {source.threats.toLocaleString("en-US")}
      </td>
      <td className="px-5 py-3">
        <div className="flex items-center gap-2.5">
          <span className={clsx("font-data text-[13px] font-semibold tabular", riskTextClass(source.riskScore))}>
            {source.riskScore}
          </span>
          <span className="h-1 w-14 overflow-hidden rounded-full bg-cyber-border/60">
            <span
              className={clsx(
                "block h-full rounded-full",
                source.riskScore >= 85
                  ? "bg-severity-critical"
                  : source.riskScore >= 70
                    ? "bg-severity-high"
                    : source.riskScore >= 50
                      ? "bg-severity-medium"
                      : "bg-severity-low",
              )}
              style={{ width: `${source.riskScore}%` }}
            />
          </span>
        </div>
      </td>
      <td className="px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="font-data text-[11.5px] text-slate-200">{source.topAttack}</span>
          <CategoryChip category={source.category} size="sm" showDot={false} />
        </div>
      </td>
      <td className="px-5 py-3 font-data text-[11px] tabular text-cyber-muted">
        {formatClockUTC(source.lastSeen)} UTC
      </td>
      <td className="px-5 py-3">
        <span
          className={clsx(
            "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-data text-[10px] tracking-wide uppercase",
            meta.text,
            meta.bg,
            meta.border,
          )}
        >
          <span className={clsx("h-1.5 w-1.5 rounded-full", meta.dot)} aria-hidden="true" />
          {meta.label}
        </span>
      </td>
    </tr>
  );
}
