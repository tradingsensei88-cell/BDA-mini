"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import clsx from "clsx";
import type { ThreatEvent } from "@/types";
import SeverityBadge from "@/components/ui/SeverityBadge";
import CategoryChip from "@/components/ui/CategoryChip";
import { formatAgo, formatClockUTC } from "@/lib/format";

export interface ThreatFeedProps {
  /** Pool of events rendered initially and recycled by the live simulation. */
  events: ThreatEvent[];
  /** Maximum number of rows kept in the visible list. */
  maxItems?: number;
  /** Simulates live arrivals by rotating the pool every few seconds. */
  live?: boolean;
  onSelect?: (event: ThreatEvent) => void;
  className?: string;
}

/**
 * Live threat feed: newest detections slide in from the top with Framer
 * Motion, relative timestamps tick every 10s, and (when `live`) fresh events
 * keep arriving on a simulated socket cadence.
 */
export default function ThreatFeed({
  events,
  maxItems = 14,
  live = true,
  onSelect,
  className,
}: ThreatFeedProps) {
  const [items, setItems] = useState<ThreatEvent[]>(() => events.slice(0, maxItems));
  const [now, setNow] = useState<number | null>(null);
  const cursor = useRef(maxItems);

  /* Relative-time ticker (client-only so SSR output stays deterministic). */
  useEffect(() => {
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 10_000);
    return () => window.clearInterval(timer);
  }, []);

  /* Simulated live arrivals. */
  useEffect(() => {
    if (!live || events.length === 0) return;
    const timer = window.setInterval(() => {
      const template = events[cursor.current % events.length];
      cursor.current += 1;
      const fresh: ThreatEvent = {
        ...template,
        id: `${template.id}-live-${cursor.current}`,
        timestamp: new Date().toISOString(),
      };
      setItems((prev) => [fresh, ...prev].slice(0, maxItems));
    }, 3800);
    return () => window.clearInterval(timer);
  }, [live, events, maxItems]);

  return (
    <div className={clsx("flex min-h-0 flex-col", className)}>
      {/* Panel header */}
      <div className="flex items-center justify-between gap-3 border-b border-cyber-border/60 px-5 py-4">
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-2 w-2">
            <span
              className="absolute inline-flex h-full w-full animate-ping rounded-full bg-severity-critical opacity-60"
              style={{ animationDuration: "2.2s" }}
              aria-hidden="true"
            />
            <span
              className="relative inline-flex h-2 w-2 rounded-full bg-severity-critical shadow-[0_0_10px_rgba(255,59,92,0.9)]"
              aria-hidden="true"
            />
          </span>
          <h2 className="font-data text-[11px] tracking-[0.22em] text-cyber-muted uppercase">
            Live Threat Feed
          </h2>
        </div>
        <span className="rounded border border-cyber-border/80 bg-cyber-surface/60 px-2 py-0.5 font-data text-[10px] tabular text-cyber-muted">
          {items.length} events · 24h
        </span>
      </div>

      {/* Scrolling list */}
      <div className="relative min-h-0 flex-1">
        <ul className="h-full space-y-1 overflow-y-auto p-3 pr-2">
          <AnimatePresence initial={false}>
            {items.map((event) => {
              const isFresh = event.id.includes("-live-");
              return (
                <motion.li
                  key={event.id}
                  layout
                  initial={{ opacity: 0, y: -18, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, height: 0, marginTop: 0 }}
                  transition={{ type: "spring", stiffness: 420, damping: 34 }}
                >
                  <button
                    type="button"
                    onClick={() => onSelect?.(event)}
                    className={clsx(
                      "group w-full rounded-lg border border-transparent px-2.5 py-2 text-left",
                      "hover:border-cyber-border/70 hover:bg-cyber-overlay/50 focus-visible:border-cyber-accent/40",
                      onSelect && "cursor-pointer",
                    )}
                  >
                    <div className="flex items-start gap-2.5">
                      <SeverityBadge level={event.severity} size="sm" className="mt-0.5 shrink-0" />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate font-data text-[12px] font-medium text-slate-100">
                            {event.attackType}
                          </span>
                          <CategoryChip category={event.category} size="sm" showDot={false} />
                          {isFresh && (
                            <span className="flex items-center gap-1 font-data text-[9px] font-semibold tracking-widest text-emerald-300 uppercase">
                              <span className="h-1 w-1 animate-pulse rounded-full bg-emerald-400" />
                              new
                            </span>
                          )}
                        </div>
                        <p className="mt-0.5 truncate font-data text-[10.5px] text-cyber-muted">
                          {event.source}
                          <span className="px-1 text-cyber-muted/60">→</span>
                          {event.destination}
                        </p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="font-data text-[11px] tabular text-slate-200">
                          {(event.confidence * 100).toFixed(1)}%
                        </p>
                        <p className="mt-0.5 font-data text-[9.5px] tabular text-cyber-muted">
                          {now === null ? formatClockUTC(event.timestamp) : formatAgo(event.timestamp, now)}
                        </p>
                      </div>
                    </div>
                  </button>
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ul>

        {/* Bottom fade hinting at more content */}
        <div
          className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-[#0b1424] to-transparent"
          aria-hidden="true"
        />
      </div>
    </div>
  );
}
