import type { SeverityLevel, ThreatLevel } from "@/types";
import type {
  NetworkConnection,
  NetworkNode,
  NetworkStats,
  NodeAlert,
  RiskFilter,
  RiskLevel,
} from "@/types/network";

/* --------------------------------------------------------------------------
   Risk tokens - single source of truth for every risk-colored surface
   (3D materials, HTML overlays, panels, legend).
   -------------------------------------------------------------------------- */

/** Fill color per risk level, matched to the 3D glow palette. */
export const RISK_COLORS: Record<RiskLevel, string> = {
  normal: "#06b6d4",
  suspicious: "#eab308",
  high: "#f97316",
  critical: "#ef4444",
};

/** Brightened accent per risk level - used for edges, labels, and text. */
export const RISK_ACCENTS: Record<RiskLevel, string> = {
  normal: "#67e8f9",
  suspicious: "#fde047",
  high: "#fdba74",
  critical: "#fca5a5",
};

/** Human label per risk level. */
export const RISK_LABELS: Record<RiskLevel, string> = {
  normal: "Normal",
  suspicious: "Suspicious",
  high: "High Risk",
  critical: "Critical",
};

/** Severity ordering - higher index = more severe. */
export const RISK_ORDER: Record<RiskLevel, number> = {
  normal: 0,
  suspicious: 1,
  high: 2,
  critical: 3,
};

/** Minimum risk level required by each filter option. */
const FILTER_THRESHOLDS: Record<RiskFilter, number> = {
  all: -1,
  suspicious: RISK_ORDER.suspicious,
  high: RISK_ORDER.high,
  critical: RISK_ORDER.critical,
};

/** Does `level` pass the active behavioral filter? */
export function passesRiskFilter(level: RiskLevel, filter: RiskFilter): boolean {
  return RISK_ORDER[level] >= FILTER_THRESHOLDS[filter];
}

/** Map the coarse risk scale onto the alert severity scale (badges). */
export function riskToSeverity(level: RiskLevel): SeverityLevel {
  const map: Record<RiskLevel, SeverityLevel> = {
    normal: "low",
    suspicious: "medium",
    high: "high",
    critical: "critical",
  };
  return map[level];
}

/* --------------------------------------------------------------------------
   Mock enterprise topology - layered architecture.
   Vertical strata (top -> bottom): cloud -> firewalls -> core routers ->
   servers -> databases -> endpoints. ~18 assets, ~31 flows.
   -------------------------------------------------------------------------- */

export const NETWORK_NODES: NetworkNode[] = [
  {
    id: "cloud-gw",
    name: "Cloud Gateway",
    type: "gateway",
    position: [0, 12.5, 0],
    riskLevel: "normal",
    trafficVolume: 9840,
    connections: ["fw-edge-1", "fw-edge-2"],
    alerts: 0,
    riskScore: 12,
  },
  {
    id: "fw-edge-1",
    name: "Edge Firewall A",
    type: "firewall",
    position: [-9, 8.5, 4],
    riskLevel: "normal",
    trafficVolume: 6210,
    connections: ["cloud-gw", "rtr-core-1", "rtr-core-2"],
    alerts: 1,
    riskScore: 22,
  },
  {
    id: "fw-edge-2",
    name: "Edge Firewall B",
    type: "firewall",
    position: [9, 8.5, -4],
    riskLevel: "suspicious",
    trafficVolume: 5430,
    connections: ["cloud-gw", "rtr-core-1", "rtr-core-3", "ep-mob-06"],
    alerts: 3,
    riskScore: 58,
  },
  {
    id: "rtr-core-1",
    name: "Core Router 1",
    type: "router",
    position: [0, 4.5, 0],
    riskLevel: "normal",
    trafficVolume: 14200,
    connections: ["fw-edge-1", "fw-edge-2", "srv-web-1", "srv-app-1"],
    alerts: 0,
    riskScore: 15,
  },
  {
    id: "rtr-core-2",
    name: "Core Router 2",
    type: "router",
    position: [-12, 3.8, -7],
    riskLevel: "normal",
    trafficVolume: 11350,
    connections: ["fw-edge-1", "srv-web-1", "srv-mail-1", "ep-ws-01", "ep-ws-02"],
    alerts: 1,
    riskScore: 24,
  },
  {
    id: "rtr-core-3",
    name: "Core Router 3",
    type: "router",
    position: [12, 3.8, 7],
    riskLevel: "suspicious",
    trafficVolume: 9870,
    connections: ["fw-edge-2", "srv-app-1", "srv-file-1", "ep-ws-03", "ep-ws-04", "ep-ws-05"],
    alerts: 2,
    riskScore: 47,
  },
  {
    id: "srv-web-1",
    name: "Web Server",
    type: "server",
    position: [-7, 0, 5],
    riskLevel: "normal",
    trafficVolume: 7420,
    connections: ["rtr-core-1", "rtr-core-2", "srv-app-1", "db-pg-1", "ep-ws-01"],
    alerts: 1,
    riskScore: 18,
  },
  {
    id: "srv-app-1",
    name: "App Server",
    type: "server",
    position: [0, 0, -1.5],
    riskLevel: "suspicious",
    trafficVolume: 6890,
    connections: ["rtr-core-1", "rtr-core-3", "srv-web-1", "db-pg-1", "db-redis-1", "srv-file-1", "ep-ws-02", "ep-ws-05"],
    alerts: 3,
    riskScore: 61,
  },
  {
    id: "srv-mail-1",
    name: "Mail Server",
    type: "server",
    position: [-4, 0, -7],
    riskLevel: "normal",
    trafficVolume: 3980,
    connections: ["rtr-core-2", "db-redis-1", "ep-ws-03"],
    alerts: 0,
    riskScore: 14,
  },
  {
    id: "srv-file-1",
    name: "File Server",
    type: "server",
    position: [7, 0, 0.5],
    riskLevel: "high",
    trafficVolume: 5120,
    connections: ["rtr-core-3", "srv-app-1", "db-pg-1", "ep-ws-04"],
    alerts: 5,
    riskScore: 76,
  },
  {
    id: "db-pg-1",
    name: "PostgreSQL Cluster",
    type: "database",
    position: [4, -3.5, -5.5],
    riskLevel: "critical",
    trafficVolume: 8340,
    connections: ["srv-web-1", "srv-app-1", "srv-file-1"],
    alerts: 7,
    riskScore: 88,
  },
  {
    id: "db-redis-1",
    name: "Redis Cache",
    type: "database",
    position: [-8, -3.5, -2],
    riskLevel: "normal",
    trafficVolume: 5600,
    connections: ["srv-app-1", "srv-mail-1"],
    alerts: 0,
    riskScore: 20,
  },
  {
    id: "ep-ws-01",
    name: "Workstation 01",
    type: "endpoint",
    position: [-14, -7, 3],
    riskLevel: "normal",
    trafficVolume: 1240,
    connections: ["rtr-core-2"],
    alerts: 0,
    riskScore: 9,
  },
  {
    id: "ep-ws-02",
    name: "Workstation 02",
    type: "endpoint",
    position: [-7, -7.5, -8],
    riskLevel: "normal",
    trafficVolume: 1620,
    connections: ["rtr-core-2", "srv-app-1"],
    alerts: 0,
    riskScore: 12,
  },
  {
    id: "ep-ws-03",
    name: "Workstation 03",
    type: "endpoint",
    position: [2, -7, 8],
    riskLevel: "suspicious",
    trafficVolume: 2890,
    connections: ["rtr-core-3", "srv-mail-1"],
    alerts: 2,
    riskScore: 55,
  },
  {
    id: "ep-ws-04",
    name: "Workstation 04",
    type: "endpoint",
    position: [6, -7.5, -9],
    riskLevel: "critical",
    trafficVolume: 7420,
    connections: ["rtr-core-3", "srv-file-1"],
    alerts: 6,
    riskScore: 92,
  },
  {
    id: "ep-ws-05",
    name: "Workstation 05",
    type: "endpoint",
    position: [15, -7, 1],
    riskLevel: "normal",
    trafficVolume: 980,
    connections: ["rtr-core-3", "srv-app-1"],
    alerts: 0,
    riskScore: 8,
  },
  {
    id: "ep-mob-06",
    name: "Branch Laptop 06",
    type: "endpoint",
    position: [19, -6.5, -6],
    riskLevel: "high",
    trafficVolume: 3510,
    connections: ["fw-edge-2"],
    alerts: 3,
    riskScore: 71,
  },
];

export const NETWORK_CONNECTIONS: NetworkConnection[] = [
  /* Cloud / firewall tier */
  { id: "cnx-01", source: "cloud-gw", target: "fw-edge-1", protocol: "HTTPS", eventCount: 48200, riskLevel: "normal", prediction: "TLS session", confidence: 99 },
  { id: "cnx-02", source: "cloud-gw", target: "fw-edge-2", protocol: "HTTPS", eventCount: 39100, riskLevel: "normal", prediction: "TLS session", confidence: 98 },
  { id: "cnx-03", source: "fw-edge-1", target: "rtr-core-1", protocol: "TCP", eventCount: 52300, riskLevel: "normal", prediction: "Allowed flow", confidence: 99 },
  { id: "cnx-04", source: "fw-edge-1", target: "rtr-core-2", protocol: "TCP", eventCount: 31800, riskLevel: "normal", prediction: "Allowed flow", confidence: 97 },
  { id: "cnx-05", source: "fw-edge-2", target: "rtr-core-1", protocol: "TCP", eventCount: 28700, riskLevel: "suspicious", prediction: "Malformed packet burst", confidence: 66 },
  { id: "cnx-06", source: "fw-edge-2", target: "rtr-core-3", protocol: "TCP", eventCount: 22100, riskLevel: "normal", prediction: "Allowed flow", confidence: 95 },
  /* Router tier */
  { id: "cnx-07", source: "rtr-core-1", target: "srv-web-1", protocol: "TCP", eventCount: 19400, riskLevel: "normal", prediction: "HTTP session", confidence: 98 },
  { id: "cnx-08", source: "rtr-core-1", target: "srv-app-1", protocol: "TCP", eventCount: 16200, riskLevel: "normal", prediction: "HTTP session", confidence: 96 },
  { id: "cnx-09", source: "rtr-core-2", target: "srv-web-1", protocol: "TCP", eventCount: 8300, riskLevel: "normal", prediction: "HTTP session", confidence: 97 },
  { id: "cnx-10", source: "rtr-core-2", target: "srv-mail-1", protocol: "TCP", eventCount: 6400, riskLevel: "normal", prediction: "SMTP relay", confidence: 97 },
  { id: "cnx-11", source: "rtr-core-3", target: "srv-app-1", protocol: "TCP", eventCount: 9100, riskLevel: "suspicious", prediction: "Unusual port sweep", confidence: 71 },
  { id: "cnx-12", source: "rtr-core-3", target: "srv-file-1", protocol: "TCP", eventCount: 7800, riskLevel: "normal", prediction: "SMB transfer", confidence: 94 },
  /* Server tier */
  { id: "cnx-13", source: "srv-web-1", target: "srv-app-1", protocol: "HTTP", eventCount: 12400, riskLevel: "normal", prediction: "API calls", confidence: 98 },
  { id: "cnx-14", source: "srv-web-1", target: "db-pg-1", protocol: "TCP", eventCount: 5600, riskLevel: "normal", prediction: "Query stream", confidence: 96 },
  { id: "cnx-15", source: "srv-app-1", target: "db-pg-1", protocol: "TCP", eventCount: 14200, riskLevel: "high", prediction: "SQL injection attempts", confidence: 84 },
  { id: "cnx-16", source: "srv-app-1", target: "db-redis-1", protocol: "TCP", eventCount: 18700, riskLevel: "normal", prediction: "Cache operations", confidence: 98 },
  { id: "cnx-17", source: "srv-app-1", target: "srv-file-1", protocol: "TCP", eventCount: 5900, riskLevel: "suspicious", prediction: "Abnormal upload volume", confidence: 68 },
  { id: "cnx-18", source: "srv-mail-1", target: "db-redis-1", protocol: "TCP", eventCount: 2100, riskLevel: "normal", prediction: "Queue sync", confidence: 95 },
  { id: "cnx-19", source: "srv-file-1", target: "db-pg-1", protocol: "TCP", eventCount: 4300, riskLevel: "high", prediction: "Data staging activity", confidence: 79 },
  { id: "cnx-20", source: "srv-file-1", target: "ep-ws-04", protocol: "SMB", eventCount: 6200, riskLevel: "critical", prediction: "Bulk data exfiltration", confidence: 93 },
  /* Endpoint tier */
  { id: "cnx-21", source: "srv-app-1", target: "ep-ws-02", protocol: "TCP", eventCount: 2400, riskLevel: "normal", prediction: "Developer session", confidence: 94 },
  { id: "cnx-22", source: "srv-app-1", target: "ep-ws-05", protocol: "TCP", eventCount: 1900, riskLevel: "normal", prediction: "API session", confidence: 96 },
  { id: "cnx-23", source: "ep-ws-01", target: "rtr-core-2", protocol: "UDP", eventCount: 1400, riskLevel: "normal", prediction: "DNS queries", confidence: 97 },
  { id: "cnx-24", source: "ep-ws-02", target: "rtr-core-2", protocol: "TCP", eventCount: 2600, riskLevel: "normal", prediction: "VPN session", confidence: 96 },
  { id: "cnx-25", source: "ep-ws-03", target: "rtr-core-3", protocol: "UDP", eventCount: 3100, riskLevel: "suspicious", prediction: "Beaconing pattern (5s interval)", confidence: 74 },
  { id: "cnx-26", source: "ep-ws-04", target: "rtr-core-3", protocol: "TCP", eventCount: 8900, riskLevel: "high", prediction: "Port scan sweep", confidence: 87 },
  { id: "cnx-27", source: "ep-ws-05", target: "rtr-core-3", protocol: "TCP", eventCount: 1200, riskLevel: "normal", prediction: "Intranet browsing", confidence: 97 },
  { id: "cnx-28", source: "ep-mob-06", target: "fw-edge-2", protocol: "HTTPS", eventCount: 4400, riskLevel: "high", prediction: "Periodic C2 beacon", confidence: 82 },
  { id: "cnx-29", source: "ep-ws-03", target: "srv-mail-1", protocol: "TCP", eventCount: 800, riskLevel: "normal", prediction: "Mail client", confidence: 95 },
  { id: "cnx-30", source: "ep-ws-01", target: "srv-web-1", protocol: "TCP", eventCount: 1500, riskLevel: "normal", prediction: "HTTPS browsing", confidence: 96 },
];

/* --------------------------------------------------------------------------
   Lookup helpers
   -------------------------------------------------------------------------- */

const NODE_INDEX = new Map<string, NetworkNode>(
  NETWORK_NODES.map((node) => [node.id, node]),
);

/** Resolve a node by id (undefined for unknown ids). */
export function getNodeById(id: string): NetworkNode | undefined {
  return NODE_INDEX.get(id);
}

/** All flows touching the given node. */
export function getConnectionsForNode(nodeId: string): NetworkConnection[] {
  return NETWORK_CONNECTIONS.filter(
    (connection) =>
      connection.source === nodeId || connection.target === nodeId,
  );
}

/** Aggregate overlay figures derived from the mock topology. */
export function computeNetworkStats(): NetworkStats {
  return {
    totalNodes: NETWORK_NODES.length,
    activeConnections: NETWORK_CONNECTIONS.length,
    criticalThreats: NETWORK_CONNECTIONS.filter(
      (c) => c.riskLevel === "high" || c.riskLevel === "critical",
    ).length,
    anomalies: NETWORK_CONNECTIONS.filter(
      (c) => c.riskLevel === "suspicious",
    ).length,
  };
}

/* --------------------------------------------------------------------------
   Detail panel view models (deterministic - seeded by node / flow id)
   -------------------------------------------------------------------------- */

/** djb2 string hash - stable seed for the deterministic mock generators. */
export function hashString(value: string): number {
  let hash = 5381;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 33) ^ value.charCodeAt(i);
  }
  return hash >>> 0;
}

/** mulberry32 PRNG - same seed, same sequence, every render. */
export function mulberry32(seed: number): () => number {
  let state = seed;
  return () => {
    state |= 0;
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const ALERT_TIME_SLOTS = ["2m ago", "14m ago", "38m ago", "1h 04m ago"];

const BENIGN_ALERTS: Array<{ title: string; severity: ThreatLevel }> = [
  { title: "TLS certificate rotation verified", severity: "info" as ThreatLevel },
  { title: "Configuration backup completed", severity: "info" as ThreatLevel },
  { title: "Intrusion policy sync succeeded", severity: "info" as ThreatLevel },
];

/**
 * Recent alerts for a node: every suspicious-or-worse flow touching the node
 * becomes a triaged alert (most severe first), padded with benign
 * operational notices so the feed always renders three entries.
 */
export function getNodeAlerts(nodeId: string): NodeAlert[] {
  const node = getNodeById(nodeId);
  if (!node) return [];

  const flagged = getConnectionsForNode(nodeId)
    .filter((connection) => connection.riskLevel !== "normal")
    .sort(
      (a, b) => RISK_ORDER[b.riskLevel] - RISK_ORDER[a.riskLevel],
    )
    .slice(0, 4)
    .map((connection, index) => {
      const peerId =
        connection.source === nodeId ? connection.target : connection.source;
      const peer = getNodeById(peerId);
      return {
        id: `${connection.id}-alert`,
        title: connection.prediction,
        severity: riskToSeverity(connection.riskLevel),
        timestamp: ALERT_TIME_SLOTS[index % ALERT_TIME_SLOTS.length],
        source: peer?.name ?? peerId,
      };
    });

  const alerts = [...flagged];
  let benignIndex = 0;
  while (alerts.length < 3) {
    const benign = BENIGN_ALERTS[benignIndex % BENIGN_ALERTS.length];
    alerts.push({
      id: `${nodeId}-benign-${benignIndex}`,
      title: benign.title,
      severity: `${benign.severity}` as SeverityLevel,
      timestamp: ALERT_TIME_SLOTS[alerts.length % ALERT_TIME_SLOTS.length],
      source: "System",
    });
    benignIndex += 1;
  }
  return alerts;
}

/**
 * 24-point traffic trend for the detail-panel sparkline. A seeded random walk
 * around the node's traffic volume with an upward drift for risky nodes.
 */
export function getTrafficTrend(node: NetworkNode, points = 24): number[] {
  const random = mulberry32(hashString(node.id));
  const base = node.trafficVolume;
  const drift =
    (RISK_ORDER[node.riskLevel] / RISK_ORDER.critical) * base * 0.012;
  let value = base * 0.62;

  const trend: number[] = [];
  for (let i = 0; i < points; i += 1) {
    value += (random() - 0.48) * base * 0.14 + drift;
    value = Math.min(Math.max(value, base * 0.3), base * 1.28);
    trend.push(Math.round(value));
  }
  return trend;
}

/** Deterministic "last observed" stamp for a connection detail panel. */
export function getConnectionTimestampHint(connectionId: string): string {
  const random = mulberry32(hashString(connectionId));
  const minutes = Math.floor(random() * 4);
  const seconds = Math.floor(random() * 60);
  if (minutes === 0) return `${seconds + 8}s ago`;
  return `${minutes}m ${String(seconds).padStart(2, "0")}s ago`;
}
