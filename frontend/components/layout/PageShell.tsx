"use client";

import { motion } from "framer-motion";
import { Check, Construction } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import clsx from "clsx";
import GlassCard from "@/components/ui/GlassCard";

export interface PageShellProps {
  title: string;
  description: string;
  icon: LucideIcon;
  /** Module index used in the placeholder footer, e.g. "03 / 10". */
  moduleIndex?: string;
  /** Planned capabilities rendered as checklist chips in the placeholder. */
  capabilities?: string[];
  /** Custom body - falls back to the placeholder panel when omitted. */
  children?: ReactNode;
}

/**
 * Shared scaffold for every SOC route: animated page header with icon,
 * and (by default) an elegant "module not yet wired" placeholder panel.
 */
export default function PageShell({
  title,
  description,
  icon: Icon,
  moduleIndex,
  capabilities,
  children,
}: PageShellProps) {
  return (
    <div className="space-y-6">
      {/* Page header */}
      <motion.header
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
        className="flex flex-wrap items-start gap-4"
      >
        <div className="glow-ring relative flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-cyber-accent/25 bg-gradient-to-br from-cyber-accent/15 via-cyber-surface to-cyber-elevated">
          <Icon
            className="h-5 w-5 text-cyber-accent-bright"
            strokeWidth={1.9}
            aria-hidden="true"
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <h1 className="text-xl font-semibold tracking-tight text-slate-50 md:text-2xl">
              {title}
            </h1>
            {moduleIndex && (
              <span className="rounded border border-cyber-border bg-cyber-surface/60 px-1.5 py-0.5 font-data text-[10px] tracking-[0.14em] text-cyber-muted">
                MODULE {moduleIndex}
              </span>
            )}
          </div>
          <p className="mt-1 max-w-2xl text-[13px] leading-relaxed text-cyber-muted md:text-sm">
            {description}
          </p>
        </div>
      </motion.header>

      {/* Body */}
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.32, delay: 0.08, ease: [0.22, 1, 0.36, 1] }}
      >
        {children ?? (
          <PlaceholderPanel title={title} capabilities={capabilities} />
        )}
      </motion.div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

interface PlaceholderPanelProps {
  title: string;
  capabilities?: string[];
}

const DEFAULT_CAPABILITIES = [
  "Live data binding",
  "Real-time streaming updates",
  "Export & drill-down actions",
];

/**
 * The elegant "module initializing" state shown before this route is wired to
 * the streaming backend in later tasks.
 */
function PlaceholderPanel({ title, capabilities }: PlaceholderPanelProps) {
  const items = capabilities ?? DEFAULT_CAPABILITIES;

  return (
    <GlassCard className="hairline-top relative overflow-hidden p-0">
      {/* Sweeping scan line */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-cyber-accent/[0.07] to-transparent animate-scan-sweep"
        aria-hidden="true"
      />

      <div className="relative flex flex-col items-start gap-6 p-8 md:flex-row md:items-center md:justify-between md:p-10">
        <div className="max-w-lg space-y-3">
          <div className="inline-flex items-center gap-2 rounded-full border border-cyber-accent/20 bg-cyber-accent/[0.06] px-3 py-1">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyber-accent opacity-70" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-cyber-accent" />
            </span>
            <span className="font-data text-[10px] font-semibold tracking-[0.2em] text-cyber-accent-bright uppercase">
              Module initializing
            </span>
          </div>
          <h2 className="text-lg font-semibold tracking-tight text-slate-100">
            {title} data plane coming online
          </h2>
          <p className="text-[13px] leading-relaxed text-cyber-muted">
            The interface shell is in place. This view will stream live telemetry
            from the Kafka ingestion pipeline and Spark detection jobs once the
            backend services are deployed.
          </p>
          <p className="font-data text-[11px] text-cyber-muted/80">
            waiting for upstream feed
            <span className="animate-caret-blink text-cyber-accent">▊</span>
          </p>
        </div>

        <div className="w-full shrink-0 md:w-auto md:min-w-[280px]">
          <div className="glass-inset rounded-lg p-4">
            <p className="mb-3 flex items-center gap-2 font-data text-[10px] tracking-[0.2em] text-cyber-muted uppercase">
              <Construction className="h-3.5 w-3.5 text-cyber-accent" aria-hidden="true" />
              Planned capabilities
            </p>
            <ul className="space-y-2.5">
              {items.map((item, index) => (
                <motion.li
                  key={item}
                  initial={{ opacity: 0, x: 8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.15 + index * 0.07, duration: 0.3 }}
                  className="flex items-start gap-2.5 text-[12px] text-slate-300"
                >
                  <span
                    className={clsx(
                      "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                      "border-cyber-accent/30 bg-cyber-accent/10",
                    )}
                  >
                    <Check className="h-2.5 w-2.5 text-cyber-accent" strokeWidth={3} aria-hidden="true" />
                  </span>
                  {item}
                </motion.li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </GlassCard>
  );
}
