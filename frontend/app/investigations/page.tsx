"use client";

import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, type Variants } from "framer-motion";
import {
  CheckCircle2,
  ClipboardList,
  Download,
  FileSearch,
  FolderOpen,
  FolderSearch,
  Link2,
  Loader,
  ShieldCheck,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import clsx from "clsx";
import PageShell from "@/components/layout/PageShell";
import GlassCard from "@/components/ui/GlassCard";
import SectionHeading from "@/components/ui/SectionHeading";
import SeverityBadge from "@/components/ui/SeverityBadge";
import CategoryChip from "@/components/ui/CategoryChip";
import StatusChip from "@/components/ui/StatusChip";
import AnimatedCounter from "@/components/ui/AnimatedCounter";
import MetricGauge from "@/components/charts/MetricGauge";
import { INVESTIGATIONS, SEVERITY_HEX, THREAT_EVENTS } from "@/lib/mock-data";
import { formatClockUTC, formatDateTimeUTC, riskBarClass, riskTextClass } from "@/lib/format";
import type { InvestigationRecord, InvestigationStatus } from "@/types";

/* -------------------------------------------------------------------------- */
/*  Constants                                                                  */
/* -------------------------------------------------------------------------- */

type TabId = "all" | InvestigationStatus;

const TABS: Array<{ id: TabId; label: string }> = [
  { id: "all", label: "All Cases" },
  { id: "open", label: "Open" },
  { id: "in_progress", label: "In Progress" },
  { id: "closed", label: "Closed" },
];

const INV_STATUS_META: Record<
  InvestigationStatus,
  { label: string; chip: string; dot: string; pulse: boolean }
> = {
  open: {
    label: "Open",
    chip: "border-sky-400/30 bg-sky-400/10 text-sky-300",
    dot: "bg-sky-400",
    pulse: true,
  },
  in_progress: {
    label: "In Progress",
    chip: "border-amber-400/30 bg-amber-400/10 text-amber-300",
    dot: "bg-amber-400",
    pulse: true,
  },
  closed: {
    label: "Closed",
    chip: "border-severity-low/30 bg-severity-low/10 text-emerald-300",
    dot: "bg-emerald-400",
    pulse: false,
  },
};

const SORTED_INVESTIGATIONS = [...INVESTIGATIONS].sort(
  (a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt),
);

const containerVariants: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.07, delayChildren: 0.06 } },
};

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.38, ease: [0.22, 1, 0.36, 1] } },
};

/* -------------------------------------------------------------------------- */
/*  Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function InvestigationsPage() {
  const [tab, setTab] = useState<TabId>("all");
  const [selected, setSelected] = useState<InvestigationRecord | null>(null);

  const filtered = useMemo(
    () =>
      tab === "all"
        ? SORTED_INVESTIGATIONS
        : SORTED_INVESTIGATIONS.filter((record) => record.status === tab),
    [tab],
  );

  const counts = useMemo(() => {
    const byStatus = (status: InvestigationStatus) =>
      INVESTIGATIONS.filter((record) => record.status === status).length;
    return {
      all: INVESTIGATIONS.length,
      open: byStatus("open"),
      in_progress: byStatus("in_progress"),
      closed: byStatus("closed"),
      linked: INVESTIGATIONS.reduce((acc, record) => acc + record.relatedAlerts, 0),
    };
  }, []);

  return (
    <PageShell
      title="Investigations"
      description="Case workspace for escalated threats - assignments, findings, and linked alerts."
      icon={FolderSearch}
      moduleIndex="07 / 10"
    >
      <div className="space-y-5">
        {/* ------------------------------------------------------------------ */}
        {/* Stat tiles                                                          */}
        {/* ------------------------------------------------------------------ */}
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile icon={FolderOpen} label="Open Cases" value={counts.open} accent="#38bdf8" />
          <StatTile icon={Loader} label="In Progress" value={counts.in_progress} accent="#FFD166" />
          <StatTile icon={CheckCircle2} label="Closed (30d)" value={counts.closed} accent="#34d399" />
          <StatTile icon={Link2} label="Linked Alerts" value={counts.linked} accent="#22d3ee" />
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Case list                                                           */}
        {/* ------------------------------------------------------------------ */}
        <section aria-label="Investigation case list">
          <SectionHeading
            title="Case Files"
            hint={`${filtered.length} shown · sorted by recency`}
            action={
              <div className="flex items-center gap-1 rounded-full border border-cyber-border/70 bg-cyber-surface/60 p-1">
                {TABS.map((item) => {
                  const active = tab === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setTab(item.id)}
                      className={clsx(
                        "relative rounded-full px-3 py-1.5 font-data text-[10.5px] tracking-wide uppercase transition-colors",
                        active ? "text-cyber-bg" : "text-cyber-muted hover:text-slate-200",
                      )}
                    >
                      {active && (
                        <motion.span
                          layoutId="investigations-tab-pill"
                          transition={{ type: "spring", stiffness: 420, damping: 34 }}
                          className="absolute inset-0 rounded-full bg-cyber-accent"
                        />
                      )}
                      <span className="relative flex items-center gap-1.5">
                        {item.label}
                        <span
                          className={clsx(
                            "font-data text-[9px] tabular",
                            active ? "text-cyber-bg/70" : "text-cyber-muted/70",
                          )}
                        >
                          {counts[item.id]}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            }
          />

          <motion.ul
            key={tab}
            variants={containerVariants}
            initial="hidden"
            animate="show"
            className="grid gap-4 xl:grid-cols-2"
          >
            {filtered.map((record) => {
              const statusMeta = INV_STATUS_META[record.status];
              return (
                <motion.li key={record.id} variants={itemVariants} className="h-full">
                  <button
                    type="button"
                    onClick={() => setSelected(record)}
                    className="block h-full w-full text-left"
                    aria-label={`Open investigation ${record.id}`}
                  >
                    <GlassCard
                      hover
                      variant={record.severity === "critical" ? "danger" : "default"}
                      className="flex h-full flex-col"
                    >
                      {/* Header */}
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-data text-[12px] font-semibold text-slate-100">
                          {record.id}
                        </span>
                        <SeverityBadge level={record.severity} size="sm" />
                        <CategoryChip category={record.category} size="sm" />
                        <span
                          className={clsx(
                            "ml-auto flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-data text-[10px] tracking-wide uppercase",
                            statusMeta.chip,
                          )}
                        >
                          <span
                            className={clsx(
                              "h-1 w-1 rounded-full",
                              statusMeta.dot,
                              statusMeta.pulse && "animate-pulse",
                            )}
                            aria-hidden="true"
                          />
                          {statusMeta.label}
                        </span>
                      </div>

                      {/* Title + summary */}
                      <h3 className="mt-2.5 text-[14px] font-semibold tracking-tight text-slate-50">
                        {record.title}
                      </h3>
                      <p className="mt-1.5 line-clamp-2 text-[11.5px] leading-relaxed text-cyber-muted">
                        {record.summary}
                      </p>

                      {/* Analyst + dates */}
                      <div className="mt-3.5 flex flex-wrap items-center gap-x-4 gap-y-2">
                        <span className="flex items-center gap-2">
                          <span className="flex h-6 w-6 items-center justify-center rounded-full border border-cyber-accent/30 bg-cyber-accent/10 font-data text-[9px] font-semibold text-cyber-accent-bright">
                            {initials(record.analyst)}
                          </span>
                          <span className="text-[11.5px] text-slate-200">{record.analyst}</span>
                          <span className="hidden font-data text-[10px] text-cyber-muted/80 sm:inline">
                            · {record.team}
                          </span>
                        </span>
                        <span className="ml-auto font-data text-[10px] tabular text-cyber-muted">
                          opened {formatDateTimeUTC(record.createdAt)}
                        </span>
                      </div>

                      {/* Footer */}
                      <div className="mt-auto border-t border-cyber-border/50 pt-3.5">
                        <div className="flex items-center gap-4">
                          <span className="flex shrink-0 items-center gap-1.5 font-data text-[10.5px] text-cyber-muted">
                            <ClipboardList className="h-3 w-3 text-cyber-accent" aria-hidden="true" />
                            {record.relatedAlerts} related alerts
                          </span>
                          <span className="flex min-w-0 flex-1 items-center gap-2">
                            <span className="font-data text-[9.5px] tracking-wide text-cyber-muted/80 uppercase">
                              risk
                            </span>
                            <span className="h-1.5 min-w-[40px] flex-1 overflow-hidden rounded-full bg-cyber-border/50">
                              <motion.span
                                initial={{ width: 0 }}
                                animate={{ width: `${record.riskScore}%` }}
                                transition={{ duration: 0.8, delay: 0.3, ease: [0.22, 1, 0.36, 1] }}
                                className={clsx("block h-full rounded-full", riskBarClass(record.riskScore))}
                              />
                            </span>
                            <span
                              className={clsx(
                                "shrink-0 font-data text-[11px] tabular",
                                riskTextClass(record.riskScore),
                              )}
                            >
                              {record.riskScore}
                            </span>
                          </span>
                          <span className="shrink-0 font-data text-[10.5px] tabular text-slate-300">
                            conf {(record.confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      </div>
                    </GlassCard>
                  </button>
                </motion.li>
              );
            })}
          </motion.ul>
        </section>
      </div>

      {/* -------------------------------------------------------------------- */}
      {/* Detail modal                                                          */}
      {/* -------------------------------------------------------------------- */}
      <InvestigationModal record={selected} onClose={() => setSelected(null)} />
    </PageShell>
  );
}

/* -------------------------------------------------------------------------- */
/*  Detail modal                                                               */
/* -------------------------------------------------------------------------- */

function InvestigationModal({
  record,
  onClose,
}: {
  record: InvestigationRecord | null;
  onClose: () => void;
}) {
  /* Escape closes the modal. */
  useEffect(() => {
    if (!record) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [record, onClose]);

  const relatedAlerts = useMemo(
    () =>
      record
        ? THREAT_EVENTS.filter((event) => event.category === record.category).slice(0, 3)
        : [],
    [record],
  );

  return (
    <AnimatePresence>
      {record && (
        <>
          <motion.div
            key="inv-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            className="fixed inset-0 z-[55] bg-cyber-bg/70 backdrop-blur-sm"
            aria-hidden="true"
          />
          <div className="pointer-events-none fixed inset-0 z-[60] flex items-center justify-center p-4">
            <motion.div
              key="inv-panel"
              role="dialog"
              aria-modal="true"
              aria-label={`Investigation ${record.id}`}
              initial={{ opacity: 0, y: 18, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 14, scale: 0.97 }}
              transition={{ type: "spring", stiffness: 380, damping: 34 }}
              className="glass-panel-strong pointer-events-auto flex max-h-[86vh] w-full max-w-[720px] flex-col overflow-hidden rounded-xl border border-cyber-border/80"
            >
              {/* Header */}
              <div className="flex items-start justify-between gap-3 border-b border-cyber-border/60 px-5 py-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-data text-[13px] font-semibold text-slate-50">
                      {record.id}
                    </span>
                    <SeverityBadge level={record.severity} size="sm" />
                    <CategoryChip category={record.category} size="sm" verbose />
                    <span
                      className={clsx(
                        "flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-data text-[10px] tracking-wide uppercase",
                        INV_STATUS_META[record.status].chip,
                      )}
                    >
                      <span
                        className={clsx(
                          "h-1 w-1 rounded-full",
                          INV_STATUS_META[record.status].dot,
                          INV_STATUS_META[record.status].pulse && "animate-pulse",
                        )}
                        aria-hidden="true"
                      />
                      {INV_STATUS_META[record.status].label}
                    </span>
                  </div>
                  <h2 className="mt-2 text-[15.5px] font-semibold tracking-tight text-slate-50">
                    {record.title}
                  </h2>
                  <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 font-data text-[10.5px] text-cyber-muted">
                    <Users className="h-3 w-3" aria-hidden="true" />
                    {record.analyst} · {record.team}
                    <span className="text-cyber-muted/60">·</span>
                    opened {formatDateTimeUTC(record.createdAt)}
                    <span className="text-cyber-muted/60">·</span>
                    updated {formatDateTimeUTC(record.updatedAt)}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  aria-label="Close investigation details"
                  className="rounded-lg border border-cyber-border/70 bg-cyber-surface/60 p-2 text-cyber-muted hover:border-cyber-accent/30 hover:text-slate-100"
                >
                  <X className="h-4 w-4" strokeWidth={2} aria-hidden="true" />
                </button>
              </div>

              {/* Body */}
              <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-5">
                {/* Gauges */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="glass-inset flex items-center justify-center rounded-lg py-4">
                    <MetricGauge
                      value={record.riskScore}
                      label="Risk Score"
                      sublabel="0 - 100"
                      color={SEVERITY_HEX[record.severity]}
                      size={118}
                      strokeWidth={9}
                      decimals={0}
                    />
                  </div>
                  <div className="glass-inset flex items-center justify-center rounded-lg py-4">
                    <MetricGauge
                      value={record.confidence * 100}
                      label="ML Confidence"
                      sublabel="classifier"
                      color="#22d3ee"
                      size={118}
                      strokeWidth={9}
                    />
                  </div>
                </div>

                {/* Summary */}
                <section aria-label="Case summary">
                  <ModalHeading icon={FileSearch} title="Summary" />
                  <p className="mt-2.5 text-[12.5px] leading-relaxed text-slate-200">
                    {record.summary}
                  </p>
                </section>

                {/* Findings timeline */}
                <section aria-label="Findings">
                  <ModalHeading icon={ClipboardList} title="Findings" hint={`${record.findings.length} entries`} />
                  <ol className="relative mt-3 space-y-4 border-l border-cyber-border/70 pl-4">
                    {record.findings.map((finding, index) => (
                      <motion.li
                        key={`${finding.time}-${index}`}
                        initial={{ opacity: 0, x: 8 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.08 + index * 0.06, duration: 0.3 }}
                        className="relative"
                      >
                        <span
                          className="absolute -left-[21.5px] top-1 h-2 w-2 rounded-full border-2 border-cyber-surface"
                          style={{
                            backgroundColor: index === 0 ? "#22d3ee" : "#1e2f4e",
                          }}
                          aria-hidden="true"
                        />
                        <p className="text-[12px] leading-snug text-slate-200">{finding.note}</p>
                        <p className="mt-0.5 font-data text-[10px] tabular text-cyber-muted">
                          {formatDateTimeUTC(finding.time)} UTC
                        </p>
                      </motion.li>
                    ))}
                  </ol>
                </section>

                {/* Related alerts */}
                <section aria-label="Related alerts">
                  <ModalHeading icon={Link2} title="Related Alerts" hint={`${record.relatedAlerts} linked`} />
                  <ul className="mt-3 space-y-2">
                    {relatedAlerts.map((event) => (
                      <li
                        key={event.id}
                        className="glass-inset flex items-center justify-between gap-3 rounded-lg px-3 py-2.5"
                      >
                        <span className="flex min-w-0 items-center gap-2.5">
                          <span
                            className="h-1.5 w-1.5 shrink-0 rounded-full"
                            style={{ backgroundColor: SEVERITY_HEX[event.severity] }}
                            aria-hidden="true"
                          />
                          <span className="truncate font-data text-[11.5px] text-slate-200">
                            {event.id}
                          </span>
                          <span className="hidden truncate font-data text-[10.5px] text-cyber-muted sm:inline">
                            {event.attackType}
                          </span>
                          <StatusChip status={event.status} size="sm" />
                        </span>
                        <span className="flex shrink-0 items-center gap-3">
                          <span className="font-data text-[10.5px] tabular text-slate-300">
                            {(event.confidence * 100).toFixed(1)}%
                          </span>
                          <span className="font-data text-[10px] tabular text-cyber-muted">
                            {formatClockUTC(event.timestamp)}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              </div>

              {/* Footer */}
              <div className="flex flex-wrap items-center gap-2 border-t border-cyber-border/60 px-5 py-4">
                <button
                  type="button"
                  title="Mock action - wires to the case API later"
                  className="flex items-center justify-center gap-2 rounded-lg border border-cyber-accent/35 bg-cyber-accent/10 px-3 py-2 text-[12px] font-medium text-cyber-accent-bright hover:bg-cyber-accent/20"
                >
                  <UserPlus className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                  Reassign
                </button>
                <button
                  type="button"
                  title="Mock action - wires to the case API later"
                  className="flex items-center justify-center gap-2 rounded-lg border border-severity-low/30 bg-severity-low/10 px-3 py-2 text-[12px] font-medium text-emerald-300 hover:bg-severity-low/20"
                >
                  <ShieldCheck className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                  Close case
                </button>
                <button
                  type="button"
                  title="Mock action - wires to the case API later"
                  className="ml-auto flex items-center justify-center gap-2 rounded-lg border border-cyber-border/70 bg-cyber-surface/60 px-3 py-2 text-[12px] font-medium text-cyber-muted hover:border-cyber-accent/30 hover:text-slate-100"
                >
                  <Download className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                  Export report
                </button>
              </div>
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  );
}

/* -------------------------------------------------------------------------- */
/*  Local building blocks                                                      */
/* -------------------------------------------------------------------------- */

function StatTile({
  icon: Icon,
  label,
  value,
  accent,
}: {
  icon: typeof FolderOpen;
  label: string;
  value: number;
  accent: string;
}) {
  return (
    <GlassCard hover className="flex items-center gap-4">
      <span
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border"
        style={{ borderColor: `${accent}40`, backgroundColor: `${accent}14` }}
      >
        <Icon className="h-4 w-4" style={{ color: accent }} strokeWidth={1.9} aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <p className="truncate font-data text-[10px] tracking-[0.16em] text-cyber-muted uppercase">
          {label}
        </p>
        <AnimatedCounter
          value={value}
          duration={1.1}
          className="mt-1 block text-[22px] font-semibold leading-none text-slate-50"
        />
      </div>
    </GlassCard>
  );
}

function ModalHeading({
  icon: Icon,
  title,
  hint,
}: {
  icon: typeof FileSearch;
  title: string;
  hint?: string;
}) {
  return (
    <h3 className="flex items-center gap-2 font-data text-[10.5px] tracking-[0.2em] text-cyber-muted uppercase">
      <Icon className="h-3.5 w-3.5 text-cyber-accent" strokeWidth={1.9} aria-hidden="true" />
      {title}
      {hint && (
        <span className="text-[10px] tracking-[0.05em] text-cyber-muted/70 normal-case">
          · {hint}
        </span>
      )}
    </h3>
  );
}

function initials(name: string): string {
  return name
    .split(" ")
    .map((part) => part.charAt(0))
    .join("")
    .slice(0, 2)
    .toUpperCase();
}
