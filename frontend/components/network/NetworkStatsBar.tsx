"use client";

import { useEffect, useState } from "react";
import { Activity, AlertTriangle, Network, Server, Zap } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import clsx from "clsx";
import AnimatedCounter from "@/components/ui/AnimatedCounter";
import type { NetworkStats } from "@/types/network";

export interface NetworkStatsBarProps {
  stats: NetworkStats;
  reducedMotion: boolean;
  className?: string;
}

/** Live ticker seed - mock platform throughput in events/second. */
const BASE_EVENTS_PER_SEC = 12480;

/**
 * Top overlay strip with the topology headline figures plus a simulated live
 * events/sec ticker that random-walks on an interval (frozen under reduced
 * motion).
 */
export default function NetworkStatsBar({
  stats,
  reducedMotion,
  className,
}: NetworkStatsBarProps) {
  const [eventsPerSecond, setEventsPerSecond] = useState(BASE_EVENTS_PER_SEC);

  useEffect(() => {
    if (reducedMotion) return;
    const interval = window.setInterval(() => {
      setEventsPerSecond((previous) => {
        const drift = (Math.random() - 0.48) * 900;
        return Math.round(
          Math.min(Math.max(previous + drift, 8600), 19600),
        );
      });
    }, 1800);
    return () => window.clearInterval(interval);
  }, [reducedMotion]);

  return (
    <div
      className={clsx(
        "glass-panel-strong pointer-events-auto flex items-stretch overflow-hidden rounded-xl border border-cyber-border/90 shadow-panel",
        className,
      )}
    >
      <StatCell icon={Server} label="Nodes" value={stats.totalNodes} />
      <StatCell icon={Network} label="Flows" value={stats.activeConnections} />
      <StatCell
        icon={AlertTriangle}
        label="Threats"
        value={stats.criticalThreats}
        tone="#f97316"
        className="hidden sm:flex"
      />
      <StatCell
        icon={Activity}
        label="Anomalies"
        value={stats.anomalies}
        tone="#eab308"
        className="hidden md:flex"
      />

      {/* Live throughput cell */}
      <div className="hidden items-center gap-2.5 border-l border-cyber-border/60 bg-cyber-bg/30 px-3 py-1.5 lg:flex">
        <Zap className="h-4 w-4 text-cyber-accent" strokeWidth={1.9} aria-hidden="true" />
        <div>
          <p className="flex items-center gap-1.5 font-data text-[9px] tracking-[0.18em] text-cyber-muted uppercase">
            <span className="relative flex h-1.5 w-1.5">
              {!reducedMotion && (
                <span
                  className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-70"
                  style={{ animationDuration: "2.2s" }}
                />
              )}
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
            </span>
            Events/sec
          </p>
          <AnimatedCounter
            value={eventsPerSecond}
            duration={0.9}
            className="text-[15px] leading-tight font-semibold text-cyber-accent-bright"
          />
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

interface StatCellProps {
  icon: LucideIcon;
  label: string;
  value: number;
  tone?: string;
  className?: string;
}

function StatCell({ icon: Icon, label, value, tone, className }: StatCellProps) {
  return (
    <div
      className={clsx(
        "flex min-w-[92px] items-center gap-2.5 border-r border-cyber-border/60 px-3 py-1.5 last:border-r-0",
        className,
      )}
    >
      <Icon
        className="h-4 w-4 shrink-0"
        strokeWidth={1.9}
        style={{ color: tone ?? "#22d3ee" }}
        aria-hidden="true"
      />
      <div>
        <p className="font-data text-[9px] tracking-[0.18em] text-cyber-muted uppercase">
          {label}
        </p>
        <span style={{ color: tone ?? "#e2e8f0" }}>
          <AnimatedCounter
            value={value}
            className="text-[15px] leading-tight font-semibold"
          />
        </span>
      </div>
    </div>
  );
}
