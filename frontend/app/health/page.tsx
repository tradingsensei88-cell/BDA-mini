"use client";

import { motion, type Variants } from "framer-motion";
import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  HeartPulse,
  Server,
  Timer,
} from "lucide-react";
import clsx from "clsx";
import PageShell from "@/components/layout/PageShell";
import GlassCard from "@/components/ui/GlassCard";
import SectionHeading from "@/components/ui/SectionHeading";
import StatusIndicator from "@/components/ui/StatusIndicator";
import SeverityBadge from "@/components/ui/SeverityBadge";
import { HEALTH_SUMMARY, INCIDENTS, SERVICE_HEALTH } from "@/lib/mock-data";
import { formatDateTimeUTC } from "@/lib/format";
import type { ServiceStatus } from "@/types";

/* -------------------------------------------------------------------------- */
/*  Constants                                                                  */
/* -------------------------------------------------------------------------- */

const STATUS_HEX: Record<ServiceStatus, string> = {
  online: "#34d399",
  warning: "#FFD166",
  offline: "#f43f5e",
  connecting: "#38bdf8",
};

const SUMMARY_ICONS = [Activity, Server, AlertTriangle, Timer] as const;

const containerVariants: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06, delayChildren: 0.08 } },
};

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] } },
};

/* -------------------------------------------------------------------------- */
/*  Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function SystemHealthPage() {
  return (
    <PageShell
      title="System Health"
      description="Live availability, throughput, and incident history for every service in the SOC stack."
      icon={HeartPulse}
      moduleIndex="09 / 10"
    >
      <div className="space-y-5">
        {/* ------------------------------------------------------------------ */}
        {/* Platform summary strip                                              */}
        {/* ------------------------------------------------------------------ */}
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {HEALTH_SUMMARY.map((row, index) => {
            const Icon = SUMMARY_ICONS[index % SUMMARY_ICONS.length];
            return (
              <GlassCard key={row.label} hover className="flex items-center gap-4">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-cyber-accent/25 bg-cyber-accent/10">
                  <Icon className="h-4 w-4 text-cyber-accent" strokeWidth={1.9} aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <p className="truncate font-data text-[10px] tracking-[0.16em] text-cyber-muted uppercase">
                    {row.label}
                  </p>
                  <p className="mt-1 font-data text-[19px] leading-none tabular text-slate-50">
                    {row.value}
                  </p>
                </div>
              </GlassCard>
            );
          })}
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Service cards                                                       */
        /* ------------------------------------------------------------------ */}
        <section aria-label="Service health cards">
          <SectionHeading
            title="Services"
            hint={`${SERVICE_HEALTH.length} reporting · sparkline = last 1h`}
            action={
              <span className="flex items-center gap-3 font-data text-[10px] text-cyber-muted">
                <span className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
                  online
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-400" aria-hidden="true" />
                  warning
                </span>
              </span>
            }
          />
          <motion.div
            variants={containerVariants}
            initial="hidden"
            animate="show"
            className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"
          >
            {SERVICE_HEALTH.map((service) => {
              const color = STATUS_HEX[service.status];
              return (
                <motion.div key={service.id} variants={itemVariants} className="h-full">
                  <GlassCard
                    hover
                    variant={service.status === "warning" ? "warning" : "default"}
                    className="flex h-full flex-col"
                  >
                    {/* Header */}
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex min-w-0 items-start gap-3">
                        <span
                          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border"
                          style={{
                            borderColor: `${color}40`,
                            backgroundColor: `${color}14`,
                          }}
                        >
                          <service.icon
                            className="h-[17px] w-[17px]"
                            style={{ color }}
                            strokeWidth={1.9}
                            aria-hidden="true"
                          />
                        </span>
                        <div className="min-w-0">
                          <h3 className="truncate text-[13.5px] font-semibold tracking-tight text-slate-50">
                            {service.name}
                          </h3>
                          <p className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-cyber-muted">
                            {service.summary}
                          </p>
                        </div>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="font-data text-[15px] leading-none tabular text-slate-50">
                          {service.uptime.toFixed(2)}%
                        </p>
                        <p className="mt-1 font-data text-[9px] tracking-[0.14em] text-cyber-muted uppercase">
                          30d uptime
                        </p>
                      </div>
                    </div>

                    <div className="mt-2.5">
                      <StatusIndicator status={service.status} size="sm" />
                    </div>

                    {/* Metrics mini grid */}
                    <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-cyber-border/50 pt-3.5">
                      {service.metrics.map((metric) => (
                        <div key={metric.label} className="min-w-0">
                          <p className="truncate font-data text-[9px] tracking-[0.16em] text-cyber-muted/80 uppercase">
                            {metric.label}
                          </p>
                          <p className="mt-0.5 truncate font-data text-[12px] tabular text-slate-100">
                            {metric.value}
                          </p>
                        </div>
                      ))}
                    </div>

                    {/* Sparkline */}
                    <div className="mt-4 h-[56px] w-full">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart
                          data={service.sparkline.map((value, i) => ({ i, value }))}
                          margin={{ top: 4, right: 2, bottom: 2, left: 2 }}
                        >
                          <YAxis hide domain={["dataMin - 2", "dataMax + 2"]} />
                          <Line
                            type="monotone"
                            dataKey="value"
                            stroke={color}
                            strokeWidth={1.6}
                            dot={false}
                            isAnimationActive
                            animationDuration={900}
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>

                    {/* 24h uptime bars */}
                    <div className="mt-auto pt-3.5">
                      <div className="flex h-4 items-stretch gap-[2px]" role="img" aria-label={`${service.name} availability over the last 24 hours`}>
                        {service.uptimeBars.map((slot, i) => (
                          <span
                            key={i}
                            className="flex-1 rounded-[1.5px]"
                            style={{
                              backgroundColor: STATUS_HEX[slot],
                              opacity: slot === "online" ? 0.75 : 0.95,
                            }}
                          />
                        ))}
                      </div>
                      <div className="mt-1.5 flex items-center justify-between font-data text-[9px] tracking-wide text-cyber-muted/70">
                        <span>24h ago</span>
                        <span>now</span>
                      </div>
                    </div>
                  </GlassCard>
                </motion.div>
              );
            })}
          </motion.div>
        </section>

        {/* ------------------------------------------------------------------ */}
        {/* Uptime timeline                                                     */}
        {/* ------------------------------------------------------------------ */}
        <GlassCard>
          <SectionHeading
            title="Uptime Timeline"
            hint="last 72 hours · all services"
            action={
              <span className="rounded border border-cyber-border/80 bg-cyber-surface/60 px-2 py-0.5 font-data text-[10px] tabular text-cyber-muted">
                {INCIDENTS.length} events
              </span>
            }
          />
          <ol className="relative ml-2 space-y-5 border-l border-cyber-border/70 pl-6">
            {INCIDENTS.map((incident, index) => {
              const ongoing = incident.status === "ongoing";
              return (
                <motion.li
                  key={incident.id}
                  initial={{ opacity: 0, x: 10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.1 + index * 0.07, duration: 0.34 }}
                  className="relative"
                >
                  {/* Timeline dot */}
                  <span
                    className={clsx(
                      "absolute -left-[30.5px] top-1 flex h-2.5 w-2.5 items-center justify-center rounded-full border-2 border-cyber-surface",
                      ongoing ? "bg-amber-400" : "bg-emerald-400",
                    )}
                    aria-hidden="true"
                  >
                    {ongoing && (
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-60" />
                    )}
                  </span>

                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                    <span className="font-data text-[11.5px] tabular text-slate-300">
                      {formatDateTimeUTC(incident.time)}
                    </span>
                    <span className="rounded border border-cyber-border/80 bg-cyber-surface/60 px-1.5 py-0.5 font-data text-[10px] text-cyber-muted">
                      {incident.service}
                    </span>
                    <SeverityBadge level={incident.severity} size="sm" />
                    <span className="font-data text-[10px] text-cyber-muted/70">{incident.id}</span>
                    <span
                      className={clsx(
                        "ml-auto flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-data text-[10px] tracking-wide uppercase",
                        ongoing
                          ? "border-amber-400/30 bg-amber-400/10 text-amber-300"
                          : "border-severity-low/30 bg-severity-low/10 text-emerald-300",
                      )}
                    >
                      {ongoing ? (
                        <span className="h-1 w-1 animate-pulse rounded-full bg-amber-400" aria-hidden="true" />
                      ) : (
                        <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
                      )}
                      {incident.status}
                    </span>
                  </div>
                  <p className="mt-1.5 text-[12.5px] leading-snug text-slate-200">
                    {incident.title}
                  </p>
                </motion.li>
              );
            })}
          </ol>
          <p className="mt-5 border-t border-cyber-border/50 pt-3 font-data text-[10.5px] text-cyber-muted">
            Platform MTTR 38 min · HDFS rebalance window scheduled 02:00 UTC
          </p>
        </GlassCard>
      </div>
    </PageShell>
  );
}
