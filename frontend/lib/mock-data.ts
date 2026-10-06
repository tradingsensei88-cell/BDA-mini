/**
 * Central mock dataset for every CyberShield AI dashboard page.
 *
 * All values are generated from a fixed seed + fixed base timestamp, so the
 * dataset is realistic but fully deterministic. This keeps server rendering
 * and client hydration in perfect agreement (no Math.random at module scope).
 *
 * Grounded in the NSL-KDD taxonomy: Normal, DoS, Probe, R2L, U2R.
 * A later task swaps these arrays for live API + WebSocket feeds.
 */

import {
  AlertOctagon,
  ArrowRightLeft,
  Brain,
  Database,
  HardDrive,
  Layers,
  MemoryStick,
  Monitor,
  Network,
  Radar,
  Radio,
  Search,
  Server,
  ShieldAlert,
  Target,
  Wrench,
  Zap,
} from "lucide-react";
import type {
  AlertRecord,
  AttackCategory,
  AttackKind,
  CategorySlice,
  ClassPerformanceRow,
  ConfidenceBucketRow,
  FeatureImportanceRow,
  FlowProtocol,
  HeatmapRow,
  IncidentEntry,
  InfoItem,
  InvestigationRecord,
  KpiTile,
  PipelineStage,
  ProtocolBreakdownRow,
  RadarMetricRow,
  ServiceHealthCard,
  ServiceStatus,
  SeverityLevel,
  ThreatEvent,
  ThreatSourceRow,
  TimelinePoint,
  TimelineRange,
} from "@/types";
import { formatBucketHourUTC } from "@/lib/format";

/* --------------------------------------------------------------------------
   Deterministic RNG + time helpers
   -------------------------------------------------------------------------- */

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const rng = mulberry32(20260406);

const MINUTE = 60_000;
const HOUR = 3_600_000;

/** Fixed "now" for the mock telemetry window (UTC). */
export const BASE_TIME = Date.parse("2026-10-06T15:45:00.000Z");

const iso = (ms: number) => new Date(ms).toISOString();
const pick = <T,>(items: T[]): T => items[Math.floor(rng() * items.length)];
const round1 = (value: number) => Math.round(value * 10) / 10;

/* --------------------------------------------------------------------------
   Palette & taxonomy
   -------------------------------------------------------------------------- */

/** Chart palette mandated by the design spec. */
export const ATTACK_COLORS: Record<AttackCategory, string> = {
  normal: "#06b6d4",
  dos: "#ef4444",
  probe: "#f97316",
  r2l: "#a855f7",
  u2r: "#ec4899",
};

export const SEVERITY_HEX: Record<SeverityLevel, string> = {
  critical: "#FF3B5C",
  high: "#FF8A3D",
  medium: "#FFD166",
  low: "#34D399",
  info: "#60A5FA",
};

export const CATEGORY_LABELS: Record<AttackCategory, string> = {
  normal: "Normal",
  dos: "DoS",
  probe: "Probe",
  r2l: "R2L",
  u2r: "U2R",
};

export const CATEGORY_FULL_NAMES: Record<AttackCategory, string> = {
  normal: "Normal traffic",
  dos: "Denial of Service",
  probe: "Probing / Surveillance",
  r2l: "Remote to Local",
  u2r: "User to Root",
};

/** NSL-KDD attack labels per category. */
export const ATTACK_TYPES: Record<AttackKind, string[]> = {
  dos: ["neptune", "smurf", "back", "teardrop", "pod", "land", "mailbomb", "apache2"],
  probe: ["satan", "ipsweep", "nmap", "portsweep", "mscan", "saint"],
  r2l: ["guess_passwd", "warezclient", "warezmaster", "ftp_write", "imap", "phf", "multihop", "spy"],
  u2r: ["buffer_overflow", "rootkit", "loadmodule", "perl", "sqlattack", "xterm"],
};

const GENERIC_REASONS = [
  "High traffic volume",
  "Unusual connection pattern",
  "Abnormal packet behavior",
  "Asymmetric byte ratio",
  "Bursty inter-arrival times",
  "Off-hours connection attempt",
];

const CATEGORY_REASONS: Record<AttackKind, string[]> = {
  dos: [
    "Sustained high packet rate",
    "SYN flood signature detected",
    "Abnormal bandwidth spike",
    "Connection table exhaustion",
    "Low source-port entropy",
  ],
  probe: [
    "Sequential port sweep pattern",
    "High unique-destination fan-out",
    "Short-lived connection bursts",
    "ICMP echo sweep signature",
    "Service enumeration behavior",
  ],
  r2l: [
    "Repeated authentication failures",
    "Abnormal login timing",
    "Unusual data transfer after auth",
    "Remote shell payload detected",
    "Credential stuffing pattern",
  ],
  u2r: [
    "Privilege escalation syscall chain",
    "Malformed kernel payload",
    "Unauthorized root shell spawn",
    "Suspicious kernel module load",
    "Privileged process anomaly",
  ],
};

const SIGNATURE_FEATURES: Record<AttackKind, string[]> = {
  dos: ["src_bytes spike (+38 MB/s)", "count = 512 conn / 2s", "serror_rate = 0.97", "same_srv_rate = 0.01"],
  probe: ["unique dst ports = 1,024", "diff_srv_rate = 0.91", "dst_host_count = 255", "rerror_rate = 0.42"],
  r2l: ["num_failed_logins = 6", "logged_in = 1", "dst_bytes = 8.4 MB exfil", "hot = 12"],
  u2r: ["root_shell = 1", "num_root = 4", "su_attempted = 2", "is_hot_login = 1"],
};

/* --------------------------------------------------------------------------
   Timeline series (10-minute resolution across 7 days)
   -------------------------------------------------------------------------- */

function buildSeries(slots: number): TimelinePoint[] {
  const out: TimelinePoint[] = [];
  for (let i = slots - 1; i >= 0; i--) {
    const t = BASE_TIME - i * 10 * MINUTE;
    const d = new Date(t);
    const hour = d.getUTCHours() + d.getUTCMinutes() / 60;
    const diurnal = 1 + 0.38 * Math.sin(((hour - 14) / 24) * Math.PI * 2);
    const burst = rng() < 0.06 ? 3.5 + rng() * 6 : 1;
    out.push({
      time: iso(t),
      normal: Math.round(820 * diurnal + rng() * 180),
      dos: Math.round((30 + rng() * 40) * diurnal * burst),
      probe: Math.round((8 + rng() * 18) * diurnal),
      r2l: rng() < 0.5 ? 0 : Math.round(1 + rng() * 6),
      u2r: rng() < 0.9 ? 0 : 1,
    });
  }
  return out;
}

const FULL_7D = buildSeries(7 * 24 * 6); // 1,008 ten-minute slots

function aggregateHourly(points: TimelinePoint[]): TimelinePoint[] {
  const buckets = new Map<string, TimelinePoint>();
  for (const p of points) {
    const d = new Date(p.time);
    const key = `${d.getUTCFullYear()}-${d.getUTCMonth()}-${d.getUTCDate()}-${d.getUTCHours()}`;
    const bucket = buckets.get(key);
    if (!bucket) {
      buckets.set(key, {
        time: new Date(
          Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), d.getUTCHours()),
        ).toISOString(),
        normal: p.normal,
        dos: p.dos,
        probe: p.probe,
        r2l: p.r2l,
        u2r: p.u2r,
      });
    } else {
      bucket.normal += p.normal;
      bucket.dos += p.dos;
      bucket.probe += p.probe;
      bucket.r2l += p.r2l;
      bucket.u2r += p.u2r;
    }
  }
  return Array.from(buckets.values());
}

/** Time-series data for the requested range (newest point last). */
export function getTimelineSeries(range: TimelineRange): TimelinePoint[] {
  switch (range) {
    case "1h":
      return FULL_7D.slice(-7);
    case "6h":
      return FULL_7D.slice(-37);
    case "24h":
      return FULL_7D.slice(-145);
    case "7d":
      return aggregateHourly(FULL_7D);
  }
}

/* --------------------------------------------------------------------------
   Attack distribution + hourly buckets (last 24h)
   -------------------------------------------------------------------------- */

const LAST_24H = FULL_7D.slice(-144);

export const ATTACK_DISTRIBUTION_24H: CategorySlice[] = (() => {
  const totals: Record<AttackCategory, number> = { normal: 0, dos: 0, probe: 0, r2l: 0, u2r: 0 };
  for (const p of LAST_24H) {
    totals.normal += p.normal;
    totals.dos += p.dos;
    totals.probe += p.probe;
    totals.r2l += p.r2l;
    totals.u2r += p.u2r;
  }
  return (Object.keys(totals) as AttackCategory[]).map((category) => ({
    category,
    name: CATEGORY_LABELS[category],
    value: totals[category],
    color: ATTACK_COLORS[category],
  }));
})();

export interface HourlyAttackBucket {
  hour: string;
  dos: number;
  probe: number;
  r2l: number;
  u2r: number;
}

/** 24 hourly buckets of attack counts (attacks only, stacked bars). */
export const HOURLY_ATTACK_BUCKETS: HourlyAttackBucket[] = Array.from(
  { length: 24 },
  (_, i) => {
    const chunk = LAST_24H.slice(i * 6, i * 6 + 6);
    const sum = (key: AttackKind) => chunk.reduce((acc, p) => acc + p[key], 0);
    return {
      hour: formatBucketHourUTC(chunk[chunk.length - 1].time),
      dos: sum("dos"),
      probe: sum("probe"),
      r2l: sum("r2l"),
      u2r: sum("u2r"),
    };
  },
);

/* --------------------------------------------------------------------------
   Threat events (classified flows, last 24h)
   -------------------------------------------------------------------------- */

const SOURCE_HOSTS: Array<{ id: string; ip: string }> = [
  { id: "SIM-SRC-104", ip: "203.0.113.104" },
  { id: "SIM-SRC-231", ip: "203.0.113.231" },
  { id: "SIM-SRC-118", ip: "203.0.113.118" },
  { id: "SIM-SRC-057", ip: "203.0.113.57" },
  { id: "HOST-014", ip: "198.51.100.14" },
  { id: "HOST-007", ip: "198.51.100.7" },
  { id: "HOST-031", ip: "198.51.100.31" },
  { id: "NODE-028", ip: "198.51.100.28" },
  { id: "NODE-042", ip: "198.51.100.42" },
  { id: "GW-002", ip: "198.51.100.2" },
  { id: "EDGE-017", ip: "192.0.2.17" },
  { id: "LAB-VM-226", ip: "192.0.2.226" },
];

const TARGET_HOSTS: Array<{ name: string; ip: string }> = [
  { name: "web-prod-01", ip: "10.0.12.44" },
  { name: "api-gw-02", ip: "10.0.12.9" },
  { name: "db-primary", ip: "10.0.20.5" },
  { name: "auth-svc-01", ip: "10.0.14.18" },
  { name: "edge-node-03", ip: "10.0.8.71" },
  { name: "internal-dns", ip: "10.0.1.2" },
  { name: "mail-relay-01", ip: "10.0.14.33" },
  { name: "cache-redis-02", ip: "10.0.22.11" },
];

function severityFromRisk(risk: number): SeverityLevel {
  if (risk >= 88) return "critical";
  if (risk >= 70) return "high";
  if (risk >= 50) return "medium";
  return "low";
}

const EVENT_STATUS_CYCLE = [
  "new",
  "investigating",
  "new",
  "resolved",
  "investigating",
  "new",
  "acknowledged",
  "resolved",
  "investigating",
  "new",
] as const;

function buildThreatEvents(count: number): ThreatEvent[] {
  const events: ThreatEvent[] = [];
  for (let i = 0; i < count; i++) {
    const roll = rng();
    const category: AttackKind =
      roll < 0.42 ? "dos" : roll < 0.7 ? "probe" : roll < 0.88 ? "r2l" : "u2r";
    const attackType = pick(ATTACK_TYPES[category]);
    const source = pick(SOURCE_HOSTS);
    const target = pick(TARGET_HOSTS);

    const confidence =
      category === "dos"
        ? 0.86 + rng() * 0.13
        : category === "probe"
          ? 0.78 + rng() * 0.18
          : category === "r2l"
            ? 0.81 + rng() * 0.16
            : 0.85 + rng() * 0.14;

    const riskScore = Math.round(
      category === "dos"
        ? 52 + rng() * 36
        : category === "probe"
          ? 38 + rng() * 34
          : category === "r2l"
            ? 65 + rng() * 28
            : 80 + rng() * 19,
    );

    const bytes =
      category === "dos"
        ? Math.round(2_000_000 + rng() * 38_000_000)
        : category === "probe"
          ? Math.round(380 + rng() * 2_600)
          : category === "r2l"
            ? Math.round(40_000 + rng() * 900_000)
            : Math.round(6_000 + rng() * 120_000);

    const protocol: FlowProtocol =
      attackType === "smurf" || attackType === "pod" || attackType === "land"
        ? "UDP"
        : category === "probe" && (attackType === "ipsweep" || attackType === "mscan") && rng() < 0.5
          ? "ICMP"
          : "TCP";

    events.push({
      id: `EVT-${String(4800 + i).padStart(4, "0")}`,
      timestamp: iso(BASE_TIME - Math.round(rng() * 23.5 * HOUR)),
      source: source.id,
      sourceIp: source.ip,
      destination: target.name,
      destinationIp: target.ip,
      protocol,
      category,
      attackType,
      confidence: round1(confidence * 1000) / 1000,
      riskScore,
      severity: severityFromRisk(riskScore),
      status: EVENT_STATUS_CYCLE[i % EVENT_STATUS_CYCLE.length],
      bytes,
      topFeatures: [
        pick(CATEGORY_REASONS[category]),
        pick(GENERIC_REASONS),
        pick(SIGNATURE_FEATURES[category]),
        pick(SIGNATURE_FEATURES[category]),
      ],
    });
  }
  return events.sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp));
}

/** 60 classified threat flows over the last 24h (newest first). */
export const THREAT_EVENTS: ThreatEvent[] = buildThreatEvents(60);

/** Recent window used by the live threat feed. */
export const THREAT_FEED_EVENTS: ThreatEvent[] = THREAT_EVENTS.slice(0, 24);

/** 20 events promoted into the alert triage queue. */
export const ALERTS: AlertRecord[] = THREAT_EVENTS.slice(0, 20).map((event) => ({
  ...event,
  id: event.id.replace("EVT", "ALT"),
  title: `${CATEGORY_LABELS[event.category]} Attack Detected - ${event.attackType}`,
}));

/* --------------------------------------------------------------------------
   Top threat sources (aggregated reputation table)
   -------------------------------------------------------------------------- */

export const THREAT_SOURCES: ThreatSourceRow[] = [
  { id: "SIM-SRC-104", firstSeen: iso(BASE_TIME - 71 * HOUR), lastSeen: iso(BASE_TIME - 3 * MINUTE), events: 18432, threats: 1284, riskScore: 94, topAttack: "neptune", category: "dos", status: "quarantined" },
  { id: "SIM-SRC-231", firstSeen: iso(BASE_TIME - 64 * HOUR), lastSeen: iso(BASE_TIME - 9 * MINUTE), events: 15208, threats: 964, riskScore: 91, topAttack: "smurf", category: "dos", status: "blocked" },
  { id: "HOST-014", firstSeen: iso(BASE_TIME - 58 * HOUR), lastSeen: iso(BASE_TIME - 14 * MINUTE), events: 11260, threats: 712, riskScore: 83, topAttack: "buffer_overflow", category: "u2r", status: "watchlist" },
  { id: "NODE-028", firstSeen: iso(BASE_TIME - 49 * HOUR), lastSeen: iso(BASE_TIME - 22 * MINUTE), events: 9874, threats: 548, riskScore: 78, topAttack: "nmap", category: "probe", status: "watchlist" },
  { id: "SIM-SRC-118", firstSeen: iso(BASE_TIME - 44 * HOUR), lastSeen: iso(BASE_TIME - 31 * MINUTE), events: 8142, threats: 486, riskScore: 74, topAttack: "portsweep", category: "probe", status: "monitoring" },
  { id: "EDGE-017", firstSeen: iso(BASE_TIME - 38 * HOUR), lastSeen: iso(BASE_TIME - 46 * MINUTE), events: 7418, threats: 392, riskScore: 71, topAttack: "guess_passwd", category: "r2l", status: "monitoring" },
  { id: "GW-002", firstSeen: iso(BASE_TIME - 33 * HOUR), lastSeen: iso(BASE_TIME - 58 * MINUTE), events: 6390, threats: 341, riskScore: 66, topAttack: "satan", category: "probe", status: "monitoring" },
  { id: "SIM-SRC-057", firstSeen: iso(BASE_TIME - 27 * HOUR), lastSeen: iso(BASE_TIME - 72 * MINUTE), events: 5824, threats: 288, riskScore: 61, topAttack: "teardrop", category: "dos", status: "blocked" },
  { id: "LAB-VM-226", firstSeen: iso(BASE_TIME - 20 * HOUR), lastSeen: iso(BASE_TIME - 96 * MINUTE), events: 4106, threats: 157, riskScore: 48, topAttack: "warezclient", category: "r2l", status: "monitoring" },
  { id: "NODE-042", firstSeen: iso(BASE_TIME - 14 * HOUR), lastSeen: iso(BASE_TIME - 128 * MINUTE), events: 3042, threats: 96, riskScore: 39, topAttack: "ipsweep", category: "probe", status: "cleared" },
];

/* --------------------------------------------------------------------------
   Overview KPIs
   -------------------------------------------------------------------------- */

export const OVERVIEW_KPIS: KpiTile[] = [
  {
    id: "eps",
    title: "Events / sec",
    value: 247,
    change: 12.4,
    trend: "up",
    icon: Zap,
    accent: "text-cyber-accent",
    chip: "border-cyber-accent/25 bg-cyber-accent/10 text-cyber-accent",
    positive: true,
    live: true,
  },
  {
    id: "processed",
    title: "Events Processed · 24h",
    value: 1_284_912,
    change: 3.8,
    trend: "up",
    icon: Database,
    accent: "text-severity-info",
    chip: "border-severity-info/25 bg-severity-info/10 text-severity-info",
    positive: true,
  },
  {
    id: "threats",
    title: "Threats Detected",
    value: 3847,
    change: 8.1,
    trend: "up",
    icon: ShieldAlert,
    accent: "text-severity-high",
    chip: "border-severity-high/25 bg-severity-high/10 text-severity-high",
    positive: false,
  },
  {
    id: "critical",
    title: "Critical Alerts",
    value: 23,
    change: 21.1,
    trend: "up",
    icon: AlertOctagon,
    accent: "text-severity-critical",
    chip: "border-severity-critical/25 bg-severity-critical/10 text-severity-critical",
    positive: false,
  },
  {
    id: "investigations",
    title: "Active Investigations",
    value: 7,
    change: -22.2,
    trend: "down",
    icon: Search,
    accent: "text-cyber-teal",
    chip: "border-cyber-teal/25 bg-cyber-teal/10 text-cyber-teal",
    positive: true,
  },
  {
    id: "anomalies",
    title: "Anomalies Detected",
    value: 156,
    change: 9.9,
    trend: "up",
    icon: Radar,
    accent: "text-severity-medium",
    chip: "border-severity-medium/25 bg-severity-medium/10 text-severity-medium",
    positive: false,
  },
  {
    id: "accuracy",
    title: "Detection Accuracy",
    value: 96.7,
    decimals: 1,
    unit: "%",
    change: 0.4,
    trend: "up",
    icon: Target,
    accent: "text-severity-low",
    chip: "border-severity-low/25 bg-severity-low/10 text-severity-low",
    positive: true,
  },
];

/* --------------------------------------------------------------------------
   Analytics: heatmap, protocols, radar, targeted services
   -------------------------------------------------------------------------- */

export const HEATMAP_HOSTS = [
  "HOST-001",
  "HOST-002",
  "HOST-003",
  "HOST-004",
  "HOST-005",
  "HOST-006",
  "HOST-007",
  "HOST-008",
  "HOST-009",
  "HOST-010",
];

const HOST_ACTIVITY = [1.9, 1.6, 1.35, 1.15, 0.9, 0.72, 0.58, 0.46, 0.36, 0.28];

/** 10 source hosts x 24 hours attack-frequency matrix. */
export const HEATMAP_MATRIX: HeatmapRow[] = HEATMAP_HOSTS.map((host, hi) => ({
  host,
  cells: Array.from({ length: 24 }, (_, hh) => {
    const diurnal = 1 + 0.55 * Math.sin(((hh - 13) / 24) * Math.PI * 2);
    const value = Math.round(HOST_ACTIVITY[hi] * diurnal * (5 + rng() * 22));
    return rng() < 0.06 ? 0 : Math.min(48, value);
  }),
}));

export const PROTOCOL_BREAKDOWN: ProtocolBreakdownRow[] = [
  { protocol: "TCP", normal: 88_400, attacks: 9_800 },
  { protocol: "UDP", normal: 24_600, attacks: 2_800 },
  { protocol: "ICMP", normal: 5_200, attacks: 900 },
];

export const CATEGORY_RADAR: RadarMetricRow[] = [
  { metric: "Volume", dos: 100, probe: 41, r2l: 18, u2r: 6 },
  { metric: "Avg Confidence", dos: 96, probe: 92, r2l: 94, u2r: 97 },
  { metric: "Avg Risk", dos: 84, probe: 71, r2l: 88, u2r: 95 },
  { metric: "Persistence", dos: 78, probe: 65, r2l: 59, u2r: 88 },
  { metric: "Stealth", dos: 22, probe: 74, r2l: 91, u2r: 96 },
];

export interface TargetedServiceRow {
  name: string;
  ip: string;
  events: number;
  riskScore: number;
}

export const TOP_TARGETED_SERVICES: TargetedServiceRow[] = [
  { name: "web-prod-01", ip: "10.0.12.44", events: 412, riskScore: 88 },
  { name: "api-gw-02", ip: "10.0.12.9", events: 368, riskScore: 79 },
  { name: "db-primary", ip: "10.0.20.5", events: 246, riskScore: 92 },
  { name: "auth-svc-01", ip: "10.0.14.18", events: 218, riskScore: 74 },
  { name: "edge-node-03", ip: "10.0.8.71", events: 187, riskScore: 68 },
  { name: "internal-dns", ip: "10.0.1.2", events: 94, riskScore: 51 },
];

/* --------------------------------------------------------------------------
   ML intelligence
   -------------------------------------------------------------------------- */

export const MODEL_INFO = {
  name: "CyberShield Random Forest Classifier",
  version: "2.1.0",
  trainedAt: "2024-03-15",
  dataset: "NSL-KDD",
  trainRecords: 125_973,
  testRecords: 22_544,
  features: 41,
  framework: "Spark MLlib",
  estimator: "RandomForestClassifier",
  trees: 200,
  maxDepth: 24,
  classes: ["Normal", "DoS", "Probe", "R2L", "U2R"],
};

export interface ModelMetric {
  id: string;
  label: string;
  value: number;
  delta: string;
  color: string;
  description: string;
}

export const MODEL_METRICS: ModelMetric[] = [
  { id: "accuracy", label: "Accuracy", value: 96.7, delta: "+0.4", color: "#22d3ee", description: "Correct predictions across the held-out test set" },
  { id: "precision", label: "Precision", value: 95.2, delta: "+0.2", color: "#34d399", description: "Share of raised alerts that are true attacks" },
  { id: "recall", label: "Recall", value: 94.8, delta: "-0.1", color: "#a78bfa", description: "Share of true attacks successfully detected" },
  { id: "f1", label: "F1 Score", value: 95.0, delta: "+0.1", color: "#fbbf24", description: "Harmonic mean of precision and recall" },
];

export const CONFUSION_LABELS = ["Normal", "DoS", "Probe", "R2L", "U2R"];

/** Rows = actual class, columns = predicted class (test set, n = 22,544). */
export const CONFUSION_MATRIX: number[][] = [
  [9580, 42, 66, 18, 5],
  [88, 7300, 52, 12, 6],
  [132, 34, 2220, 28, 7],
  [122, 19, 46, 2540, 27],
  [11, 3, 4, 27, 155],
];

function computeClassPerformance(matrix: number[][], labels: string[]): ClassPerformanceRow[] {
  const rowTotals = matrix.map((row) => row.reduce((a, b) => a + b, 0));
  const colTotals = labels.map((_, c) => matrix.reduce((acc, row) => acc + row[c], 0));
  return labels.map((label, i) => {
    const tp = matrix[i][i];
    const precision = colTotals[i] === 0 ? 0 : (tp / colTotals[i]) * 100;
    const recall = rowTotals[i] === 0 ? 0 : (tp / rowTotals[i]) * 100;
    const f1 = precision + recall === 0 ? 0 : (2 * precision * recall) / (precision + recall);
    return {
      label,
      precision: round1(precision),
      recall: round1(recall),
      f1: round1(f1),
      support: rowTotals[i],
    };
  });
}

export const CLASS_PERFORMANCE: ClassPerformanceRow[] = computeClassPerformance(
  CONFUSION_MATRIX,
  CONFUSION_LABELS,
);

export const FEATURE_IMPORTANCE: FeatureImportanceRow[] = [
  { feature: "src_bytes", importance: 0.142 },
  { feature: "dst_bytes", importance: 0.118 },
  { feature: "count", importance: 0.098 },
  { feature: "srv_count", importance: 0.086 },
  { feature: "dst_host_srv_count", importance: 0.074 },
  { feature: "same_srv_rate", importance: 0.067 },
  { feature: "dst_host_same_srv_rate", importance: 0.061 },
  { feature: "dst_host_diff_srv_rate", importance: 0.055 },
  { feature: "hot", importance: 0.049 },
  { feature: "dst_host_srv_diff_host_rate", importance: 0.044 },
  { feature: "flag_SF", importance: 0.038 },
  { feature: "logged_in", importance: 0.034 },
  { feature: "serror_rate", importance: 0.031 },
  { feature: "dst_host_serror_rate", importance: 0.028 },
  { feature: "diff_srv_rate", importance: 0.025 },
];

const CONFIDENCE_BUCKET_LABELS = ["0-10", "10-20", "20-30", "30-40", "40-50", "50-60", "60-70", "70-80", "80-90", "90-100"];

const CONFIDENCE_COUNTS: Record<AttackCategory, number[]> = {
  normal: [310, 480, 760, 980, 1240, 1500, 1660, 1490, 880, 411],
  dos: [40, 60, 110, 180, 320, 480, 720, 1180, 2060, 2308],
  probe: [25, 40, 70, 110, 180, 260, 340, 420, 540, 436],
  r2l: [18, 30, 52, 88, 140, 210, 300, 420, 640, 856],
  u2r: [2, 4, 6, 10, 14, 20, 26, 32, 40, 46],
};

export const CONFIDENCE_DISTRIBUTION: ConfidenceBucketRow[] = CONFIDENCE_BUCKET_LABELS.map(
  (bucket, i) => ({
    bucket,
    normal: CONFIDENCE_COUNTS.normal[i],
    dos: CONFIDENCE_COUNTS.dos[i],
    probe: CONFIDENCE_COUNTS.probe[i],
    r2l: CONFIDENCE_COUNTS.r2l[i],
    u2r: CONFIDENCE_COUNTS.u2r[i],
  }),
);

export const INFERENCE_STATS: InfoItem[] = [
  { label: "p50 latency", value: "38 ms" },
  { label: "p95 latency", value: "112 ms" },
  { label: "Inference throughput", value: "24.6K ev/s" },
  { label: "Drift score (7d)", value: "0.03 · stable" },
  { label: "Last promotion", value: "2024-03-18" },
  { label: "Endpoint", value: "spark-mllib-serve:8080" },
];

/* --------------------------------------------------------------------------
   Data pipeline stages
   -------------------------------------------------------------------------- */

export const PIPELINE_STAGES: PipelineStage[] = [
  { id: "dataset", name: "NSL-KDD Dataset", role: "Historical attack corpus · raw source", icon: Database, status: "online", throughput: "batch load", latencyMs: 0, processed: 125_973, note: "KDDTrain+ · 41 features" },
  { id: "prepare", name: "Data Preparation", role: "Cleaning, encoding, SMOTE balancing", icon: Wrench, status: "online", throughput: "batch", latencyMs: 0, processed: 125_973, note: "label → 5 classes" },
  { id: "kafka", name: "Apache Kafka", role: "Durable event backbone · 12 partitions", icon: ArrowRightLeft, status: "online", throughput: "24.8K ev/s", latencyMs: 4, processed: 1_284_912, note: "consumer lag 1.2K" },
  { id: "spark", name: "Spark Streaming", role: "Micro-batch processing · 5s windows", icon: Zap, status: "warning", throughput: "24.6K ev/s", latencyMs: 42, processed: 1_284_860, note: "backpressure on batch 14" },
  { id: "features", name: "Feature Engineering", role: "41-feature vector assembly per flow", icon: Layers, status: "online", throughput: "24.6K ev/s", latencyMs: 6, processed: 1_284_860, note: "schema v2.1" },
  { id: "model", name: "ML Model", role: "Random Forest scoring · 200 trees", icon: Brain, status: "online", throughput: "23.9K ev/s", latencyMs: 18, processed: 1_284_712, note: "confidence ≥ 0.75" },
  { id: "detection", name: "Threat Detection", role: "Alert fan-out · severity classification", icon: ShieldAlert, status: "online", throughput: "3.2K scored/s", latencyMs: 12, processed: 3_847, note: "23 critical" },
  { id: "storage", name: "Redis / PostgreSQL", role: "Hot cache + durable alert store", icon: HardDrive, status: "online", throughput: "24.6K writes/s", latencyMs: 3, processed: 1_284_712, note: "TTL 6h hot cache" },
  { id: "api", name: "FastAPI Service", role: "REST + query API for analysts", icon: Server, status: "online", throughput: "1.4K req/s", latencyMs: 21, processed: 128_431, note: "p95 112 ms" },
  { id: "ws", name: "WebSocket Gateway", role: "Push channel · live event fan-out", icon: Radio, status: "online", throughput: "24.5K msg/s", latencyMs: 2, processed: 1_284_712, note: "42 clients" },
  { id: "dashboard", name: "CyberShield AI Dashboard", role: "This console · operator surface", icon: Monitor, status: "online", throughput: "live", latencyMs: 60, processed: 128_431, note: "render 60 fps" },
];

/* --------------------------------------------------------------------------
   System health
   -------------------------------------------------------------------------- */

const spark = (base: number, amp: number, drift = 0): number[] =>
  Array.from({ length: 30 }, (_, i) =>
    Math.max(1, Math.round(base + drift * i + (rng() - 0.5) * amp)),
  );

const bars = (warnings: number[] = [], offline: number[] = []): ServiceStatus[] =>
  Array.from({ length: 48 }, (_, i) =>
    offline.includes(i) ? "offline" : warnings.includes(i) ? "warning" : "online",
  );

export const SERVICE_HEALTH: ServiceHealthCard[] = [
  {
    id: "kafka",
    name: "Apache Kafka",
    icon: Network,
    status: "online",
    uptime: 99.98,
    summary: "3 brokers · 12 partitions · replication 3",
    metrics: [
      { label: "Messages/sec", value: "24.8K" },
      { label: "Partitions", value: "12" },
      { label: "Consumer lag", value: "1.2K" },
      { label: "Brokers", value: "3 / 3" },
    ],
    sparkline: spark(24.4, 2.6, 0.02),
    uptimeBars: bars([36, 37]),
  },
  {
    id: "spark",
    name: "Apache Spark",
    icon: Zap,
    status: "warning",
    uptime: 99.72,
    summary: "Structured Streaming · 5s micro-batches",
    metrics: [
      { label: "Active jobs", value: "8" },
      { label: "Executors", value: "24" },
      { label: "Batch time", value: "2.4 s" },
      { label: "Backlog", value: "1.1K" },
    ],
    sparkline: spark(2.2, 1.4, 0.02),
    uptimeBars: bars([40, 41, 42, 43, 44, 45, 46, 47]),
  },
  {
    id: "hdfs",
    name: "HDFS",
    icon: HardDrive,
    status: "warning",
    uptime: 99.81,
    summary: "4 data nodes · storage pressure on dn-03",
    metrics: [
      { label: "Used", value: "3.8 / 5.0 TB" },
      { label: "Replication", value: "3x" },
      { label: "Blocks", value: "218K" },
      { label: "Nodes", value: "4 / 4" },
    ],
    sparkline: spark(76, 4, 0.06),
    uptimeBars: bars([38, 39, 40, 44, 45, 46, 47]),
  },
  {
    id: "fastapi",
    name: "FastAPI",
    icon: Server,
    status: "online",
    uptime: 99.99,
    summary: "REST + WebSocket API · uvicorn 4 workers",
    metrics: [
      { label: "Requests/sec", value: "1.4K" },
      { label: "Avg latency", value: "21 ms" },
      { label: "Error rate", value: "0.02%" },
      { label: "Workers", value: "4 / 4" },
    ],
    sparkline: spark(21, 6, -0.04),
    uptimeBars: bars(),
  },
  {
    id: "postgres",
    name: "PostgreSQL",
    icon: Database,
    status: "online",
    uptime: 100,
    summary: "Primary alert + case store · streamed replica",
    metrics: [
      { label: "Connections", value: "42 / 200" },
      { label: "Query time", value: "8 ms" },
      { label: "Tables", value: "36" },
      { label: "Size", value: "12.4 GB" },
    ],
    sparkline: spark(42, 8, 0.1),
    uptimeBars: bars(),
  },
  {
    id: "redis",
    name: "Redis",
    icon: MemoryStick,
    status: "online",
    uptime: 99.97,
    summary: "Hot cache for enriched events",
    metrics: [
      { label: "Memory", value: "412 / 1024 MB" },
      { label: "Keys", value: "218K" },
      { label: "Hit rate", value: "99.2%" },
      { label: "Ops/sec", value: "31.2K" },
    ],
    sparkline: spark(410, 22, 0.6),
    uptimeBars: bars([18]),
  },
  {
    id: "websocket",
    name: "WebSocket Gateway",
    icon: Radio,
    status: "online",
    uptime: 99.99,
    summary: "Live fan-out to operator consoles",
    metrics: [
      { label: "Connections", value: "42" },
      { label: "Messages/sec", value: "24.5K" },
      { label: "Uptime", value: "31d 4h" },
      { label: "Reconnects", value: "3" },
    ],
    sparkline: spark(42, 10, 0.02),
    uptimeBars: bars(),
  },
];

export const HEALTH_SUMMARY: InfoItem[] = [
  { label: "Platform uptime (30d)", value: "99.94%" },
  { label: "Services reporting", value: "7 / 7" },
  { label: "Active incidents", value: "1" },
  { label: "MTTR (30d)", value: "38 min" },
];

export const INCIDENTS: IncidentEntry[] = [
  { id: "INC-2214", time: iso(BASE_TIME - 6 * HOUR), service: "Kafka", title: "Consumer lag spike on broker-2 (group: spark-detector)", status: "resolved", severity: "medium" },
  { id: "INC-2211", time: iso(BASE_TIME - 11 * HOUR), service: "Spark", title: "Executor OOM on partition 14/22 - job retried", status: "resolved", severity: "high" },
  { id: "INC-2210", time: iso(BASE_TIME - 15 * HOUR), service: "HDFS", title: "Volume over 80% on dn-03 - rebalance scheduled", status: "ongoing", severity: "medium" },
  { id: "INC-2204", time: iso(BASE_TIME - 30 * HOUR), service: "FastAPI", title: "p95 latency above 400ms for 12 minutes", status: "resolved", severity: "low" },
  { id: "INC-2198", time: iso(BASE_TIME - 52 * HOUR), service: "WebSocket", title: "Reconnect storm - 12 clients in 90 seconds", status: "resolved", severity: "medium" },
];

/* --------------------------------------------------------------------------
   Investigations
   -------------------------------------------------------------------------- */

export const INVESTIGATIONS: InvestigationRecord[] = [
  {
    id: "INV-2026-041",
    title: "Coordinated DoS burst against edge nodes",
    severity: "critical",
    category: "dos",
    analyst: "Priya Nair",
    team: "Threat Response",
    status: "in_progress",
    createdAt: iso(BASE_TIME - 31 * HOUR),
    updatedAt: iso(BASE_TIME - 42 * MINUTE),
    relatedAlerts: 6,
    riskScore: 93,
    confidence: 0.97,
    summary:
      "Sustained SYN flood from SIM-SRC-104 and SIM-SRC-231 targeting edge-node-03 and web-prod-01. Peak of 41 MB/s against a 4 MB/s baseline; connection table hit 92% occupancy before upstream rate limits engaged.",
    findings: [
      { time: iso(BASE_TIME - 42 * MINUTE), note: "Upstream scrubber rule validated - attack traffic dropped 94%" },
      { time: iso(BASE_TIME - 3 * HOUR), note: "Two source hosts correlated to the same ASN block" },
      { time: iso(BASE_TIME - 9 * HOUR), note: "neptune signature confirmed on 1,284 events" },
      { time: iso(BASE_TIME - 31 * HOUR), note: "Case opened from auto-escalation (6 linked critical alerts)" },
    ],
  },
  {
    id: "INV-2026-039",
    title: "Repeated SSH credential stuffing from SIM-SRC-104",
    severity: "high",
    category: "r2l",
    analyst: "Marcus Lee",
    team: "Threat Response",
    status: "open",
    createdAt: iso(BASE_TIME - 19 * HOUR),
    updatedAt: iso(BASE_TIME - 2 * HOUR),
    relatedAlerts: 4,
    riskScore: 84,
    confidence: 0.93,
    summary:
      "guess_passwd pattern with 6+ failed logins per minute against auth-svc-01. Source rotates user agents but reuses two /24 blocks. No successful authentication observed so far.",
    findings: [
      { time: iso(BASE_TIME - 2 * HOUR), note: "Wordlist fingerprint matches known credential dump (2024-Q1)" },
      { time: iso(BASE_TIME - 7 * HOUR), note: "Fail2ban threshold lowered to 4 attempts for auth-svc-01" },
      { time: iso(BASE_TIME - 19 * HOUR), note: "Case opened from triage queue - 4 related alerts" },
    ],
  },
  {
    id: "INV-2026-036",
    title: "Internal port sweep - NODE-028 range scan",
    severity: "medium",
    category: "probe",
    analyst: "Ade Okafor",
    team: "Detection Engineering",
    status: "open",
    createdAt: iso(BASE_TIME - 13 * HOUR),
    updatedAt: iso(BASE_TIME - 5 * HOUR),
    relatedAlerts: 3,
    riskScore: 68,
    confidence: 0.9,
    summary:
      "nmap-style sweep across 10.0.8.0/24 from an internal node. Possibly a rogue inventory scanner; asset owner confirmation pending. Scanning rate stayed below rate-limits by design.",
    findings: [
      { time: iso(BASE_TIME - 5 * HOUR), note: "Asset owner contacted - awaiting scan-tool authorization proof" },
      { time: iso(BASE_TIME - 10 * HOUR), note: "1,024 unique destination ports observed in 90 seconds" },
      { time: iso(BASE_TIME - 13 * HOUR), note: "Case opened from probe cluster detection" },
    ],
  },
  {
    id: "INV-2026-031",
    title: "Kernel exploit attempt on db-primary (buffer_overflow)",
    severity: "critical",
    category: "u2r",
    analyst: "Sana Verma",
    team: "Threat Response",
    status: "closed",
    createdAt: iso(BASE_TIME - 76 * HOUR),
    updatedAt: iso(BASE_TIME - 50 * HOUR),
    relatedAlerts: 2,
    riskScore: 97,
    confidence: 0.96,
    summary:
      "Buffer overflow payload delivered to a legacy RPC service (CVE-2021-3156 pattern). Patch was already deployed; exploit failed at the syscall gate and the host was rebuilt from golden image.",
    findings: [
      { time: iso(BASE_TIME - 50 * HOUR), note: "Case closed - host rebuilt from golden image, no persistence found" },
      { time: iso(BASE_TIME - 60 * HOUR), note: "Forensics: exploit aborted at setuid gate" },
      { time: iso(BASE_TIME - 76 * HOUR), note: "Case opened - critical ML classification (conf 0.96)" },
    ],
  },
  {
    id: "INV-2026-028",
    title: "Anomalous ICMP tunneling between edge and core",
    severity: "high",
    category: "probe",
    analyst: "Jon Alvarez",
    team: "Detection Engineering",
    status: "closed",
    createdAt: iso(BASE_TIME - 102 * HOUR),
    updatedAt: iso(BASE_TIME - 88 * HOUR),
    relatedAlerts: 5,
    riskScore: 81,
    confidence: 0.88,
    summary:
      "Large ICMP echo payloads (1,400+ bytes) between edge-node-03 and db-primary over 40 minutes. Traffic engineered to bypass egress filters; blocked and logged. Root cause traced to a misconfigured monitoring probe.",
    findings: [
      { time: iso(BASE_TIME - 88 * HOUR), note: "Case closed - misconfigured monitoring probe confirmed with owner" },
      { time: iso(BASE_TIME - 94 * HOUR), note: "ICMP tunneling route blocked at core firewall" },
      { time: iso(BASE_TIME - 102 * HOUR), note: "Case opened from anomaly detector escalation" },
    ],
  },
];
