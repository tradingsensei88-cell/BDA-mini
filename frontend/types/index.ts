import type { LucideIcon } from "lucide-react";

/* --------------------------------------------------------------------------
   Navigation
   -------------------------------------------------------------------------- */

/** A single entry in the SOC sidebar navigation. */
export interface NavigationItem {
  name: string;
  href: string;
  icon: LucideIcon;
  /** Optional count rendered as a badge (e.g. open alerts). */
  badge?: number;
}

/* --------------------------------------------------------------------------
   Health & status
   -------------------------------------------------------------------------- */

/** Lifecycle status for any streaming service or pipeline node. */
export type ServiceStatus = "online" | "warning" | "offline" | "connecting";

/** Reported health snapshot of one backend service. */
export interface SystemHealth {
  service: string;
  status: ServiceStatus;
  /** Uptime percentage, 0-100. */
  uptime: number;
  /** Round-trip latency in milliseconds. */
  latency: number;
}

/** Aggregate platform health rendered in the header badge. */
export type PlatformHealth = "healthy" | "warning" | "critical";

/* --------------------------------------------------------------------------
   Metrics
   -------------------------------------------------------------------------- */

export type TrendDirection = "up" | "down" | "flat";

/** A headline KPI tile (events/sec, alerts, precision, ...). */
export interface KPICard {
  title: string;
  value: number;
  /** Signed percentage change vs. the comparison window. */
  change: number;
  trend: TrendDirection;
  icon: LucideIcon;
  /** Optional unit appended to the rendered value, e.g. "eps", "%". */
  unit?: string;
}

/* --------------------------------------------------------------------------
   Threat taxonomy
   -------------------------------------------------------------------------- */

/** Severity levels aligned with `severity.*` tokens in tailwind.config.ts. */
export enum ThreatLevel {
  Critical = "critical",
  High = "high",
  Medium = "medium",
  Low = "low",
  Info = "info",
}

/** Lifecycle of an alert inside the SOC triage workflow. */
export enum AlertStatus {
  New = "new",
  Investigating = "investigating",
  Acknowledged = "acknowledged",
  Resolved = "resolved",
}

/** Union form of `ThreatLevel`, convenient for component props. */
export type SeverityLevel = `${ThreatLevel}`;

/* --------------------------------------------------------------------------
   Streaming telemetry
   -------------------------------------------------------------------------- */

/** One normalized network-flow record emitted by the ingestion pipeline. */
export interface NetworkEvent {
  id: string;
  timestamp: string;
  sourceIp: string;
  destinationIp: string;
  protocol: "TCP" | "UDP" | "ICMP" | "HTTP" | "HTTPS" | "DNS";
  bytes: number;
  severity: ThreatLevel;
  /** Human-readable classifier output, e.g. "Port Scan". */
  classification: string;
}

/* --------------------------------------------------------------------------
   SOC domain vocabulary (dashboard mock data & future API responses)
   -------------------------------------------------------------------------- */

/** Attack taxonomy used by the NSL-KDD trained detector. */
export type AttackCategory = "normal" | "dos" | "probe" | "r2l" | "u2r";

/** Attack-only subset (benign traffic excluded). */
export type AttackKind = Exclude<AttackCategory, "normal">;

/** Triage lifecycle of an alert inside the SOC workflow. */
export type AlertWorkflowStatus =
  | "new"
  | "investigating"
  | "acknowledged"
  | "resolved";

/** Case lifecycle of an investigation. */
export type InvestigationStatus = "open" | "in_progress" | "closed";

/** Post-triage disposition of a suspicious source host. */
export type SourceDisposition =
  | "blocked"
  | "quarantined"
  | "watchlist"
  | "monitoring"
  | "cleared";

/** Transport protocol of a captured flow. */
export type FlowProtocol = "TCP" | "UDP" | "ICMP";

/** Time-range presets for the analytics time-series charts. */
export type TimelineRange = "1h" | "6h" | "24h" | "7d";

/** One classified network flow surfaced on the threat feed / tables. */
export interface ThreatEvent {
  id: string;
  timestamp: string;
  source: string;
  sourceIp: string;
  destination: string;
  destinationIp: string;
  protocol: FlowProtocol;
  category: AttackKind;
  /** NSL-KDD attack label, e.g. "neptune". */
  attackType: string;
  /** Classifier confidence, 0-1. */
  confidence: number;
  /** Composite risk score, 0-100. */
  riskScore: number;
  severity: SeverityLevel;
  status: AlertWorkflowStatus;
  bytes: number;
  /** Top contributing features behind the ML decision. */
  topFeatures: string[];
}

/** A ThreatEvent promoted into the alert triage queue. */
export interface AlertRecord extends ThreatEvent {
  title: string;
}

/** Aggregated reputation row for a noisy source host. */
export interface ThreatSourceRow {
  id: string;
  firstSeen: string;
  lastSeen: string;
  events: number;
  threats: number;
  riskScore: number;
  topAttack: string;
  category: AttackKind;
  status: SourceDisposition;
}

/** One bucket of the stacked attack timeline. */
export interface TimelinePoint {
  /** Index signature keeps timeline rows assignable to generic chart data. */
  [key: string]: string | number;
  time: string;
  normal: number;
  dos: number;
  probe: number;
  r2l: number;
  u2r: number;
}

/** Donut slice for the attack distribution chart. */
export interface CategorySlice {
  name: string;
  value: number;
  color: string;
  category: AttackCategory;
}

/** KPI tile rendered on the SOC overview. */
export interface KpiTile extends KPICard {
  id: string;
  /** Tailwind text color class used for the value / trend accent. */
  accent: string;
  /** Tailwind classes for the icon chip. */
  chip: string;
  /** Whether an increase is good (green) or bad (red). */
  positive?: boolean;
  /** Renders a live pulsing dot and jittering value. */
  live?: boolean;
  /** Decimal places used when rendering the animated value. */
  decimals?: number;
}

/** Small key/value chip used across info cards. */
export interface InfoItem {
  label: string;
  value: string;
}

/** Row of the ML feature-importance ranking. */
export interface FeatureImportanceRow {
  feature: string;
  importance: number;
}

/** Row of the per-class classification report. */
export interface ClassPerformanceRow {
  label: string;
  precision: number;
  recall: number;
  f1: number;
  support: number;
}

/** Confidence histogram bucket (counts per class). */
export interface ConfidenceBucketRow {
  bucket: string;
  normal: number;
  dos: number;
  probe: number;
  r2l: number;
  u2r: number;
}

/** Row of the radar chart comparing attack categories. */
export interface RadarMetricRow {
  metric: string;
  dos: number;
  probe: number;
  r2l: number;
  u2r: number;
}

/** Protocol breakdown for the horizontal bar chart. */
export interface ProtocolBreakdownRow {
  protocol: FlowProtocol;
  normal: number;
  attacks: number;
}

/** One row of the analytics source-by-hour heatmap. */
export interface HeatmapRow {
  host: string;
  cells: number[];
}

/** One stage of the streaming pipeline visualization. */
export interface PipelineStage {
  id: string;
  name: string;
  role: string;
  icon: LucideIcon;
  status: ServiceStatus;
  throughput: string;
  latencyMs: number;
  processed: number;
  note?: string;
}

/** Service card on the system health page. */
export interface ServiceHealthCard {
  id: string;
  name: string;
  icon: LucideIcon;
  status: ServiceStatus;
  /** Uptime percentage, 0-100. */
  uptime: number;
  summary: string;
  metrics: InfoItem[];
  /** 30 samples covering the last hour (sparkline). */
  sparkline: number[];
  /** 48 half-hour status slots covering the last 24h. */
  uptimeBars: ServiceStatus[];
}

/** Incident row of the system uptime timeline. */
export interface IncidentEntry {
  id: string;
  time: string;
  service: string;
  title: string;
  status: "resolved" | "ongoing";
  severity: SeverityLevel;
}

/** Case file shown in the investigations workspace. */
export interface InvestigationRecord {
  id: string;
  title: string;
  severity: SeverityLevel;
  category: AttackKind;
  analyst: string;
  team: string;
  status: InvestigationStatus;
  createdAt: string;
  updatedAt: string;
  relatedAlerts: number;
  riskScore: number;
  confidence: number;
  summary: string;
  findings: Array<{ time: string; note: string }>;
}
