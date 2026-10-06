"use client";

import { Fragment, useId, useState } from "react";
import { motion, type Variants } from "framer-motion";
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  Brain,
  Clock3,
  Database,
  GitBranch,
  Layers,
  Rocket,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import clsx from "clsx";
import PageShell from "@/components/layout/PageShell";
import GlassCard from "@/components/ui/GlassCard";
import SectionHeading from "@/components/ui/SectionHeading";
import MetricGauge from "@/components/charts/MetricGauge";
import ChartTooltip, { type ChartTooltipProps } from "@/components/charts/ChartTooltip";
import CategoryChip from "@/components/ui/CategoryChip";
import {
  ATTACK_COLORS,
  CLASS_PERFORMANCE,
  CONFIDENCE_DISTRIBUTION,
  CONFUSION_LABELS,
  CONFUSION_MATRIX,
  FEATURE_IMPORTANCE,
  INFERENCE_STATS,
  MODEL_INFO,
  MODEL_METRICS,
} from "@/lib/mock-data";
import { formatCompact } from "@/lib/format";
import type { AttackCategory } from "@/types";

/* -------------------------------------------------------------------------- */
/*  Confusion matrix helpers (static data - computed once at module scope)     */
/* -------------------------------------------------------------------------- */

const ROW_TOTALS = CONFUSION_MATRIX.map((row) => row.reduce((a, b) => a + b, 0));
const GRAND_TOTAL = ROW_TOTALS.reduce((a, b) => a + b, 0);
const DIAGONAL_TOTAL = CONFUSION_MATRIX.reduce((acc, row, i) => acc + row[i], 0);
const OVERALL_ACCURACY = ((DIAGONAL_TOTAL / GRAND_TOTAL) * 100).toFixed(1);
const MAX_DIAGONAL = Math.max(...CONFUSION_MATRIX.map((row, i) => row[i]));
const MAX_OFF_DIAGONAL = Math.max(
  ...CONFUSION_MATRIX.flatMap((row, r) => row.filter((_, c) => c !== r)),
);

/** Cyan intensity on the diagonal, red intensity off it. */
function cellColor(value: number, diagonal: boolean): string {
  if (value <= 0) return "rgba(23, 35, 61, 0.45)";
  if (diagonal) {
    const t = value / MAX_DIAGONAL;
    return `rgba(34, 211, 238, ${(0.1 + t * 0.55).toFixed(3)})`;
  }
  const t = Math.sqrt(value / MAX_OFF_DIAGONAL);
  return `rgba(255, 59, 92, ${(0.07 + t * 0.6).toFixed(3)})`;
}

/* -------------------------------------------------------------------------- */
/*  Feature-importance tooltip (avoids the gradient-url color dot)             */
/* -------------------------------------------------------------------------- */

function FeatureTooltip({ active, label, payload }: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const importance = Number(payload[0]?.value) || 0;
  return (
    <div className="glass-inset min-w-[170px] rounded-lg px-3 py-2.5 shadow-panel">
      <p className="mb-1.5 border-b border-cyber-border/60 pb-1.5 font-data text-[11px] text-slate-200">
        {String(label)}
      </p>
      <p className="flex items-center justify-between gap-4 text-[11px]">
        <span className="text-cyber-muted">Gini importance</span>
        <span className="font-data text-slate-100">{(importance * 100).toFixed(1)}%</span>
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Motion variants                                                            */
/* -------------------------------------------------------------------------- */

const gaugeContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08, delayChildren: 0.1 } },
};

const gaugeItem: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] } },
};

/* -------------------------------------------------------------------------- */
/*  Per-class table helpers                                                    */
/* -------------------------------------------------------------------------- */

function metricColor(value: number): string {
  if (value >= 96) return "#34d399";
  if (value >= 90) return "#fbbf24";
  return "#fb7185";
}

/* -------------------------------------------------------------------------- */
/*  Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function MlIntelligencePage() {
  const [hoverCell, setHoverCell] = useState<{ r: number; c: number } | null>(null);
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");

  return (
    <PageShell
      title="ML Intelligence"
      description="Model registry, prediction quality, and drift telemetry for the NSL-KDD threat classifier."
      icon={Brain}
      moduleIndex="06 / 10"
    >
      <div className="space-y-5">
        {/* ------------------------------------------------------------------ */}
        {/* Model identity + serving telemetry                                  */}
        {/* ------------------------------------------------------------------ */}
        <div className="grid gap-5 xl:grid-cols-3">
          <GlassCard className="xl:col-span-2">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex items-start gap-3.5">
                <div className="glow-ring flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-cyber-accent/25 bg-gradient-to-br from-cyber-accent/15 via-cyber-surface to-cyber-elevated">
                  <Brain className="h-5 w-5 text-cyber-accent-bright" strokeWidth={1.9} aria-hidden="true" />
                </div>
                <div>
                  <h2 className="text-[15px] font-semibold tracking-tight text-slate-50">
                    {MODEL_INFO.name}
                  </h2>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <span className="rounded border border-cyber-accent/30 bg-cyber-accent/10 px-1.5 py-0.5 font-data text-[10px] tracking-[0.12em] text-cyber-accent-bright">
                      v{MODEL_INFO.version}
                    </span>
                    <span className="flex items-center gap-1.5 rounded border border-severity-low/30 bg-severity-low/10 px-1.5 py-0.5 font-data text-[10px] tracking-[0.12em] text-emerald-300 uppercase">
                      <span className="h-1 w-1 animate-pulse rounded-full bg-emerald-400" aria-hidden="true" />
                      production
                    </span>
                    <span className="font-data text-[10.5px] text-cyber-muted">
                      promoted {MODEL_INFO.trainedAt}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <p className="mt-4 max-w-2xl text-[12.5px] leading-relaxed text-cyber-muted">
              Random Forest ensemble scoring every enriched flow in the streaming pipeline —
              {" "}
              {MODEL_INFO.trees} trees at max depth {MODEL_INFO.maxDepth}, trained with{" "}
              {MODEL_INFO.framework} on {MODEL_INFO.features} NSL-KDD connection features.
            </p>

            <div className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3.5 border-t border-cyber-border/50 pt-4 sm:grid-cols-3">
              <InfoCell icon={Database} label="Dataset" value={MODEL_INFO.dataset} hint="KDDTrain+ / KDDTest+" />
              <InfoCell
                icon={Layers}
                label="Training records"
                value={MODEL_INFO.trainRecords.toLocaleString("en-US")}
              />
              <InfoCell
                icon={Layers}
                label="Test records"
                value={MODEL_INFO.testRecords.toLocaleString("en-US")}
              />
              <InfoCell icon={GitBranch} label="Input features" value={String(MODEL_INFO.features)} />
              <InfoCell icon={Rocket} label="Framework" value={MODEL_INFO.framework} />
              <InfoCell
                icon={Activity}
                label="Estimator"
                value={MODEL_INFO.estimator}
                hint={`${MODEL_INFO.trees} trees · depth ${MODEL_INFO.maxDepth}`}
              />
            </div>
          </GlassCard>

          <GlassCard className="flex flex-col">
            <SectionHeading title="Serving Telemetry" hint="streaming inference" />
            <ul className="divide-y divide-cyber-border/50">
              {INFERENCE_STATS.map((row) => (
                <li key={row.label} className="flex items-center justify-between gap-3 py-2.5">
                  <span className="text-[12px] text-cyber-muted">{row.label}</span>
                  <span className="font-data text-[12px] tabular text-slate-100">{row.value}</span>
                </li>
              ))}
            </ul>
            <div className="mt-auto flex items-center gap-2 rounded-lg border border-severity-low/25 bg-severity-low/[0.07] px-3 py-2.5">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-70" aria-hidden="true" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
              </span>
              <p className="font-data text-[10.5px] tracking-wide text-emerald-300">
                No drift alerts · last checked 4 min ago
              </p>
            </div>
          </GlassCard>
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Performance metric gauges                                           */}
        {/* ------------------------------------------------------------------ */}
        <section aria-label="Model performance metrics">
          <SectionHeading
            title="Performance Metrics"
            hint={`held-out test set · n = ${GRAND_TOTAL.toLocaleString("en-US")}`}
          />
          <motion.div
            variants={gaugeContainer}
            initial="hidden"
            animate="show"
            className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
          >
            {MODEL_METRICS.map((metric) => {
              const positive = !metric.delta.startsWith("-");
              return (
                <motion.div key={metric.id} variants={gaugeItem}>
                  <GlassCard hover className="flex h-full flex-col items-center overflow-hidden">
                    <MetricGauge
                      value={metric.value}
                      label={metric.label}
                      sublabel="test set"
                      color={metric.color}
                      size={136}
                      strokeWidth={10}
                    />
                    <div className="mt-4 flex items-center gap-2">
                      <span
                        className={clsx(
                          "flex items-center gap-1 rounded-full border px-2 py-0.5 font-data text-[10.5px]",
                          positive
                            ? "border-severity-low/30 bg-severity-low/10 text-emerald-300"
                            : "border-severity-critical/30 bg-severity-critical/10 text-rose-300",
                        )}
                      >
                        {positive ? (
                          <TrendingUp className="h-3 w-3" aria-hidden="true" />
                        ) : (
                          <TrendingDown className="h-3 w-3" aria-hidden="true" />
                        )}
                        {metric.delta} vs prev
                      </span>
                    </div>
                    <p className="mt-3 text-center text-[11px] leading-relaxed text-cyber-muted">
                      {metric.description}
                    </p>
                  </GlassCard>
                </motion.div>
              );
            })}
          </motion.div>
        </section>

        {/* ------------------------------------------------------------------ */}
        {/* Confusion matrix + per-class report                                 */}
        {/* ------------------------------------------------------------------ */}
        <div className="grid gap-5 xl:grid-cols-2">
          <GlassCard>
            <SectionHeading
              title="Confusion Matrix"
              hint="rows = actual · columns = predicted"
              action={
                <span className="rounded border border-cyber-border/80 bg-cyber-surface/60 px-2 py-0.5 font-data text-[10px] tabular text-cyber-muted">
                  acc {OVERALL_ACCURACY}%
                </span>
              }
            />
            <div className="min-w-[440px] overflow-x-auto xl:min-w-0">
              <div className="grid grid-cols-[70px_repeat(5,minmax(0,1fr))] gap-1">
                {/* Corner + column headers */}
                <div className="flex items-end justify-end pb-1 pr-1.5 font-data text-[8.5px] tracking-widest text-cyber-muted/70 uppercase">
                  p→ · a↓
                </div>
                {CONFUSION_LABELS.map((label) => (
                  <div
                    key={`col-${label}`}
                    className={clsx(
                      "pb-1 text-center font-data text-[10px] tracking-wide transition-colors",
                      hoverCell && CONFUSION_LABELS[hoverCell.c] === label
                        ? "text-cyber-accent-bright"
                        : "text-cyber-muted",
                    )}
                  >
                    {label}
                  </div>
                ))}

                {/* Matrix rows */}
                {CONFUSION_MATRIX.map((row, r) => (
                  <Fragment key={`row-${CONFUSION_LABELS[r]}`}>
                    <div
                      className={clsx(
                        "flex items-center justify-end pr-1.5 font-data text-[10px] tracking-wide transition-colors",
                        hoverCell && hoverCell.r === r ? "text-cyber-accent-bright" : "text-cyber-muted",
                      )}
                    >
                      {CONFUSION_LABELS[r]}
                    </div>
                    {row.map((value, c) => {
                      const diagonal = r === c;
                      const hovered = hoverCell?.r === r && hoverCell?.c === c;
                      const inCrosshair = hoverCell && (hoverCell.r === r || hoverCell.c === c);
                      const pct = ((value / ROW_TOTALS[r]) * 100).toFixed(2);
                      return (
                        <button
                          key={`cell-${r}-${c}`}
                          type="button"
                          onMouseEnter={() => setHoverCell({ r, c })}
                          onMouseLeave={() => setHoverCell(null)}
                          onFocus={() => setHoverCell({ r, c })}
                          onBlur={() => setHoverCell(null)}
                          aria-label={`Actual ${CONFUSION_LABELS[r]}, predicted ${CONFUSION_LABELS[c]}: ${value} samples, ${pct}% of actual class`}
                          className={clsx(
                            "relative flex h-[46px] items-center justify-center rounded-md border transition-all duration-150",
                            hovered
                              ? "z-10 scale-[1.06] border-cyber-accent-bright/70 shadow-[0_0_18px_-2px_rgba(34,211,238,0.5)]"
                              : inCrosshair
                                ? "border-white/20"
                                : "border-transparent hover:border-white/15",
                          )}
                          style={{ backgroundColor: cellColor(value, diagonal) }}
                        >
                          <span
                            className={clsx(
                              "font-data text-[11px] tabular",
                              diagonal ? "font-semibold text-white" : "text-slate-200",
                            )}
                          >
                            {value.toLocaleString("en-US")}
                          </span>
                          {hovered && (
                            <span className="absolute inset-0 flex items-center justify-center rounded-md bg-cyber-bg/85 font-data text-[10.5px] font-semibold text-cyber-accent-bright">
                              {pct}%
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </Fragment>
                ))}
              </div>

              {/* Live readout */}
              <div className="glass-inset mt-3 flex min-h-[38px] items-center gap-2.5 rounded-lg px-3.5">
                {hoverCell ? (
                  <>
                    <span
                      className="h-1.5 w-1.5 shrink-0 rounded-full"
                      style={{
                        backgroundColor:
                          hoverCell.r === hoverCell.c ? "#22d3ee" : "#FF3B5C",
                      }}
                      aria-hidden="true"
                    />
                    <p className="font-data text-[11px] text-slate-200">
                      actual <span className="text-white">{CONFUSION_LABELS[hoverCell.r]}</span>
                      <span className="px-1.5 text-cyber-muted/70">→</span>
                      predicted <span className="text-white">{CONFUSION_LABELS[hoverCell.c]}</span>
                      <span className="px-2 text-cyber-muted/60">·</span>
                      <span className="tabular">
                        {CONFUSION_MATRIX[hoverCell.r][hoverCell.c].toLocaleString("en-US")}
                      </span>{" "}
                      samples
                      <span className="px-2 text-cyber-muted/60">·</span>
                      <span className="tabular text-cyber-accent-bright">
                        {((CONFUSION_MATRIX[hoverCell.r][hoverCell.c] / ROW_TOTALS[hoverCell.r]) * 100).toFixed(2)}%
                      </span>{" "}
                      of {CONFUSION_LABELS[hoverCell.r]}
                    </p>
                  </>
                ) : (
                  <p className="font-data text-[11px] text-cyber-muted">
                    {DIAGONAL_TOTAL.toLocaleString("en-US")} / {GRAND_TOTAL.toLocaleString("en-US")} correct ·
                    hover a cell for class-conditional percentages
                  </p>
                )}
              </div>
            </div>
          </GlassCard>

          <GlassCard>
            <SectionHeading title="Per-Class Performance" hint="precision · recall · F1 · support" />
            <div className="overflow-x-auto">
              <table className="w-full min-w-[440px] border-collapse">
                <thead>
                  <tr className="border-b border-cyber-border/60">
                    <th className="pb-2.5 pr-3 text-left font-data text-[10px] font-medium tracking-[0.16em] text-cyber-muted uppercase">
                      Class
                    </th>
                    {["Precision", "Recall", "F1", "Support"].map((head) => (
                      <th
                        key={head}
                        className="pb-2.5 pl-3 text-right font-data text-[10px] font-medium tracking-[0.16em] text-cyber-muted uppercase"
                      >
                        {head}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {CLASS_PERFORMANCE.map((row, index) => {
                    const category = row.label.toLowerCase() as AttackCategory;
                    const supportShare = (row.support / GRAND_TOTAL) * 100;
                    return (
                      <motion.tr
                        key={row.label}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.1 + index * 0.06, duration: 0.32 }}
                        className="border-b border-cyber-border/40 last:border-0"
                      >
                        <td className="py-3 pr-3">
                          <CategoryChip category={category} size="sm" />
                        </td>
                        {[
                          { value: row.precision },
                          { value: row.recall },
                          { value: row.f1 },
                        ].map((cell, i) => (
                          <td key={i} className="py-3 pl-3 align-middle">
                            <div className="flex flex-col items-end gap-1.5">
                              <span
                                className="font-data text-[12px] tabular"
                                style={{ color: metricColor(cell.value) }}
                              >
                                {cell.value.toFixed(1)}%
                              </span>
                              <span className="h-1 w-full max-w-[88px] overflow-hidden rounded-full bg-cyber-border/50">
                                <motion.span
                                  initial={{ width: 0 }}
                                  animate={{ width: `${cell.value}%` }}
                                  transition={{ duration: 0.8, delay: 0.25 + index * 0.06, ease: [0.22, 1, 0.36, 1] }}
                                  className="block h-full rounded-full"
                                  style={{ backgroundColor: metricColor(cell.value) }}
                                />
                              </span>
                            </div>
                          </td>
                        ))}
                        <td className="py-3 pl-3 text-right align-middle">
                          <span className="font-data text-[12px] tabular text-slate-100">
                            {row.support.toLocaleString("en-US")}
                          </span>
                          <span className="mt-1 block font-data text-[9.5px] tabular text-cyber-muted">
                            {supportShare.toFixed(1)}% of test
                          </span>
                        </td>
                      </motion.tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="mt-4 flex items-center gap-2 border-t border-cyber-border/50 pt-3 font-data text-[10.5px] text-cyber-muted">
              <Clock3 className="h-3 w-3 text-cyber-accent" aria-hidden="true" />
              Evaluated on KDDTest+ · weighted F1{" "}
              <span className="text-slate-200">95.0%</span> · minority classes tracked for drift
            </p>
          </GlassCard>
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Feature importance + confidence distribution                        */}
        {/* ------------------------------------------------------------------ */}
        <div className="grid gap-5 xl:grid-cols-2">
          <GlassCard>
            <SectionHeading
              title="Feature Importance"
              hint="top 15 · Gini impurity decrease"
              action={
                <span className="rounded border border-cyber-border/80 bg-cyber-surface/60 px-2 py-0.5 font-data text-[10px] tabular text-cyber-muted">
                  41 features total
                </span>
              }
            />
            <div className="w-full" style={{ height: 442 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  layout="vertical"
                  data={FEATURE_IMPORTANCE}
                  margin={{ top: 2, right: 46, bottom: 0, left: 0 }}
                >
                  <defs>
                    <linearGradient id={`${uid}-feat`} x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.95} />
                      <stop offset="100%" stopColor="#60a5fa" stopOpacity={0.9} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" horizontal={false} />
                  <XAxis
                    type="number"
                    domain={[0, 0.16]}
                    tickFormatter={(value: number) => `${Math.round(value * 100)}%`}
                    tick={{ fill: "#94a3b8", fontSize: 10, fontFamily: "var(--font-jetbrains-mono)" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="feature"
                    width={172}
                    tick={{ fill: "#94a3b8", fontSize: 10, fontFamily: "var(--font-jetbrains-mono)" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <RechartsTooltip
                    cursor={{ fill: "rgba(34, 211, 238, 0.06)" }}
                    content={<FeatureTooltip />}
                  />
                  <Bar
                    dataKey="importance"
                    name="Importance"
                    barSize={13}
                    radius={4}
                    fill={`url(#${uid}-feat)`}
                    background={{ fill: "rgba(23, 35, 61, 0.4)" }}
                    animationDuration={900}
                  >
                    <LabelList
                      dataKey="importance"
                      position="right"
                      formatter={(value: unknown) => `${(Number(value) * 100).toFixed(1)}%`}
                      fill="#94a3b8"
                      fontSize={9.5}
                      fontFamily="var(--font-jetbrains-mono)"
                    />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </GlassCard>

          <GlassCard className="flex flex-col">
            <SectionHeading
              title="Prediction Confidence Distribution"
              hint="scored events by class"
              action={
                <span className="rounded border border-cyber-border/80 bg-cyber-surface/60 px-2 py-0.5 font-data text-[10px] tabular text-cyber-muted">
                  threshold 0.75
                </span>
              }
            />
            <div className="min-h-0 w-full flex-1" style={{ height: 400 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={CONFIDENCE_DISTRIBUTION}
                  margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
                >
                  <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="bucket"
                    tick={{ fill: "#94a3b8", fontSize: 9, fontFamily: "var(--font-jetbrains-mono)" }}
                    axisLine={{ stroke: "#1e293b" }}
                    tickLine={false}
                    dy={6}
                  />
                  <YAxis
                    tickFormatter={(value: number) => formatCompact(value)}
                    tick={{ fill: "#94a3b8", fontSize: 10, fontFamily: "var(--font-jetbrains-mono)" }}
                    axisLine={false}
                    tickLine={false}
                    width={46}
                  />
                  <RechartsTooltip
                    cursor={{ fill: "rgba(34, 211, 238, 0.06)" }}
                    content={
                      <ChartTooltip
                        totalLabel="Events"
                        labelFormatter={(label) => `${String(label)}% confidence`}
                      />
                    }
                  />
                  <Bar dataKey="normal" name="Normal" stackId="conf" fill={ATTACK_COLORS.normal} barSize={30} animationDuration={800} />
                  <Bar dataKey="dos" name="DoS" stackId="conf" fill={ATTACK_COLORS.dos} barSize={30} animationDuration={800} />
                  <Bar dataKey="probe" name="Probe" stackId="conf" fill={ATTACK_COLORS.probe} barSize={30} animationDuration={800} />
                  <Bar dataKey="r2l" name="R2L" stackId="conf" fill={ATTACK_COLORS.r2l} barSize={30} animationDuration={800} />
                  <Bar
                    dataKey="u2r"
                    name="U2R"
                    stackId="conf"
                    fill={ATTACK_COLORS.u2r}
                    barSize={30}
                    radius={[3, 3, 0, 0]}
                    animationDuration={800}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <ul className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
              {(["normal", "dos", "probe", "r2l", "u2r"] as const).map((key) => (
                <li key={key} className="flex items-center gap-1.5 font-data text-[10px] tracking-wide text-cyber-muted uppercase">
                  <span
                    className="h-1.5 w-3 rounded-full"
                    style={{ backgroundColor: ATTACK_COLORS[key] }}
                    aria-hidden="true"
                  />
                  {key}
                </li>
              ))}
            </ul>
          </GlassCard>
        </div>
      </div>
    </PageShell>
  );
}

/* -------------------------------------------------------------------------- */
/*  Local building blocks                                                      */
/* -------------------------------------------------------------------------- */

function InfoCell({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof Database;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="min-w-0">
      <p className="flex items-center gap-1.5 font-data text-[9.5px] tracking-[0.18em] text-cyber-muted uppercase">
        <Icon className="h-3 w-3 text-cyber-accent" strokeWidth={1.9} aria-hidden="true" />
        {label}
      </p>
      <p className="mt-1 truncate font-data text-[12.5px] text-slate-100">{value}</p>
      {hint && <p className="mt-0.5 truncate font-data text-[9.5px] text-cyber-muted/80">{hint}</p>}
    </div>
  );
}
