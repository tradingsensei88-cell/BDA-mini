"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import clsx from "clsx";
import { ChevronsLeft, ChevronsRight, ShieldCheck, X } from "lucide-react";
import { NAV_ITEMS } from "@/lib/navigation";

export const SIDEBAR_WIDTH = 280;
export const SIDEBAR_COLLAPSED_WIDTH = 72;

export interface SidebarProps {
  /** Desktop collapse state (ignored when `isMobile`). */
  collapsed?: boolean;
  onToggle?: () => void;
  /** Rendered inside the mobile drawer - always expanded, toggle closes it. */
  isMobile?: boolean;
  /** Fired after a nav link is clicked (used to close the mobile drawer). */
  onNavigate?: () => void;
  className?: string;
}

/**
 * Primary SOC navigation rail.
 * Desktop: animates between 280px (expanded) and 72px (icon-only) via Framer Motion.
 * Mobile: rendered expanded inside a drawer owned by MainLayout.
 */
export default function Sidebar({
  collapsed = false,
  onToggle,
  isMobile = false,
  onNavigate,
  className,
}: SidebarProps) {
  const pathname = usePathname();
  const isCollapsed = isMobile ? false : collapsed;

  return (
    <motion.aside
      initial={false}
      animate={{ width: isMobile ? SIDEBAR_WIDTH : isCollapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_WIDTH }}
      transition={{ type: "spring", stiffness: 300, damping: 32 }}
      className={clsx(
        "glass-panel-strong relative z-30 flex h-full shrink-0 flex-col border-y-0 border-l-0 border-r",
        className,
      )}
      aria-label="Primary navigation"
    >
      {/* Section label */}
      <div
        className={clsx(
          "flex h-14 shrink-0 items-center border-b border-cyber-border/60 px-4",
          isCollapsed ? "justify-center" : "justify-between",
        )}
      >
        <AnimatePresence initial={false} mode="wait">
          {isCollapsed ? (
            <motion.span
              key="collapsed-label"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="font-data text-[10px] tracking-[0.2em] text-cyber-muted"
            >
              NAV
            </motion.span>
          ) : (
            <motion.div
              key="expanded-label"
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -6 }}
              transition={{ duration: 0.18 }}
              className="flex items-center gap-2"
            >
              <span className="font-data text-[10px] tracking-[0.24em] text-cyber-muted uppercase">
                Operations
              </span>
              <span className="h-px flex-1 bg-gradient-to-r from-cyber-border to-transparent" />
            </motion.div>
          )}
        </AnimatePresence>
        {isMobile && (
          <button
            type="button"
            onClick={onToggle}
            aria-label="Close navigation"
            className="rounded-md p-1.5 text-cyber-muted hover:bg-cyber-overlay hover:text-slate-100"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Navigation items */}
      <nav className="flex-1 overflow-y-auto overflow-x-hidden px-3 py-3">
        <ul className="space-y-1">
          {NAV_ITEMS.map((item) => {
            const isActive =
              pathname === item.href || pathname.startsWith(`${item.href}/`);
            const Icon = item.icon;

            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  onClick={onNavigate}
                  title={isCollapsed ? item.name : undefined}
                  aria-current={isActive ? "page" : undefined}
                  className={clsx(
                    "group relative flex items-center rounded-lg outline-none",
                    isCollapsed
                      ? "justify-center px-0 py-2.5"
                      : "gap-3 px-3 py-2.5",
                    isActive
                      ? "bg-cyber-accent/10 text-cyber-accent-bright"
                      : "text-cyber-muted hover:bg-cyber-overlay/70 hover:text-slate-100",
                  )}
                >
                  {/* Active rail indicator */}
                  {isActive && (
                    <motion.span
                      layoutId={`sidebar-active-rail-${isMobile ? "mobile" : "desktop"}`}
                      transition={{ type: "spring", stiffness: 400, damping: 34 }}
                      className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-cyber-accent shadow-[0_0_10px_rgba(34,211,238,0.8)]"
                    />
                  )}

                  <Icon
                    className={clsx(
                      "h-[18px] w-[18px] shrink-0 transition-colors",
                      isActive
                        ? "text-cyber-accent drop-shadow-[0_0_6px_rgba(34,211,238,0.55)]"
                        : "text-cyber-muted group-hover:text-slate-200",
                    )}
                    strokeWidth={1.9}
                    aria-hidden="true"
                  />

                  <AnimatePresence initial={false}>
                    {!isCollapsed && (
                      <motion.span
                        initial={{ opacity: 0, x: -4 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: -4 }}
                        transition={{ duration: 0.16 }}
                        className="flex min-w-0 flex-1 items-center justify-between gap-2"
                      >
                        <span className="truncate text-[13px] font-medium tracking-tight">
                          {item.name}
                        </span>
                        {typeof item.badge === "number" && item.badge > 0 && (
                          <span
                            className={clsx(
                              "rounded-full px-1.5 py-0.5 font-data text-[10px] leading-none font-semibold",
                              isActive
                                ? "bg-cyber-accent/20 text-cyber-accent-bright"
                                : "bg-severity-critical/15 text-severity-critical",
                            )}
                          >
                            {item.badge}
                          </span>
                        )}
                      </motion.span>
                    )}
                  </AnimatePresence>

                  {/* Collapsed badge dot */}
                  {isCollapsed &&
                    typeof item.badge === "number" &&
                    item.badge > 0 && (
                      <span className="absolute right-2.5 top-2 h-1.5 w-1.5 rounded-full bg-severity-critical shadow-[0_0_8px_rgba(255,59,92,0.9)]" />
                    )}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Bottom section: threat level + collapse toggle */}
      <div className="shrink-0 border-t border-cyber-border/60 p-3">
        <AnimatePresence initial={false}>
          {!isCollapsed && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.18 }}
              className="overflow-hidden"
            >
              <div className="glass-inset mb-3 rounded-lg px-3 py-2.5">
                <div className="flex items-center justify-between">
                  <span className="font-data text-[10px] tracking-[0.18em] text-cyber-muted uppercase">
                    Threat Level
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="relative flex h-1.5 w-1.5">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-severity-medium opacity-70" />
                      <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-severity-medium" />
                    </span>
                    <span className="font-data text-[11px] font-semibold tracking-wide text-severity-medium">
                      ELEVATED
                    </span>
                  </span>
                </div>
                <div className="mt-2 flex gap-1" aria-hidden="true">
                  {[0, 1, 2, 3, 4].map((segment) => (
                    <span
                      key={segment}
                      className={clsx(
                        "h-1 flex-1 rounded-full",
                        segment < 3 ? "bg-severity-medium/80" : "bg-cyber-border",
                      )}
                    />
                  ))}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <button
          type="button"
          onClick={onToggle}
          aria-label={isMobile ? "Close navigation" : isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          className={clsx(
            "flex w-full items-center rounded-lg text-cyber-muted hover:bg-cyber-overlay/70 hover:text-cyber-accent-bright",
            isCollapsed ? "justify-center py-2.5" : "gap-3 px-3 py-2.5",
          )}
        >
          {isMobile ? (
            <X className="h-[18px] w-[18px]" strokeWidth={1.9} />
          ) : isCollapsed ? (
            <ChevronsRight className="h-[18px] w-[18px]" strokeWidth={1.9} />
          ) : (
            <ChevronsLeft className="h-[18px] w-[18px]" strokeWidth={1.9} />
          )}
          {!isCollapsed && (
            <span className="text-[13px] font-medium">
              {isMobile ? "Close" : "Collapse"}
            </span>
          )}
        </button>

        {!isCollapsed && (
          <p className="mt-2 flex items-center justify-center gap-1.5 font-data text-[10px] text-cyber-muted/70">
            <ShieldCheck className="h-3 w-3" aria-hidden="true" />
            v0.1.0 · shell build
          </p>
        )}
      </div>
    </motion.aside>
  );
}
