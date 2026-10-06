"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import type { Variants } from "framer-motion";
import {
  AlertCircle,
  AlertOctagon,
  AlertTriangle,
  Bell,
  Info,
  ShieldCheck,
  Target,
} from "lucide-react";
import clsx from "clsx";
import PageShell from "@/components/layout/PageShell";
import GlassCard from "@/components/ui/GlassCard";
import type { GlassCardVariant } from "@/components/ui/GlassCard";
import AnimatedCounter from "@/components/ui/AnimatedCounter";
import SeverityBadge from "@/components/ui/SeverityBadge";
import CategoryChip from "@/components/ui/CategoryChip";
import { WORKFLOW_STATUS_META } from "@/components/ui/StatusChip";
import { ALERTS, SEVERITY_HEX } from "@/lib/mock-data";
import { formatClockUTC, formatDateTimeUTC } from "@/lib/format";
import type { AlertRecord, AlertWorkflowStatus, SeverityLevel } from "@/types";

/* -------------------------------------------------------------------------- */
/*  Tabs & stats vocabulary                                                    */
/* -------------------------------------------------------------------------- */

type TabId =
  | "all"
  | "critical"
  | "high"
  | "medium"
  | "low"
  | "new"
  | "investigating"
  | "resolved";

const TABS: Array<{ id: TabId; label: string }> = [
  { id: "all", label: "All" },
  { id: "critical", label: "Critical" },
  { id: "high", label: "High" },
  { id: "medium", label: "Medium" },
  { id: "low", label: "Low" },
  { id: "new", label: "New" },
  { id: "investigating", label: "Investigating" },
  { id: "resolved", label: "Resolved" },
];

const SEVERITIES: SeverityLevel[] = ["critical", "high", "medium", "low"];

const SEVERITY_CARD_VARIANT: Record<string, GlassCardVariant> = {
  critical: "danger",
  high: "warning",
  medium: "warning",
  low: "success",
};

interface StatTile {
  id: string;
  label: string;
  value: number;
  icon: typeof Bell;
  accent: string;
  chip: string;
}

const gridVariants: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.05 } },
};

const cardVariants: Variants = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] } },
};

/* -------------------------------------------------------------------------- */
/*  Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<AlertRecord[]>(ALERTS);
  const [tab, setTab] = useState<TabId>("all");

  const counts = useMemo(() => {
    const bySeverity: Record<string, number> = {};
    for (const severity of SEVERITIES) {
      bySeverity[severity] = alerts.filter((a) => a.severity === severity).length;
    }
    const byStatus = {
      new: alerts.filter((a) => a.status === "new").length,
      investigating: alerts.filter((a) => a.status === "investigating").length,
      acknowledged: alerts.filter((a) => a.status === "acknowledged").length,
      resolved: alerts.filter((a) => a.status === "resolved").length,
    };
    return { bySeverity, byStatus };
  }, [alerts]);

  const stats: StatTile[] = [
    {
      id: "total",
      label: "Total Alerts",
      value: alerts.length,
      icon: Bell,
      accent: "text-cyber-accent",
      chip: "border-cyber-accent/25 bg-cyber-accent/10 text-cyber-accent",
    },
    {
      id: "critical",
      label: "Critical",
      value: counts.bySeverity.critical,
      icon: AlertOctagon,
      accent: "text-severity-critical",
      chip: "border-severity-critical/25 bg-severity-critical/10 text-severity-critical",
    },
    {
      id: "high",
      label: "High",
      value: counts.bySeverity.high,
      icon: AlertTriangle,
      accent: "text-severity-high",
      chip: "border-severity-high/25 bg-severity-high/10 text-severity-high",
    },
    {
      id: "medium",
      label: "Medium",
      value: counts.bySeverity.medium,
      icon: Info,
      accent: "text-severity-medium",
      chip: "border-severity-medium/25 bg-severity-medium/10 text-severity-medium",
    },
    {
      id: "low",
      label: "Low",
      value: counts.bySeverity.low,
      icon: ShieldCheck,
      accent: "text-severity-low",
      chip: "border-severity-low/25 bg-severity-low/10 text-severity-low",
    },
  ];

  const filtered = useMemo(() => {
    if (tab === "all") return alerts;
    if ((SEVERITIES as string[]).includes(tab)) {
      return alerts.filter((alert) => alert.severity === tab);
    }
    return alerts.filter((alert) => alert.status === tab);
  }, [alerts, tab]);

  const tabCount = (id: TabId): number => {
    if (id === "all") return alerts.length;
    if ((SEVERITIES as string[]).includes(id)) {
      return counts.bySeverity[id as SeverityLevel] ?? 0;
    }
    return counts.byStatus[id as keyof typeof counts.byStatus] ?? 0;
  };

  const updateStatus = (id: string, status: AlertWorkflowStatus) => {
    setAlerts((prev) =>
      prev.map((alert) => (alert.id === id ? { ...alert, status } : alert)),
    );
  };

  return (
    <PageShell
      title="Security Alerts"
      description="Triage queue of ML-scored detections with severity, confidence, and workflow status."
      icon={Bell}
      moduleIndex="04 / 10"
    >
      <div className="space-y-5">
        {/* ---------------------------------------------------------------- */}
        {/* Alert stats                                                       */}
        {/* ---------------------------------------------------------------- */}
        <section aria-label="Alert statistics">
          <motion.div
            variants={gridVariants}
            initial="hidden"
            animate="show"
            className="grid grid-cols-2 gap-3 md:grid-cols-5 md:gap-4"
          >
            {stats.map((stat) => {
              const Icon = stat.icon;
              return (
                <motion.div key={stat.id} variants={cardVariants}>
                  <GlassCard hover className="p-4">
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-data text-[10px] tracking-[0.16em] text-cyber-muted uppercase">
                        {stat.label}
                      </p>
                      <span className={clsx("rounded-lg border p-1.5", stat.chip)}>
                        <Icon className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden="true" />
                      </span>
                    </div>
                    <AnimatedCounter
                      value={stat.value}
                      className={clsx(
                        "mt-2.5 block text-[26px] font-semibold tracking-tight",
                        stat.accent,
                      )}
                    />
                  </GlassCard>
                </motion.div>
              );
            })}
          </motion.div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Filter tabs                                                       */}
        {/* ------------------------------------------------------------------ */}
        <div
          className="flex flex-wrap items-center gap-1.5"
          role="tablist"
          aria-label="Filter alerts"
        >
          {TABS.map((item) => {
            const active = tab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setTab(item.id)}
                className={clsx(
                  "relative rounded-full border px-3.5 py-1.5 font-data text-[11px] tracking-wide",
                  active
                    ? "border-cyber-accent/45 text-cyber-accent-bright"
                    : "border-cyber-border/70 text-cyber-muted hover:border-cyber-accent/25 hover:text-slate-200",
                )}
              >
                {active && (
                  <motion.span
                    layoutId="alerts-tab-pill"
                    transition={{ type: "spring", stiffness: 420, damping: 34 }}
                    className="absolute inset-0 rounded-full bg-cyber-accent/12 shadow-[0_0_18px_-6px_rgba(34,211,238,0.5)]"
                    aria-hidden="true"
                  />
                )}
                <span className="relative z-10">
                  {item.label}
                  <span
                    className={clsx(
                      "ml-1.5 text-[10px] tabular",
                      active ? "text-cyber-accent" : "text-cyber-muted/70",
                    )}
                  >
                    {tabCount(item.id)}
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Alert cards                                                       */}
        {/* ---------------------------------------------------------------- */}
        <motion.div
          key={tab}
          variants={gridVariants}
          initial="hidden"
          animate="show"
          className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"
        >
          {filtered.map((alert) => (
            <motion.div key={alert.id} variants={cardVariants} layout>
              <AlertCard alert={alert} onStatusChange={updateStatus} />
            </motion.div>
          ))}
        </motion.div>

        {filtered.length === 0 && (
          <GlassCard className="p-10 text-center">
            <p className="font-data text-[12px] text-cyber-muted">
              No alerts in this state right now.
            </p>
            <button
              type="button"
              onClick={() => setTab("all")}
              className="mt-3 rounded-lg border border-cyber-accent/30 bg-cyber-accent/10 px-4 py-1.5 font-data text-[11px] text-cyber-accent-bright hover:bg-cyber-accent/20"
            >
              Show all alerts
            </button>
          </GlassCard>
        )}
      </div>
    </PageShell>
  );
}

/* -------------------------------------------------------------------------- */
/*  Alert card                                                                 */
/* -------------------------------------------------------------------------- */

interface AlertCardProps {
  alert: AlertRecord;
  onStatusChange: (id: string, status: AlertWorkflowStatus) => void;
}

function AlertCard({ alert, onStatusChange }: AlertCardProps) {
  const statusMeta = WORKFLOW_STATUS_META[alert.status];

  return (
    <GlassCard
      hover
      variant={SEVERITY_CARD_VARIANT[alert.severity] ?? "default"}
      className="flex h-full flex-col p-5"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <SeverityBadge level={alert.severity} size="sm" />
        <select
          value={alert.status}
          onChange={(event) =>
            onStatusChange(alert.id, event.target.value as AlertWorkflowStatus)
          }
          aria-label={`Change status for ${alert.id}`}
          className={clsx(
            "h-7 rounded-md border bg-cyber-surface/70 px-1.5 font-data text-[10px] tracking-wide uppercase focus:border-cyber-accent/40 focus:outline-none",
            statusMeta.border,
            statusMeta.text,
          )}
        >
          {(Object.keys(WORKFLOW_STATUS_META) as AlertWorkflowStatus[]).map((status) => (
            <option key={status} value={status} className="bg-cyber-elevated text-slate-200">
              {WORKFLOW_STATUS_META[status].label}
            </option>
          ))}
        </select>
      </div>

      {/* Title */}
      <h3 className="mt-3 text-[14px] font-semibold leading-snug tracking-tight text-slate-50">
        {alert.title}
      </h3>
      <p className="mt-1.5 flex items-center gap-1.5 font-data text-[11px] text-cyber-muted">
        <span className="truncate">{alert.source}</span>
        <span className="text-cyber-accent">→</span>
        <span className="truncate">{alert.destination}</span>
        <span className="ml-auto shrink-0 rounded border border-cyber-border/70 bg-cyber-surface/60 px-1.5 py-0.5 text-[9.5px]">
          {alert.protocol}
        </span>
      </p>

      {/* Confidence + risk */}
      <div className="mt-4 space-y-3">
        <div>
          <div className="flex items-center justify-between text-[10.5px]">
            <span className="flex items-center gap-1.5 font-data tracking-[0.14em] text-cyber-muted uppercase">
              <Target className="h-3 w-3 text-cyber-accent" aria-hidden="true" />
              Confidence
            </span>
            <span className="font-data tabular text-slate-100">
              {(alert.confidence * 100).toFixed(1)}%
            </span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-cyber-border/50">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${alert.confidence * 100}%` }}
              transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
              className="h-full rounded-full bg-gradient-to-r from-cyber-accent/60 to-cyber-accent"
            />
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between text-[10.5px]">
            <span className="flex items-center gap-1.5 font-data tracking-[0.14em] text-cyber-muted uppercase">
              <AlertCircle className="h-3 w-3" aria-hidden="true" />
              Risk Score
            </span>
            <span className="font-data tabular text-slate-100">{alert.riskScore}/100</span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-cyber-border/50">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${alert.riskScore}%` }}
              transition={{ duration: 0.8, delay: 0.1, ease: [0.22, 1, 0.36, 1] }}
              className="h-full rounded-full"
              style={{
                backgroundColor: SEVERITY_HEX[alert.severity],
                boxShadow: `0 0 10px -2px ${SEVERITY_HEX[alert.severity]}80`,
              }}
            />
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="mt-auto flex items-center justify-between gap-2 pt-4">
        <div className="flex items-center gap-2">
          <CategoryChip category={alert.category} size="sm" />
          <span className="font-data text-[11px] text-slate-300">{alert.attackType}</span>
        </div>
        <span
          className="font-data text-[10px] tabular text-cyber-muted"
          title={`${formatDateTimeUTC(alert.timestamp)} UTC`}
        >
          {formatClockUTC(alert.timestamp)} UTC
        </span>
      </div>
    </GlassCard>
  );
}
