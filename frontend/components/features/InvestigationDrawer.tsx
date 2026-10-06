"use client";

import { useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  Brain,
  ClipboardList,
  Clock,
  Download,
  FileSearch,
  Gauge,
  Radio,
  ShieldCheck,
  Sparkles,
  UserPlus,
  X,
} from "lucide-react";
import type { ThreatEvent } from "@/types";
import SeverityBadge from "@/components/ui/SeverityBadge";
import CategoryChip from "@/components/ui/CategoryChip";
import StatusChip from "@/components/ui/StatusChip";
import MetricGauge from "@/components/charts/MetricGauge";
import { SEVERITY_HEX, THREAT_EVENTS } from "@/lib/mock-data";
import { formatBytes, formatClockUTC, formatDateTimeUTC } from "@/lib/format";

export interface InvestigationDrawerProps {
  /** The event under investigation (null closes the drawer). */
  event: ThreatEvent | null;
  /** Overrides the auto-derived related alerts. */
  relatedEvents?: ThreatEvent[];
  onClose: () => void;
}

/* Presentation-only feature weights for the "why flagged" bars. */
const FEATURE_WEIGHTS = [0.92, 0.83, 0.71, 0.58];

/**
 * Slide-in investigation panel opened from the threat table / feed rows.
 * Shows prediction details, gauges, contributing features, related alerts,
 * and a compact event timeline. Purely presentational for now.
 */
export default function InvestigationDrawer({
  event,
  relatedEvents,
  onClose,
}: InvestigationDrawerProps) {
  /* Escape closes the drawer. */
  useEffect(() => {
    if (!event) return;
    const onKeyDown = (keyEvent: KeyboardEvent) => {
      if (keyEvent.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [event, onClose]);

  const related = event
    ? (relatedEvents ??
      THREAT_EVENTS.filter((e) => e.category === event.category && e.id !== event.id).slice(0, 4))
    : [];

  const timeline = event
    ? (() => {
        const t = Date.parse(event.timestamp);
        return [
          { at: t - 4000, label: "Flow captured by sensor tap" },
          { at: t - 3000, label: "Feature vector assembled (41 features)" },
          {
            at: t - 2000,
            label: `ML classification: ${event.attackType} · confidence ${(event.confidence * 100).toFixed(1)}%`,
          },
          {
            at: t - 1000,
            label: `Risk scored ${event.riskScore}/100 · severity ${event.severity}`,
          },
          { at: t, label: "Alert raised · queued for triage" },
        ];
      })()
    : [];

  return (
    <AnimatePresence>
      {event && (
        <>
          <motion.div
            key="drawer-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            className="fixed inset-0 z-[55] bg-cyber-bg/70 backdrop-blur-sm"
            aria-hidden="true"
          />
          <motion.aside
            key="drawer-panel"
            role="dialog"
            aria-modal="true"
            aria-label={`Investigation for ${event.id}`}
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 340, damping: 34 }}
            className="glass-panel-strong fixed inset-y-0 right-0 z-[60] flex w-full max-w-[470px] flex-col overflow-hidden border-y-0 border-r-0 border-l border-cyber-border/80"
          >
            {/* Header */}
            <div className="flex items-start justify-between gap-3 border-b border-cyber-border/60 px-5 py-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-data text-[13px] font-semibold text-slate-50">
                    {event.id}
                  </span>
                  <SeverityBadge level={event.severity} size="sm" />
                  <StatusChip status={event.status} size="sm" />
                </div>
                <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-cyber-muted">
                  <span className="font-data text-slate-300">
                    {event.attackType}
                  </span>
                  <CategoryChip category={event.category} size="sm" verbose />
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close investigation panel"
                className="rounded-lg border border-cyber-border/70 bg-cyber-surface/60 p-2 text-cyber-muted hover:border-cyber-accent/30 hover:text-slate-100"
              >
                <X className="h-4 w-4" strokeWidth={2} />
              </button>
            </div>

            {/* Body */}
            <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-5">
              {/* Meta row */}
              <div className="glass-inset grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg p-4">
                <MetaItem
                  icon={Clock}
                  label="Detected"
                  value={formatDateTimeUTC(event.timestamp)}
                  hint="UTC"
                />
                <MetaItem
                  icon={Radio}
                  label="Protocol"
                  value={event.protocol}
                  hint={formatBytes(event.bytes)}
                />
                <MetaItem
                  icon={ArrowRight}
                  label="Source"
                  value={event.source}
                  hint={event.sourceIp}
                />
                <MetaItem
                  icon={ArrowRight}
                  label="Destination"
                  value={event.destination}
                  hint={event.destinationIp}
                />
              </div>

              {/* Gauges */}
              <section aria-label="Prediction confidence and risk">
                <DrawerHeading icon={Gauge} title="Prediction Summary" />
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <MetricGauge
                    value={event.confidence * 100}
                    label="Confidence"
                    sublabel="classifier"
                    color="#22d3ee"
                    size={128}
                    strokeWidth={9}
                  />
                  <MetricGauge
                    value={event.riskScore}
                    label="Risk Score"
                    sublabel="0 - 100"
                    color={SEVERITY_HEX[event.severity]}
                    size={128}
                    strokeWidth={9}
                  />
                </div>
              </section>

              {/* Why flagged */}
              <section aria-label="Why this event was flagged">
                <DrawerHeading icon={Sparkles} title="Why flagged?" />
                <ul className="mt-3 space-y-2.5">
                  {event.topFeatures.map((feature, index) => (
                    <li key={`${feature}-${index}`}>
                      <div className="flex items-center justify-between gap-3 text-[11.5px]">
                        <span className="flex items-center gap-2 text-slate-200">
                          <span className="h-1 w-1 rounded-full bg-cyber-accent" aria-hidden="true" />
                          {feature}
                        </span>
                        <span className="font-data text-[10.5px] tabular text-cyber-muted">
                          {Math.round((FEATURE_WEIGHTS[index] ?? 0.5) * 100)}%
                        </span>
                      </div>
                      <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-cyber-border/50">
                        <motion.div
                          initial={{ width: 0 }}
                          animate={{
                            width: `${(FEATURE_WEIGHTS[index] ?? 0.5) * 100}%`,
                          }}
                          transition={{
                            duration: 0.7,
                            delay: 0.15 + index * 0.08,
                            ease: [0.22, 1, 0.36, 1],
                          }}
                          className="h-full rounded-full bg-gradient-to-r from-cyber-accent/70 to-cyber-accent"
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              </section>

              {/* Related alerts */}
              <section aria-label="Related alerts">
                <DrawerHeading icon={ClipboardList} title="Related Alerts" hint={`${related.length} linked`} />
                <ul className="mt-3 space-y-2">
                  {related.map((item) => (
                    <li
                      key={item.id}
                      className="glass-inset flex items-center justify-between gap-3 rounded-lg px-3 py-2.5"
                    >
                      <span className="flex min-w-0 items-center gap-2.5">
                        <span
                          className="h-1.5 w-1.5 shrink-0 rounded-full"
                          style={{ backgroundColor: SEVERITY_HEX[item.severity] }}
                          aria-hidden="true"
                        />
                        <span className="truncate font-data text-[11.5px] text-slate-200">
                          {item.id}
                        </span>
                        <span className="hidden truncate font-data text-[10.5px] text-cyber-muted sm:inline">
                          {item.attackType}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-3">
                        <span className="font-data text-[10.5px] tabular text-slate-300">
                          {(item.confidence * 100).toFixed(1)}%
                        </span>
                        <span className="font-data text-[10px] tabular text-cyber-muted">
                          {formatClockUTC(item.timestamp)}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              </section>

              {/* Timeline */}
              <section aria-label="Event timeline">
                <DrawerHeading icon={FileSearch} title="Event Timeline" />
                <ol className="relative mt-3 space-y-4 border-l border-cyber-border/70 pl-4">
                  {timeline.map((step, index) => (
                    <motion.li
                      key={step.label}
                      initial={{ opacity: 0, x: 8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: index * 0.06, duration: 0.3 }}
                      className="relative"
                    >
                      <span
                        className="absolute -left-[21.5px] top-1 h-2 w-2 rounded-full border-2 border-cyber-surface"
                        style={{
                          backgroundColor:
                            index === timeline.length - 1 ? "#22d3ee" : "#1e2f4e",
                        }}
                        aria-hidden="true"
                      />
                      <p className="text-[12px] leading-snug text-slate-200">{step.label}</p>
                      <p className="mt-0.5 font-data text-[10px] tabular text-cyber-muted">
                        {formatClockUTC(new Date(step.at).toISOString())} UTC
                        <span className="px-1.5 text-cyber-muted/60">·</span>
                        {index === timeline.length - 1 ? "now" : `T-${(timeline.length - 1 - index) * 1}s`}
                      </p>
                    </motion.li>
                  ))}
                </ol>
              </section>
            </div>

            {/* Footer actions */}
            <div className="border-t border-cyber-border/60 px-5 py-4">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  title="Mock action - wires to the case API later"
                  className="flex flex-1 items-center justify-center gap-2 rounded-lg border border-cyber-accent/35 bg-cyber-accent/10 px-3 py-2 text-[12px] font-medium text-cyber-accent-bright hover:bg-cyber-accent/20"
                >
                  <UserPlus className="h-3.5 w-3.5" strokeWidth={2} />
                  Assign investigator
                </button>
                <button
                  type="button"
                  title="Mock action - wires to the case API later"
                  className="flex items-center justify-center gap-2 rounded-lg border border-severity-low/30 bg-severity-low/10 px-3 py-2 text-[12px] font-medium text-emerald-300 hover:bg-severity-low/20"
                >
                  <ShieldCheck className="h-3.5 w-3.5" strokeWidth={2} />
                  Resolve
                </button>
                <button
                  type="button"
                  title="Mock action - wires to the case API later"
                  aria-label="Export event as JSON"
                  className="rounded-lg border border-cyber-border/70 bg-cyber-surface/60 p-2 text-cyber-muted hover:border-cyber-accent/30 hover:text-slate-100"
                >
                  <Download className="h-3.5 w-3.5" strokeWidth={2} />
                </button>
              </div>
              <p className="mt-2.5 flex items-center gap-1.5 font-data text-[10px] text-cyber-muted/80">
                <Brain className="h-3 w-3" aria-hidden="true" />
                Scored by CyberShield RF v2.1.0 · pipeline latency 41 ms
              </p>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

/* -------------------------------------------------------------------------- */

function DrawerHeading({
  icon: Icon,
  title,
  hint,
}: {
  icon: typeof Gauge;
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

function MetaItem({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof Clock;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="min-w-0">
      <p className="flex items-center gap-1.5 font-data text-[9.5px] tracking-[0.18em] text-cyber-muted uppercase">
        <Icon className="h-3 w-3" aria-hidden="true" />
        {label}
      </p>
      <p className="mt-1 truncate font-data text-[12px] text-slate-100">{value}</p>
      {hint && <p className="truncate font-data text-[10px] text-cyber-muted">{hint}</p>}
    </div>
  );
}
