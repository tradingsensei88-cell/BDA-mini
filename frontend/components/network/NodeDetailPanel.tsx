"use client";

import { useMemo } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  Cloud,
  Database,
  Globe,
  HardDrive,
  Laptop,
  Router,
  Server,
  Shield,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import AnimatedCounter from "@/components/ui/AnimatedCounter";
import SeverityBadge from "@/components/ui/SeverityBadge";
import Sparkline from "./Sparkline";
import type { NetworkNode, NodeType } from "@/types/network";
import {
  RISK_COLORS,
  RISK_LABELS,
  getNodeAlerts,
  getTrafficTrend,
  riskToSeverity,
} from "@/lib/network-data";

export interface NodeDetailPanelProps {
  node: NetworkNode;
  onClose: () => void;
}

/** Icon per asset archetype, mirroring the 3D geometry family. */
const TYPE_ICONS: Record<NodeType, LucideIcon> = {
  server: Server,
  endpoint: Laptop,
  router: Router,
  gateway: Globe,
  database: Database,
  cloud: Cloud,
  firewall: Shield,
};

/**
 * Glass detail panel for the selected asset: headline metrics, a risk score
 * bar, a traffic-trend sparkline, and its recent triaged alerts. Slides in
 * from the right edge of the 3D viewport.
 */
export default function NodeDetailPanel({ node, onClose }: NodeDetailPanelProps) {
  const alerts = useMemo(() => getNodeAlerts(node.id), [node.id]);
  const trend = useMemo(() => getTrafficTrend(node), [node]);

  const riskColor = RISK_COLORS[node.riskLevel];
  const Icon = TYPE_ICONS[node.type];

  return (
    <motion.aside
      initial={{ opacity: 0, x: 32 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 32 }}
      transition={{ type: "spring", stiffness: 340, damping: 34 }}
      aria-label={`${node.name} details`}
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
          <Icon
            className="h-5 w-5"
            strokeWidth={1.9}
            style={{ color: riskColor }}
            aria-hidden="true"
          />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[15px] font-semibold tracking-tight text-slate-50">
            {node.name}
          </h2>
          <p className="mt-0.5 font-data text-[10px] tracking-[0.16em] text-cyber-muted uppercase">
            {node.type} · {node.id}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close node details"
          className="rounded-md border border-cyber-border/70 bg-cyber-surface/60 p-1.5 text-cyber-muted hover:border-cyber-accent/40 hover:text-slate-100"
        >
          <X className="h-3.5 w-3.5" strokeWidth={2} />
        </button>
      </header>

      {/* Risk banner */}
      <div className="mt-3 flex items-center justify-between rounded-lg border border-cyber-border/70 bg-cyber-bg/40 px-3 py-2">
        <SeverityBadge
          level={riskToSeverity(node.riskLevel)}
          label={RISK_LABELS[node.riskLevel]}
          size="sm"
        />
        <span className="font-data text-[11px] text-cyber-muted">
          risk score{" "}
          <span className="font-semibold" style={{ color: riskColor }}>
            {node.riskScore}
          </span>
          <span className="text-cyber-muted/70">/100</span>
        </span>
      </div>

      {/* Metric tiles */}
      <div className="mt-3 grid grid-cols-2 gap-2">
        <MetricTile
          icon={Activity}
          label="Traffic volume"
          value={
            <AnimatedCounter
              value={node.trafficVolume}
              className="text-[15px] font-semibold text-slate-100"
            />
          }
        />
        <MetricTile
          icon={Icon}
          label="Connections"
          value={
            <AnimatedCounter
              value={node.connections.length}
              className="text-[15px] font-semibold text-slate-100"
            />
          }
        />
        <MetricTile
          icon={HardDrive}
          label="Open alerts"
          value={
            <AnimatedCounter
              value={node.alerts}
              className="text-[15px] font-semibold"
            />
          }
          valueClassName={node.alerts > 0 ? "text-severity-high" : "text-slate-100"}
        />
        <MetricTile
          icon={Shield}
          label="Exposure"
          value={
            <AnimatedCounter
              value={Math.max(0, 100 - node.riskScore)}
              className="text-[15px] font-semibold text-emerald-300"
            />
          }
        />
      </div>

      {/* Risk score bar */}
      <div className="mt-4">
        <div className="flex items-center justify-between">
          <p className="font-data text-[10px] tracking-[0.18em] text-cyber-muted uppercase">
            Risk score
          </p>
          <span className="font-data text-[10px] text-cyber-muted">
            {node.riskScore}%
          </span>
        </div>
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-cyber-border/60">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${node.riskScore}%` }}
            transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
            className="h-full rounded-full"
            style={{
              background: `linear-gradient(90deg, ${riskColor}66, ${riskColor})`,
              boxShadow: `0 0 12px -2px ${riskColor}`,
            }}
          />
        </div>
      </div>

      {/* Traffic trend */}
      <div className="mt-4">
        <div className="flex items-center justify-between">
          <p className="font-data text-[10px] tracking-[0.18em] text-cyber-muted uppercase">
            Traffic trend · 60 min
          </p>
          <span className="font-data text-[10px] text-cyber-muted">
            {Math.round(trend[trend.length - 1] ?? 0).toLocaleString("en-US")} obs
          </span>
        </div>
        <div className="glass-inset mt-1.5 rounded-lg px-1 pt-2 pb-1">
          <Sparkline data={trend} color={riskColor} id={node.id} className="h-14" />
        </div>
      </div>

      {/* Recent alerts */}
      <div className="mt-4">
        <p className="font-data text-[10px] tracking-[0.18em] text-cyber-muted uppercase">
          Recent alerts
        </p>
        <ul className="mt-2 space-y-1.5">
          {alerts.map((alert) => (
            <li
              key={alert.id}
              className="rounded-lg border border-cyber-border/60 bg-cyber-surface/40 px-2.5 py-2 hover:border-cyber-accent/25"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-[11px] leading-snug text-slate-200">
                  {alert.title}
                </p>
                <SeverityBadge
                  level={alert.severity}
                  size="sm"
                  className="shrink-0"
                />
              </div>
              <p className="mt-1 font-data text-[9px] tracking-wide text-cyber-muted">
                {alert.timestamp} · {alert.source}
              </p>
            </li>
          ))}
        </ul>
      </div>

      {/* Footer */}
      <footer className="mt-4 flex items-center justify-between border-t border-cyber-border/60 pt-2.5">
        <span className="font-data text-[9px] tracking-[0.16em] text-cyber-muted/80 uppercase">
          node {node.id}
        </span>
        <span className="inline-flex items-center gap-1.5 font-data text-[9px] text-emerald-300">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.9)]" />
          telemetry live
        </span>
      </footer>
    </motion.aside>
  );
}

/* -------------------------------------------------------------------------- */

interface MetricTileProps {
  icon: LucideIcon;
  label: string;
  value: React.ReactNode;
  valueClassName?: string;
}

function MetricTile({ icon: Icon, label, value, valueClassName }: MetricTileProps) {
  return (
    <div className="glass-inset rounded-lg px-2.5 py-2">
      <p className="flex items-center gap-1.5 font-data text-[9px] tracking-[0.14em] text-cyber-muted uppercase">
        <Icon className="h-3 w-3 text-cyber-muted" strokeWidth={2} aria-hidden="true" />
        {label}
      </p>
      <div className={valueClassName}>{value}</div>
    </div>
  );
}
