import type { SeverityLevel } from "@/types";

/* --------------------------------------------------------------------------
   Network topology taxonomy
   -------------------------------------------------------------------------- */

/**
 * Risk scale for the 3D topology. Deliberately coarser than the alert
 * `ThreatLevel` scale - it drives node color, glow intensity, and the
 * behavioral filters on the Live Network page.
 */
export type RiskLevel = "normal" | "suspicious" | "high" | "critical";

/** Visual archetype of a topology node - maps to a Three.js primitive. */
export type NodeType =
  | "server"
  | "endpoint"
  | "router"
  | "gateway"
  | "database"
  | "cloud"
  | "firewall";

/** Behavioral filter applied by the scene control bar. */
export type RiskFilter = "all" | "suspicious" | "high" | "critical";

/* --------------------------------------------------------------------------
   Topology entities
   -------------------------------------------------------------------------- */

/** One asset in the stylized enterprise network. */
export interface NetworkNode {
  id: string;
  name: string;
  type: NodeType;
  position: [number, number, number];
  riskLevel: RiskLevel;
  trafficVolume: number;
  connections: string[]; // IDs of connected nodes
  alerts: number;
  riskScore: number;
}

/** One observed flow between two assets. */
export interface NetworkConnection {
  id: string;
  source: string;
  target: string;
  protocol: string;
  eventCount: number;
  riskLevel: RiskLevel;
  prediction: string;
  confidence: number;
}

/** A live packet visualization traveling along a connection path. */
export interface NetworkParticle {
  id: string;
  connectionId: string;
  progress: number; // 0-1 along the connection path
  type: "normal" | "suspicious" | "attack";
  speed: number;
}

/* --------------------------------------------------------------------------
   Derived view models (detail panels, overlays)
   -------------------------------------------------------------------------- */

/** A triaged alert attached to a node, rendered in the detail panel. */
export interface NodeAlert {
  id: string;
  title: string;
  severity: SeverityLevel;
  timestamp: string;
  source: string;
}

/** Aggregate figures rendered in the scene stats overlay. */
export interface NetworkStats {
  totalNodes: number;
  activeConnections: number;
  criticalThreats: number;
  anomalies: number;
}
