"use client";

import { motion } from "framer-motion";
import {
  Maximize2,
  Minimize2,
  RotateCcw,
  Sparkles,
  Tags,
} from "lucide-react";
import clsx from "clsx";
import type { RiskFilter } from "@/types/network";
import { RISK_COLORS } from "@/lib/network-data";

export interface SceneControlsProps {
  showLabels: boolean;
  onToggleLabels: () => void;
  showParticles: boolean;
  onToggleParticles: () => void;
  /** True when prefers-reduced-motion is active (particles unavailable). */
  particlesDisabled?: boolean;
  riskFilter: RiskFilter;
  onRiskFilterChange: (filter: RiskFilter) => void;
  onResetCamera: () => void;
  isFullscreen: boolean;
  onToggleFullscreen: () => void;
  className?: string;
}

const FILTER_OPTIONS: Array<{
  value: RiskFilter;
  label: string;
  color?: string;
}> = [
  { value: "all", label: "All" },
  { value: "suspicious", label: "Susp+", color: RISK_COLORS.suspicious },
  { value: "high", label: "High+", color: RISK_COLORS.high },
  { value: "critical", label: "Crit", color: RISK_COLORS.critical },
];

/**
 * Floating glass control bar for the 3D viewport: camera reset, label and
 * particle toggles, the behavioral risk filter, and fullscreen.
 */
export default function SceneControls({
  showLabels,
  onToggleLabels,
  showParticles,
  onToggleParticles,
  particlesDisabled = false,
  riskFilter,
  onRiskFilterChange,
  onResetCamera,
  isFullscreen,
  onToggleFullscreen,
  className,
}: SceneControlsProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
      role="toolbar"
      aria-label="Scene controls"
      className={clsx(
        "glass-panel-strong pointer-events-auto flex flex-wrap items-center gap-1 rounded-xl border border-cyber-border/90 px-2 py-1.5 shadow-panel",
        className,
      )}
    >
      <ControlButton label="Reset camera" onClick={onResetCamera}>
        <RotateCcw className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
      </ControlButton>

      <ControlButton
        label={showLabels ? "Hide labels" : "Show labels"}
        active={showLabels}
        onClick={onToggleLabels}
      >
        <Tags className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
        <span className="hidden sm:inline">Labels</span>
      </ControlButton>

      <ControlButton
        label={showParticles ? "Hide packet flow" : "Show packet flow"}
        active={showParticles && !particlesDisabled}
        disabled={particlesDisabled}
        onClick={onToggleParticles}
      >
        <Sparkles className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
        <span className="hidden sm:inline">Flow</span>
      </ControlButton>

      <span className="mx-1 hidden h-5 w-px bg-cyber-border/80 sm:block" aria-hidden="true" />

      <div
        role="group"
        aria-label="Risk filter"
        className="flex items-center gap-0.5 rounded-lg border border-cyber-border/70 bg-cyber-bg/40 p-0.5"
      >
        {FILTER_OPTIONS.map((option) => {
          const active = riskFilter === option.value;
          return (
            <button
              key={option.value}
              type="button"
              onClick={() => onRiskFilterChange(option.value)}
              aria-pressed={active}
              className={clsx(
                "flex h-7 items-center gap-1.5 rounded-md px-2 font-data text-[10px] tracking-[0.08em] uppercase",
                active
                  ? "bg-cyber-overlay text-slate-100 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.35)]"
                  : "text-cyber-muted hover:text-slate-200",
              )}
            >
              {option.color && (
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{
                    backgroundColor: option.color,
                    boxShadow: `0 0 6px ${option.color}`,
                  }}
                  aria-hidden="true"
                />
              )}
              {option.label}
            </button>
          );
        })}
      </div>

      <span className="mx-1 hidden h-5 w-px bg-cyber-border/80 sm:block" aria-hidden="true" />

      <ControlButton
        label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
        onClick={onToggleFullscreen}
      >
        {isFullscreen ? (
          <Minimize2 className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
        ) : (
          <Maximize2 className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
        )}
      </ControlButton>
    </motion.div>
  );
}

/* -------------------------------------------------------------------------- */

interface ControlButtonProps {
  label: string;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

function ControlButton({
  label,
  active = false,
  disabled = false,
  onClick,
  children,
}: ControlButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      aria-pressed={active}
      title={label}
      className={clsx(
        "flex h-8 items-center gap-1.5 rounded-lg border px-2.5 font-data text-[11px] tracking-wide",
        active
          ? "border-cyber-accent/50 bg-cyber-accent/10 text-cyber-accent-bright"
          : "border-transparent text-cyber-muted hover:border-cyber-border hover:bg-cyber-overlay/50 hover:text-slate-100",
        disabled &&
          "cursor-not-allowed opacity-40 hover:border-transparent hover:bg-transparent hover:text-cyber-muted",
      )}
    >
      {children}
    </button>
  );
}
