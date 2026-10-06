"use client";

import { motion, type Variants } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  Database,
  Layers,
  Timer,
  Workflow,
} from "lucide-react";
import clsx from "clsx";
import PageShell from "@/components/layout/PageShell";
import GlassCard from "@/components/ui/GlassCard";
import SectionHeading from "@/components/ui/SectionHeading";
import StatusIndicator from "@/components/ui/StatusIndicator";
import { PIPELINE_STAGES } from "@/lib/mock-data";
import { formatCompact } from "@/lib/format";
import type { PipelineStage } from "@/types";

/* -------------------------------------------------------------------------- */
/*  Flow gradient: green → cyan → blue across the stage list                   */
/* -------------------------------------------------------------------------- */

function hexToRgb(hex: string): [number, number, number] {
  const value = parseInt(hex.slice(1), 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

function lerpHex(a: string, b: string, t: number): string {
  const [ar, ag, ab] = hexToRgb(a);
  const [br, bg, bb] = hexToRgb(b);
  const mix = (x: number, y: number) => Math.round(x + (y - x) * t);
  return `rgb(${mix(ar, br)}, ${mix(ag, bg)}, ${mix(ab, bb)})`;
}

function flowColor(t: number): string {
  return t <= 0.5
    ? lerpHex("#34d399", "#22d3ee", t * 2)
    : lerpHex("#22d3ee", "#60a5fa", (t - 0.5) * 2);
}

const STAGE_COLORS = PIPELINE_STAGES.map((_, i) =>
  flowColor(i / (PIPELINE_STAGES.length - 1)),
);

const ONLINE_COUNT = PIPELINE_STAGES.filter((s) => s.status === "online").length;
const WARNING_COUNT = PIPELINE_STAGES.filter((s) => s.status === "warning").length;
const TOTAL_LATENCY = PIPELINE_STAGES.reduce((acc, s) => acc + s.latencyMs, 0);
const MAX_PROCESSED = Math.max(...PIPELINE_STAGES.map((s) => s.processed));
const INGEST_THROUGHPUT =
  PIPELINE_STAGES.find((s) => s.id === "spark")?.throughput ?? "24.6K ev/s";

/* -------------------------------------------------------------------------- */
/*  Motion variants                                                            */
/* -------------------------------------------------------------------------- */

const listContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.055, delayChildren: 0.08 } },
};

const listItem: Variants = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.36, ease: [0.22, 1, 0.36, 1] } },
};

/* -------------------------------------------------------------------------- */
/*  Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function PipelinePage() {
  return (
    <PageShell
      title="Data Pipeline"
      description="End-to-end streaming topology - from NSL-KDD ingest to live dashboard fan-out."
      icon={Workflow}
      moduleIndex="08 / 10"
    >
      <div className="space-y-5">
        {/* ------------------------------------------------------------------ */}
        {/* Summary tiles                                                       */}
        {/* ------------------------------------------------------------------ */}
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <SummaryTile
            icon={Layers}
            label="Pipeline Stages"
            value={`${PIPELINE_STAGES.length}`}
            hint={`${ONLINE_COUNT} online · ${WARNING_COUNT} warning`}
            accent="#34d399"
          />
          <SummaryTile
            icon={Timer}
            label="End-to-End Latency"
            value={`${TOTAL_LATENCY} ms`}
            hint="sensor tap → dashboard render"
            accent="#22d3ee"
          />
          <SummaryTile
            icon={Activity}
            label="Stream Throughput"
            value={INGEST_THROUGHPUT}
            hint="sustained processing rate"
            accent="#60a5fa"
          />
          <SummaryTile
            icon={Database}
            label="Records Processed"
            value={formatCompact(MAX_PROCESSED)}
            hint="since pipeline start"
            accent="#a855f7"
          />
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Animated stage flow                                                 */}
        {/* ------------------------------------------------------------------ */}
        <GlassCard className="overflow-hidden">
          <SectionHeading
            title="Streaming Topology"
            hint="live event path · last 24h"
            action={
              <div className="flex items-center gap-3">
                <span className="hidden items-center gap-1.5 font-data text-[10px] tracking-wide text-cyber-muted sm:flex">
                  edge
                  <span
                    className="h-1.5 w-14 rounded-full"
                    style={{
                      background:
                        "linear-gradient(90deg, #34d399, #22d3ee, #60a5fa)",
                    }}
                    aria-hidden="true"
                  />
                  data plane
                </span>
                <span className="flex items-center gap-1.5 font-data text-[10px] text-emerald-300">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" aria-hidden="true" />
                  flowing
                </span>
              </div>
            }
          />

          <motion.ol
            variants={listContainer}
            initial="hidden"
            animate="show"
            className="mx-auto max-w-4xl"
          >
            {PIPELINE_STAGES.map((stage, index) => (
              <motion.li key={stage.id} variants={listItem} className="list-none">
                <StageCard stage={stage} index={index} color={STAGE_COLORS[index]} />
                {index < PIPELINE_STAGES.length - 1 && (
                  <Connector
                    from={STAGE_COLORS[index]}
                    to={STAGE_COLORS[index + 1]}
                    warning={stage.status === "warning"}
                  />
                )}
              </motion.li>
            ))}
          </motion.ol>

          {/* Backpressure watch strip */}
          <div className="mx-auto mt-2 flex max-w-4xl items-start gap-3 rounded-lg border border-severity-medium/25 bg-severity-medium/[0.06] px-4 py-3">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" strokeWidth={2} aria-hidden="true" />
            <div>
              <p className="text-[12px] text-amber-200">
                Backpressure watch: Spark Streaming micro-batch 14 exceeded its 2.4 s SLA
                (queue depth 1.1K).
              </p>
              <p className="mt-0.5 font-data text-[10.5px] text-cyber-muted">
                autoscale armed · target 32 executors · no data loss (Kafka retention 72h)
              </p>
            </div>
          </div>
        </GlassCard>
      </div>
    </PageShell>
  );
}

/* -------------------------------------------------------------------------- */
/*  Stage card                                                                 */
/* -------------------------------------------------------------------------- */

function StageCard({
  stage,
  index,
  color,
}: {
  stage: PipelineStage;
  index: number;
  color: string;
}) {
  return (
    <GlassCard
      hover
      variant={stage.status === "warning" ? "warning" : "default"}
      className={clsx(
        "relative overflow-hidden p-4 pl-5",
        stage.status === "warning" && "shadow-[0_0_26px_-12px_rgba(255,209,102,0.4)]",
      )}
    >
      {/* Accent rail segmented by flow position */}
      <span
        className="absolute bottom-4 left-0 top-4 w-[3px] rounded-r-full"
        style={{
          background: `linear-gradient(to bottom, ${color}, ${color}55)`,
          boxShadow: `0 0 12px -2px ${color}`,
        }}
        aria-hidden="true"
      />

      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        {/* Step + icon */}
        <div className="flex items-center gap-3">
          <span className="w-6 font-data text-[10px] tabular text-cyber-muted/80">
            {String(index + 1).padStart(2, "0")}
          </span>
          <span
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border transition-shadow"
            style={{
              borderColor: `${color}4d`,
              backgroundColor: `${color}14`,
              boxShadow: `0 0 18px -6px ${color}66`,
            }}
          >
            <stage.icon className="h-[18px] w-[18px]" style={{ color }} strokeWidth={1.9} aria-hidden="true" />
          </span>
        </div>

        {/* Identity */}
        <div className="min-w-[220px] flex-1">
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <h3 className="text-[13.5px] font-semibold tracking-tight text-slate-50">
              {stage.name}
            </h3>
            <StatusIndicator status={stage.status} size="sm" />
          </div>
          <p className="mt-0.5 text-[11.5px] leading-relaxed text-cyber-muted">{stage.role}</p>
          {stage.note && (
            <span className="mt-1.5 inline-block rounded border border-cyber-border/70 bg-cyber-surface/60 px-1.5 py-0.5 font-data text-[9.5px] text-cyber-muted">
              {stage.note}
            </span>
          )}
        </div>

        {/* Metrics */}
        <div className="grid w-full grid-cols-3 gap-x-6 border-t border-cyber-border/40 pt-2.5 sm:w-auto sm:border-t-0 sm:pt-0">
          <StageMetric label="Throughput" value={stage.throughput} />
          <StageMetric
            label="Latency"
            value={stage.latencyMs > 0 ? `${stage.latencyMs} ms` : "—"}
          />
          <StageMetric label="Processed" value={formatCompact(stage.processed)} />
        </div>
      </div>
    </GlassCard>
  );
}

function StageMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="font-data text-[9px] tracking-[0.16em] text-cyber-muted/80 uppercase">
        {label}
      </p>
      <p className="mt-0.5 truncate font-data text-[12px] tabular text-slate-100">{value}</p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Connector with travelling particles                                        */
/* -------------------------------------------------------------------------- */

function Connector({
  from,
  to,
  warning,
}: {
  from: string;
  to: string;
  warning: boolean;
}) {
  const particleColor = warning ? "#FFD166" : to;
  return (
    <div className="relative ml-[38px] h-12 w-1.5" aria-hidden="true">
      {/* Gradient spine */}
      <span
        className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2"
        style={{ background: `linear-gradient(to bottom, ${from}80, ${to}cc)` }}
      />
      {/* Travelling particles */}
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="animate-flow-particle absolute left-1/2 h-1.5 w-1.5 -translate-x-1/2 rounded-full"
          style={{
            backgroundColor: particleColor,
            boxShadow: `0 0 8px 1px ${particleColor}`,
            animationDelay: `${i * 0.77}s`,
          }}
        />
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Summary tile                                                               */
/* -------------------------------------------------------------------------- */

function SummaryTile({
  icon: Icon,
  label,
  value,
  hint,
  accent,
}: {
  icon: typeof Layers;
  label: string;
  value: string;
  hint: string;
  accent: string;
}) {
  return (
    <GlassCard hover className="overflow-hidden">
      <div className="flex items-center justify-between gap-3">
        <p className="font-data text-[10px] tracking-[0.18em] text-cyber-muted uppercase">
          {label}
        </p>
        <span
          className="flex h-8 w-8 items-center justify-center rounded-lg border"
          style={{
            borderColor: `${accent}40`,
            backgroundColor: `${accent}14`,
          }}
        >
          <Icon className="h-4 w-4" style={{ color: accent }} strokeWidth={1.9} aria-hidden="true" />
        </span>
      </div>
      <p className="mt-3 font-data text-[24px] leading-none tabular text-slate-50">{value}</p>
      <p className="mt-2 text-[11px] text-cyber-muted">{hint}</p>
    </GlassCard>
  );
}
