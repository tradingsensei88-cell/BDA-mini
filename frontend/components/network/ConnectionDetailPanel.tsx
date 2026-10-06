"use client";

import { useMemo } from "react";
import { motion } from "framer-motion";
import { ArrowDown, Crosshair, Radio, X } from "lucide-react";
import AnimatedCounter from "@/components/ui/AnimatedCounter";
import SeverityBadge from "@/components/ui/SeverityBadge";
import type { NetworkConnection } from "@/types/network";
import {
  RISK_ACCENTS,
  RISK_COLORS,
  RISK_LABELS,
  getConnectionTimestampHint,
  getNodeById,
  riskToSeverity,
} from "@/lib/network-data";

export interface ConnectionDetailPanelProps {
  connection: NetworkConnection;
  onClose: () => void;
}

/**
 * Glass detail panel for a selected flow: endpoints with an animated
 * connector, protocol/event metrics, and the model's prediction with a
 * confidence bar. Slides in from the right edge of the 3D viewport.
 */
export default function ConnectionDetailPanel({
  connection,
  onClose,
}: ConnectionDetailPanelProps) {
  const source = getNodeById(connection.source);
  const target = getNodeById(connection.target);

  const riskColor = RISK_COLORS[connection.riskLevel];
  const riskAccent = RISK_ACCENTS[connection.riskLevel];
  const lastObserved = useMemo(
    () => getConnectionTimestampHint(connection.id),
    [connection.id],
  );

  return (
    <motion.aside
      initial={{ opacity: 0, x: 32 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 32 }}
      transition={{ type: "spring", stiffness: 340, damping: 34 }}
      aria-label={`Flow ${connection.source} to ${connection.target} details`}
      className="glass-panel-strong pointer-events-auto absolute inset-x-3 bottom-28 top-auto z-30 max-h-[58%] overflow-y-auto rounded-xl border border-cyber-border/90 p-4 shadow-panel md:inset-x-auto md:bottom-24 md:right-4 md:top-4 md:w-[332px] md:max-h-none"
    >
      {/* Header */}
      <header className="flex items-start gap-3">
        <span
          className="hairline-top relative flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border"
          style={{
            borderColor: `${riskColor}55`,
            backgroundColor: `${riskColor}14`,
          }}
        >
          <Radio
            className="h-5 w-5"
            strokeWidth={1.9}
            style={{ color: riskColor }}
            aria-hidden="true"
          />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[15px] font-semibold tracking-tight text-slate-50">
            Flow Detail
          </h2>
          <p className="mt-0.5 font-data text-[10px] tracking-[0.16em] text-cyber-muted uppercase">
            {connection.id} · {lastObserved}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close flow details"
          className="rounded-md border border-cyber-border/70 bg-cyber-surface/60 p-1.5 text-cyber-muted hover:border-cyber-accent/40 hover:text-slate-100"
        >
          <X className="h-3.5 w-3.5" strokeWidth={2} />
        </button>
      </header>

      {/* Endpoints + animated connector */}
      <div className="mt-3 rounded-lg border border-cyber-border/70 bg-cyber-bg/40 p-3">
        <EndpointRow
          label="Source"
          name={source?.name ?? connection.source}
          id={connection.source}
        />
        <div className="relative my-1.5 flex h-6 items-center justify-center">
          <div className="absolute inset-x-0 top-1/2 -translate-y-1/2">
            <svg
              width="100%"
              height="2"
              viewBox="0 0 100 2"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <line
                x1="0"
                y1="1"
                x2="100"
                y2="1"
                stroke={riskAccent}
                strokeWidth="1.5"
                strokeOpacity="0.7"
                className="animate-data-flow"
                vectorEffect="non-scaling-stroke"
              />
            </svg>
          </div>
          <span
            className="relative z-10 flex h-5 w-5 items-center justify-center rounded-full border bg-cyber-elevated"
            style={{ borderColor: `${riskColor}66` }}
          >
            <ArrowDown
              className="h-3 w-3"
              strokeWidth={2.4}
              style={{ color: riskAccent }}
              aria-hidden="true"
            />
          </span>
        </div>
        <EndpointRow
          label="Destination"
          name={target?.name ?? connection.target}
          id={connection.target}
        />
      </div>

      {/* Risk + protocol strip */}
      <div className="mt-3 flex items-center justify-between rounded-lg border border-cyber-border/70 bg-cyber-bg/40 px-3 py-2">
        <SeverityBadge
          level={riskToSeverity(connection.riskLevel)}
          label={RISK_LABELS[connection.riskLevel]}
          size="sm"
        />
        <span className="rounded border border-cyber-border bg-cyber-overlay/60 px-1.5 py-0.5 font-data text-[10px] tracking-[0.14em] text-slate-300">
          {connection.protocol}
        </span>
      </div>

      {/* Metrics */}
      <div className="mt-3 grid grid-cols-2 gap-2">
        <div className="glass-inset rounded-lg px-2.5 py-2">
          <p className="font-data text-[9px] tracking-[0.14em] text-cyber-muted uppercase">
            Events observed
          </p>
          <AnimatedCounter
            value={connection.eventCount}
            className="text-[15px] font-semibold text-slate-100"
          />
        </div>
        <div className="glass-inset rounded-lg px-2.5 py-2">
          <p className="font-data text-[9px] tracking-[0.14em] text-cyber-muted uppercase">
            Alert severity
          </p>
          <p className="mt-0.5 text-[13px] font-semibold" style={{ color: riskColor }}>
            {RISK_LABELS[connection.riskLevel]}
          </p>
        </div>
      </div>

      {/* Model prediction */}
      <div className="mt-4">
        <p className="flex items-center gap-1.5 font-data text-[10px] tracking-[0.18em] text-cyber-muted uppercase">
          <Crosshair className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
          Model prediction
        </p>
        <p className="mt-1.5 text-[13px] font-medium text-slate-100">
          {connection.prediction}
        </p>
        <div className="mt-2 flex items-center justify-between">
          <span className="font-data text-[9px] tracking-[0.14em] text-cyber-muted uppercase">
            Confidence
          </span>
          <span className="font-data text-[11px] font-semibold" style={{ color: riskAccent }}>
            {connection.confidence}%
          </span>
        </div>
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-cyber-border/60">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${connection.confidence}%` }}
            transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
            className="h-full rounded-full"
            style={{
              background: `linear-gradient(90deg, ${riskColor}66, ${riskColor})`,
              boxShadow: `0 0 12px -2px ${riskColor}`,
            }}
          />
        </div>
      </div>

      {/* Meta */}
      <dl className="mt-4 space-y-1.5 border-t border-cyber-border/60 pt-3">
        <MetaRow label="Flow id" value={connection.id} />
        <MetaRow label="Direction" value={`${connection.source} → ${connection.target}`} />
        <MetaRow label="Last observed" value={lastObserved} />
      </dl>
    </motion.aside>
  );
}

/* -------------------------------------------------------------------------- */

interface EndpointRowProps {
  label: string;
  name: string;
  id: string;
}

function EndpointRow({ label, name, id }: EndpointRowProps) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <p className="font-data text-[9px] tracking-[0.16em] text-cyber-muted uppercase">
          {label}
        </p>
        <p className="truncate text-[12px] font-medium text-slate-100">{name}</p>
      </div>
      <span className="shrink-0 font-data text-[9px] text-cyber-muted/80">
        {id}
      </span>
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="font-data text-[9px] tracking-[0.14em] text-cyber-muted uppercase">
        {label}
      </dt>
      <dd className="truncate font-data text-[10px] text-slate-300">{value}</dd>
    </div>
  );
}
