"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  BellRing,
  Brain,
  Check,
  Cpu,
  RotateCcw,
  Save,
  Settings2,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import clsx from "clsx";
import PageShell from "@/components/layout/PageShell";
import GlassCard from "@/components/ui/GlassCard";
import SectionHeading from "@/components/ui/SectionHeading";
import SeverityBadge from "@/components/ui/SeverityBadge";
import { formatCompact } from "@/lib/format";
import type { SeverityLevel } from "@/types";

/* -------------------------------------------------------------------------- */
/*  Settings state                                                             */
/* -------------------------------------------------------------------------- */

interface SettingsState {
  theme: string;
  language: string;
  timezone: string;
  compactNumbers: boolean;

  emailAlerts: boolean;
  desktopAlerts: boolean;
  dailyDigest: boolean;
  emailMinSeverity: SeverityLevel;

  eventRate: number;
  batchSize: number;
  checkpointSeconds: number;

  confidenceThreshold: number;
  retrainSchedule: string;
  driftSensitivity: string;
  autoQuarantine: boolean;

  thresholds: Record<Exclude<SeverityLevel, "info">, number>;
}

const DEFAULT_SETTINGS: SettingsState = {
  theme: "cyber-dark",
  language: "en-US",
  timezone: "UTC",
  compactNumbers: true,

  emailAlerts: true,
  desktopAlerts: true,
  dailyDigest: false,
  emailMinSeverity: "high",

  eventRate: 25000,
  batchSize: 5000,
  checkpointSeconds: 10,

  confidenceThreshold: 75,
  retrainSchedule: "weekly",
  driftSensitivity: "medium",
  autoQuarantine: true,

  thresholds: { critical: 90, high: 72, medium: 48, low: 22 },
};

/* -------------------------------------------------------------------------- */
/*  Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function SettingsPage() {
  const [settings, setSettings] = useState<SettingsState>(DEFAULT_SETTINGS);
  const [saved, setSaved] = useState(false);
  const saveTimer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    },
    [],
  );

  const patch = (partial: Partial<SettingsState>) =>
    setSettings((prev) => ({ ...prev, ...partial }));

  const handleSave = () => {
    setSaved(true);
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => setSaved(false), 2400);
  };

  const thresholdsDirty = JSON.stringify(settings) !== JSON.stringify(DEFAULT_SETTINGS);

  return (
    <PageShell
      title="Settings"
      description="Workspace preferences, alert routing, pipeline tuning, and detection thresholds."
      icon={Settings2}
      moduleIndex="10 / 10"
    >
      <div className="space-y-5">
        {/* ------------------------------------------------------------------ */}
        {/* Action bar                                                          */}
        {/* ------------------------------------------------------------------ */}
        <GlassCard className="flex flex-wrap items-center justify-between gap-3 p-4">
          <p className="flex items-center gap-2 font-data text-[11px] text-cyber-muted">
            <Sparkles className="h-3.5 w-3.5 text-cyber-accent" aria-hidden="true" />
            Changes persist to this workspace · mock values, wired to the config API later
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setSettings(DEFAULT_SETTINGS)}
              className="flex items-center gap-2 rounded-lg border border-cyber-border/80 bg-cyber-surface/60 px-3.5 py-2 text-[12px] font-medium text-cyber-muted hover:border-cyber-accent/30 hover:text-slate-100"
            >
              <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
              Reset
            </button>
            <button
              type="button"
              onClick={handleSave}
              className={clsx(
                "flex items-center gap-2 rounded-lg border px-3.5 py-2 text-[12px] font-medium transition-colors",
                saved
                  ? "border-severity-low/40 bg-severity-low/15 text-emerald-300"
                  : "border-cyber-accent/35 bg-cyber-accent/10 text-cyber-accent-bright hover:bg-cyber-accent/20",
              )}
            >
              {saved ? (
                <>
                  <Check className="h-3.5 w-3.5" aria-hidden="true" />
                  Saved
                </>
              ) : (
                <>
                  <Save className="h-3.5 w-3.5" aria-hidden="true" />
                  Apply Changes
                </>
              )}
            </button>
          </div>
        </GlassCard>

        {/* ------------------------------------------------------------------ */}
        {/* General + Notifications                                             */}
        {/* ------------------------------------------------------------------ */}
        <div className="grid gap-5 xl:grid-cols-2">
          <GlassCard>
            <SectionHeading title="General" hint="workspace look & locale" />
            <div className="divide-y divide-cyber-border/50">
              <SettingRow label="Theme" description="Console color scheme">
                <Select
                  value={settings.theme}
                  onChange={(value) => patch({ theme: value })}
                  options={[
                    { value: "cyber-dark", label: "Cyber Dark (default)" },
                    { value: "midnight", label: "Midnight" },
                    { value: "high-contrast", label: "High Contrast" },
                  ]}
                />
              </SettingRow>
              <SettingRow label="Language" description="Interface locale">
                <Select
                  value={settings.language}
                  onChange={(value) => patch({ language: value })}
                  options={[
                    { value: "en-US", label: "English (US)" },
                    { value: "en-GB", label: "English (UK)" },
                    { value: "de-DE", label: "Deutsch" },
                    { value: "fr-FR", label: "Français" },
                  ]}
                />
              </SettingRow>
              <SettingRow label="Timezone" description="All timestamps render in this zone">
                <Select
                  value={settings.timezone}
                  onChange={(value) => patch({ timezone: value })}
                  options={[
                    { value: "UTC", label: "UTC" },
                    { value: "America/New_York", label: "America/New_York" },
                    { value: "Europe/London", label: "Europe/London" },
                    { value: "Asia/Singapore", label: "Asia/Singapore" },
                    { value: "Asia/Kolkata", label: "Asia/Kolkata" },
                  ]}
                />
              </SettingRow>
              <SettingRow label="Compact numbers" description="Render 24.8K instead of 24,812">
                <Toggle
                  checked={settings.compactNumbers}
                  onChange={(value) => patch({ compactNumbers: value })}
                  label="Compact numbers"
                />
              </SettingRow>
            </div>
          </GlassCard>

          <GlassCard>
            <SectionHeading title="Notifications" hint="routing & thresholds" />
            <div className="divide-y divide-cyber-border/50">
              <SettingRow label="Email alerts" description="ops-oncall@cybershield.ai">
                <Toggle
                  checked={settings.emailAlerts}
                  onChange={(value) => patch({ emailAlerts: value })}
                  label="Email alerts"
                />
              </SettingRow>
              <SettingRow label="Desktop alerts" description="Browser push for live detections">
                <Toggle
                  checked={settings.desktopAlerts}
                  onChange={(value) => patch({ desktopAlerts: value })}
                  label="Desktop alerts"
                />
              </SettingRow>
              <SettingRow label="Daily digest" description="06:00 local summary of open cases">
                <Toggle
                  checked={settings.dailyDigest}
                  onChange={(value) => patch({ dailyDigest: value })}
                  label="Daily digest"
                />
              </SettingRow>
              <SettingRow label="Minimum severity" description="Floor for email delivery">
                <Select
                  value={settings.emailMinSeverity}
                  onChange={(value) => patch({ emailMinSeverity: value as SeverityLevel })}
                  options={[
                    { value: "critical", label: "Critical only" },
                    { value: "high", label: "High & above" },
                    { value: "medium", label: "Medium & above" },
                    { value: "low", label: "Everything" },
                  ]}
                />
              </SettingRow>
            </div>
          </GlassCard>
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Data pipeline + ML model                                            */}
        {/* ------------------------------------------------------------------ */}
        <div className="grid gap-5 xl:grid-cols-2">
          <GlassCard>
            <SectionHeading title="Data Pipeline" hint="ingest & micro-batch tuning" />
            <div className="divide-y divide-cyber-border/50">
              <SettingRow
                label="Target event rate"
                description="Throttle ceiling pushed to Kafka producers"
                value={formatCompact(settings.eventRate) + " ev/s"}
              >
                <Slider
                  min={1000}
                  max={50000}
                  step={1000}
                  value={settings.eventRate}
                  onChange={(value) => patch({ eventRate: value })}
                  label="Target event rate"
                />
              </SettingRow>
              <SettingRow
                label="Micro-batch size"
                description="Records per Spark Streaming window"
                value={settings.batchSize.toLocaleString("en-US")}
              >
                <Slider
                  min={500}
                  max={10000}
                  step={500}
                  value={settings.batchSize}
                  onChange={(value) => patch({ batchSize: value })}
                  label="Micro-batch size"
                />
              </SettingRow>
              <SettingRow
                label="Checkpoint interval"
                description="Kafka consumer offset commit cadence"
                value={`${settings.checkpointSeconds}s`}
              >
                <Slider
                  min={2}
                  max={60}
                  step={2}
                  value={settings.checkpointSeconds}
                  onChange={(value) => patch({ checkpointSeconds: value })}
                  label="Checkpoint interval"
                />
              </SettingRow>
            </div>
          </GlassCard>

          <GlassCard>
            <SectionHeading title="ML Model" hint="scoring & lifecycle" />
            <div className="divide-y divide-cyber-border/50">
              <SettingRow
                label="Confidence threshold"
                description="Flows scored below this stay unalerted"
                value={`${settings.confidenceThreshold}%`}
              >
                <Slider
                  min={50}
                  max={99}
                  step={1}
                  value={settings.confidenceThreshold}
                  onChange={(value) => patch({ confidenceThreshold: value })}
                  label="Confidence threshold"
                />
              </SettingRow>
              <SettingRow label="Retrain schedule" description="Nightly job retrains the RF ensemble">
                <Select
                  value={settings.retrainSchedule}
                  onChange={(value) => patch({ retrainSchedule: value })}
                  options={[
                    { value: "weekly", label: "Weekly · Sun 02:00 UTC" },
                    { value: "biweekly", label: "Bi-weekly" },
                    { value: "monthly", label: "Monthly" },
                    { value: "manual", label: "Manual only" },
                  ]}
                />
              </SettingRow>
              <SettingRow label="Drift sensitivity" description="PSI alerting on feature distribution">
                <Select
                  value={settings.driftSensitivity}
                  onChange={(value) => patch({ driftSensitivity: value })}
                  options={[
                    { value: "low", label: "Low" },
                    { value: "medium", label: "Medium" },
                    { value: "high", label: "High" },
                  ]}
                />
              </SettingRow>
              <SettingRow
                label="Auto-quarantine"
                description="Isolate source host on ≥ 0.95 confidence"
              >
                <Toggle
                  checked={settings.autoQuarantine}
                  onChange={(value) => patch({ autoQuarantine: value })}
                  label="Auto-quarantine"
                />
              </SettingRow>
            </div>
          </GlassCard>
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Alert rules                                                         */}
        {/* ------------------------------------------------------------------ */}
        <GlassCard>
          <SectionHeading
            title="Alert Rules"
            hint="risk score thresholds per severity"
            action={
              <span className="flex items-center gap-1.5 font-data text-[10px] text-cyber-muted">
                <SlidersHorizontal className="h-3 w-3 text-cyber-accent" aria-hidden="true" />
                drag to adjust
              </span>
            }
          />
          <ul className="divide-y divide-cyber-border/50">
            {(["critical", "high", "medium", "low"] as const).map((level) => (
              <li key={level} className="flex flex-wrap items-center gap-x-5 gap-y-3 py-3.5">
                <span className="w-[104px] shrink-0">
                  <SeverityBadge level={level} size="sm" />
                </span>
                <div className="min-w-[180px] flex-1">
                  <Slider
                    min={0}
                    max={100}
                    step={1}
                    value={settings.thresholds[level]}
                    onChange={(value) =>
                      patch({
                        thresholds: { ...settings.thresholds, [level]: value },
                      })
                    }
                    label={`${level} risk threshold`}
                  />
                </div>
                <span className="w-[86px] shrink-0 text-right font-data text-[12px] tabular text-slate-100">
                  ≥ {settings.thresholds[level]}/100
                </span>
                <span className="hidden w-[150px] shrink-0 text-right font-data text-[10px] text-cyber-muted/80 lg:block">
                  {level === "critical" && "page on-call immediately"}
                  {level === "high" && "ticket + email on-call"}
                  {level === "medium" && "queue for triage"}
                  {level === "low" && "log & aggregate"}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-4 flex items-center gap-2 border-t border-cyber-border/50 pt-3 font-data text-[10.5px] text-cyber-muted">
            <Cpu className="h-3 w-3 text-cyber-accent" aria-hidden="true" />
            Thresholds are evaluated after ML scoring on the composite risk index (0–100)
            {thresholdsDirty && <span className="text-amber-300">· unsaved changes</span>}
          </p>
        </GlassCard>

        {/* ------------------------------------------------------------------ */}
        {/* Security posture note                                               */}
        {/* ------------------------------------------------------------------ */}
        <GlassCard className="flex flex-wrap items-center gap-4">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg border border-cyber-accent/25 bg-cyber-accent/10">
            <Brain className="h-4 w-4 text-cyber-accent" strokeWidth={1.9} aria-hidden="true" />
          </span>
          <div className="min-w-[240px] flex-1">
            <p className="text-[13px] font-medium text-slate-100">
              Configuration audit trail enabled
            </p>
            <p className="mt-0.5 text-[11.5px] text-cyber-muted">
              Every change is versioned with actor, timestamp, and diff — visible under
              Investigations → audit. RBAC: only analysts with the{" "}
              <span className="font-data text-slate-300">config:write</span> scope can apply changes.
            </p>
          </div>
          <span className="flex items-center gap-1.5 rounded-full border border-severity-low/30 bg-severity-low/10 px-2.5 py-1 font-data text-[10px] tracking-wide text-emerald-300 uppercase">
            <BellRing className="h-3 w-3" aria-hidden="true" />
            enforced
          </span>
        </GlassCard>
      </div>
    </PageShell>
  );
}

/* -------------------------------------------------------------------------- */
/*  Controls                                                                   */
/* -------------------------------------------------------------------------- */

function SettingRow({
  label,
  description,
  value,
  children,
}: {
  label: string;
  description: string;
  value?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-3 py-3.5">
      <div className="min-w-[190px] flex-1">
        <p className="text-[12.5px] font-medium text-slate-100">{label}</p>
        <p className="mt-0.5 text-[11px] text-cyber-muted">{description}</p>
      </div>
      {value !== undefined && (
        <span className="order-last shrink-0 font-data text-[11.5px] tabular text-cyber-accent-bright sm:order-none">
          {value}
        </span>
      )}
      <div className="w-full sm:w-auto sm:min-w-[170px] sm:max-w-[220px]">{children}</div>
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={clsx(
        "relative h-6 w-11 shrink-0 rounded-full border transition-colors",
        checked
          ? "border-cyber-accent/50 bg-cyber-accent/25"
          : "border-cyber-border bg-cyber-surface",
      )}
    >
      <motion.span
        animate={{ x: checked ? 20 : 0 }}
        transition={{ type: "spring", stiffness: 520, damping: 32 }}
        className={clsx(
          "absolute left-[3px] top-[3px] h-4 w-4 rounded-full shadow-[0_0_10px_-1px_rgba(34,211,238,0.7)]",
          checked ? "bg-cyber-accent" : "bg-slate-500 shadow-none",
        )}
      />
    </button>
  );
}

function Slider({
  min,
  max,
  step,
  value,
  onChange,
  label,
}: {
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (value: number) => void;
  label: string;
}) {
  const progress = ((value - min) / (max - min)) * 100;
  return (
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      aria-label={label}
      onChange={(event) => onChange(Number(event.target.value))}
      className="h-1.5 w-full cursor-pointer appearance-none rounded-full focus-visible:outline-none"
      style={{
        accentColor: "#22d3ee",
        background: `linear-gradient(to right, #22d3ee ${progress}%, rgba(23, 35, 61, 0.9) ${progress}%)`,
      }}
    />
  );
}

function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="w-full rounded-lg border border-cyber-border/90 bg-cyber-surface/80 px-3 py-2 text-[12.5px] text-slate-100 outline-none focus:border-cyber-accent/50"
    >
      {options.map((option) => (
        <option key={option.value} value={option.value} className="bg-cyber-surface text-slate-100">
          {option.label}
        </option>
      ))}
    </select>
  );
}
