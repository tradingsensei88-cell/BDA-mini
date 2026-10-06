"use client";

import { motion } from "framer-motion";
import {
  Bell,
  ChevronDown,
  Menu,
  Search,
  ShieldCheck,
} from "lucide-react";
import StatusIndicator from "@/components/ui/StatusIndicator";

export interface HeaderProps {
  /** Opens the mobile navigation drawer. */
  onOpenMobileNav: () => void;
}

/** Mock platform health until the /health API is wired in a later task. */
const SYSTEM_HEALTH = {
  status: "online" as const,
  label: "Healthy",
};

const NOTIFICATION_COUNT = 7;

/**
 * Top command bar: branding, live feed indicator, global search,
 * system health, notifications, and the operator avatar.
 */
export default function Header({ onOpenMobileNav }: HeaderProps) {
  return (
    <header className="glass-panel-strong relative z-20 flex h-16 shrink-0 items-center gap-3 border-x-0 border-t-0 border-b border-cyber-border/80 px-4 lg:gap-5 lg:px-6">
      {/* Mobile: open navigation */}
      <button
        type="button"
        onClick={onOpenMobileNav}
        aria-label="Open navigation"
        className="rounded-lg p-2 text-cyber-muted hover:bg-cyber-overlay/70 hover:text-slate-100 md:hidden"
      >
        <Menu className="h-5 w-5" strokeWidth={1.9} />
      </button>

      {/* Brand */}
      <div className="flex items-center gap-3">
        <div className="glow-ring relative flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-gradient-to-br from-cyber-accent/25 via-cyber-surface to-cyber-elevated">
          <ShieldCheck
            className="h-[18px] w-[18px] text-cyber-accent-bright"
            strokeWidth={2}
            aria-hidden="true"
          />
          <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border-2 border-cyber-bg bg-emerald-400" />
        </div>
        <div className="hidden min-w-0 sm:block">
          <p className="text-glow-soft truncate text-[15px] font-bold tracking-tight text-slate-50">
            CyberShield <span className="text-cyber-accent">AI</span>
          </p>
          <p className="font-data truncate text-[9px] tracking-[0.28em] text-cyber-muted uppercase">
            Security Operations Center
          </p>
        </div>
      </div>

      {/* Live indicator */}
      <div className="hidden items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-400/[0.07] px-3 py-1.5 lg:flex">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-70" style={{ animationDuration: "2.4s" }} />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.9)]" />
        </span>
        <span className="font-data text-[10px] font-semibold tracking-[0.2em] text-emerald-300">
          LIVE
        </span>
      </div>

      {/* Global search */}
      <div className="min-w-0 flex-1 lg:mx-2 lg:max-w-xl">
        <label className="group relative block">
          <span className="sr-only">Search threats, alerts, events</span>
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-cyber-muted transition-colors group-focus-within:text-cyber-accent"
            strokeWidth={1.9}
            aria-hidden="true"
          />
          <input
            type="search"
            placeholder="Search threats, alerts, events..."
            className="glass-inset h-10 w-full rounded-lg pl-9 pr-14 text-[13px] text-slate-100 placeholder:text-cyber-muted/80 focus:border-cyber-accent/40 focus:outline-none focus:ring-1 focus:ring-cyber-accent/30"
          />
          <kbd className="pointer-events-none absolute right-2.5 top-1/2 hidden -translate-y-1/2 rounded border border-cyber-border bg-cyber-overlay/60 px-1.5 py-0.5 font-data text-[10px] text-cyber-muted sm:block">
            ⌘K
          </kbd>
        </label>
      </div>

      {/* Right cluster */}
      <div className="ml-auto flex items-center gap-2 lg:gap-3">
        {/* System health badge */}
        <div className="hidden items-center gap-2 rounded-lg border border-cyber-border/80 bg-cyber-surface/50 px-3 py-2 md:flex">
          <StatusIndicator status={SYSTEM_HEALTH.status} size="sm" />
          <span className="font-data text-[11px] tracking-wide text-emerald-300">
            {SYSTEM_HEALTH.label}
          </span>
        </div>

        {/* Notifications */}
        <motion.button
          type="button"
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          aria-label={`Notifications (${NOTIFICATION_COUNT} unread)`}
          className="relative rounded-lg border border-cyber-border/70 bg-cyber-surface/50 p-2.5 text-cyber-muted hover:border-cyber-accent/30 hover:text-slate-100"
        >
          <Bell className="h-[18px] w-[18px]" strokeWidth={1.9} />
          <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-severity-critical px-1 font-data text-[9px] font-bold text-white shadow-[0_0_10px_rgba(255,59,92,0.7)]">
            {NOTIFICATION_COUNT}
          </span>
        </motion.button>

        {/* Operator avatar */}
        <motion.button
          type="button"
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          aria-label="Operator menu"
          className="flex items-center gap-2.5 rounded-lg border border-cyber-border/70 bg-cyber-surface/50 py-1.5 pl-1.5 pr-2.5 hover:border-cyber-accent/30"
        >
          <span className="relative flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-cyber-accent/70 to-cyber-teal/60 font-data text-[12px] font-bold text-cyber-bg">
            SO
          </span>
          <span className="hidden text-left lg:block">
            <span className="block text-[12px] font-semibold leading-tight text-slate-100">
              SOC Operator
            </span>
            <span className="block font-data text-[9px] tracking-[0.16em] text-cyber-muted uppercase">
              Tier 2 Analyst
            </span>
          </span>
          <ChevronDown
            className="hidden h-3.5 w-3.5 text-cyber-muted lg:block"
            strokeWidth={2}
            aria-hidden="true"
          />
        </motion.button>
      </div>
    </header>
  );
}
