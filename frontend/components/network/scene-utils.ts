import * as THREE from "three";
import type { NodeType, RiskLevel } from "@/types/network";

/* --------------------------------------------------------------------------
   Scene constants - shared by the canvas, camera rig, and overlays.
   -------------------------------------------------------------------------- */

/** Canvas clear color + fog color (matches the app's `cyber.bg` token). */
export const SCENE_BG = "#04070f";

/** Default camera framing - a high three-quarter view of the topology. */
export const DEFAULT_CAMERA_POSITION: [number, number, number] = [21, 23, 31];

/** Default orbit pivot - the middle of the network's vertical strata. */
export const DEFAULT_CAMERA_TARGET: [number, number, number] = [0, 1.6, 0];

/** Orbit distance the camera settles at when flying to a node. */
export const FOCUS_CAMERA_DISTANCE = 15;

/* --------------------------------------------------------------------------
   Per-node-type visual configuration
   -------------------------------------------------------------------------- */

export interface NodeVisualConfig {
  /** Radius of the invisible hover/click capture sphere. */
  hitRadius: number;
  /** Vertical offset (world units) of the HTML name label below the node. */
  labelOffset: number;
  /** Diameter of the additive glow sprite behind the node. */
  glowScale: number;
  /** Height used to place tooltips above the geometry. */
  tooltipOffset: number;
}

export const NODE_VISUALS: Record<NodeType, NodeVisualConfig> = {
  server: { hitRadius: 1.5, labelOffset: 1.75, glowScale: 4.8, tooltipOffset: 2.1 },
  endpoint: { hitRadius: 1.15, labelOffset: 1.3, glowScale: 3.2, tooltipOffset: 1.7 },
  router: { hitRadius: 1.5, labelOffset: 1.8, glowScale: 4.6, tooltipOffset: 2.2 },
  gateway: { hitRadius: 1.6, labelOffset: 2.7, glowScale: 5.4, tooltipOffset: 3.2 },
  database: { hitRadius: 1.5, labelOffset: 2.0, glowScale: 4.6, tooltipOffset: 2.4 },
  cloud: { hitRadius: 1.9, labelOffset: 2.1, glowScale: 5.8, tooltipOffset: 2.5 },
  firewall: { hitRadius: 1.7, labelOffset: 2.0, glowScale: 5.2, tooltipOffset: 2.4 },
};

/* --------------------------------------------------------------------------
   Per-risk visual configuration - glow intensity, pulse cadence, flow speed.
   -------------------------------------------------------------------------- */

export interface RiskVisualConfig {
  /** Base emissive intensity of node materials. */
  emissive: number;
  /** Angular speed of the pulse oscillation (rad/s). */
  pulseSpeed: number;
  /** Amplitude of the emissive pulse. */
  pulseAmp: number;
  /** Dash-offset speed along connection lines (units/s). */
  flowSpeed: number;
  /** Connection line width in pixels. */
  lineWidth: number;
  /** Connection line base opacity. */
  lineOpacity: number;
  /** Expanding ground-ring effect tier. */
  ring: "none" | "soft" | "strong";
  /** Seconds per expanding-ring cycle. */
  ringPeriod: number;
}

export const RISK_VISUALS: Record<RiskLevel, RiskVisualConfig> = {
  normal: {
    emissive: 0.85,
    pulseSpeed: 0.9,
    pulseAmp: 0.18,
    flowSpeed: 0.35,
    lineWidth: 1.4,
    lineOpacity: 0.3,
    ring: "none",
    ringPeriod: 4,
  },
  suspicious: {
    emissive: 1.15,
    pulseSpeed: 1.6,
    pulseAmp: 0.42,
    flowSpeed: 0.6,
    lineWidth: 1.8,
    lineOpacity: 0.5,
    ring: "none",
    ringPeriod: 3.5,
  },
  high: {
    emissive: 1.5,
    pulseSpeed: 2.3,
    pulseAmp: 0.58,
    flowSpeed: 0.95,
    lineWidth: 2.4,
    lineOpacity: 0.72,
    ring: "soft",
    ringPeriod: 3,
  },
  critical: {
    emissive: 1.9,
    pulseSpeed: 3,
    pulseAmp: 0.72,
    flowSpeed: 1.5,
    lineWidth: 3,
    lineOpacity: 1,
    ring: "strong",
    ringPeriod: 1.8,
  },
};

/* --------------------------------------------------------------------------
   Color helpers
   -------------------------------------------------------------------------- */

const WHITE = new THREE.Color("#ffffff");

/** Lighten a hex color toward white - edges, cores, and highlight states. */
export function brightenColor(hex: string, amount: number): THREE.Color {
  return new THREE.Color(hex).lerp(WHITE, amount);
}

/** Darken a hex color toward the scene background - dimmed (filtered) state. */
export function dimColor(hex: string, amount: number): THREE.Color {
  return new THREE.Color(hex).lerp(new THREE.Color(SCENE_BG), amount);
}

/* --------------------------------------------------------------------------
   Connection curve math - one shared arc for lines, particles, and hit areas.
   -------------------------------------------------------------------------- */

/** Control point of the quadratic arc: chord midpoint bowed upward. */
export function connectionControlPoint(
  start: THREE.Vector3,
  end: THREE.Vector3,
  out: THREE.Vector3,
): THREE.Vector3 {
  out.addVectors(start, end).multiplyScalar(0.5);
  out.y += 0.65 + start.distanceTo(end) * 0.05;
  return out;
}

/**
 * Point on a quadratic bezier at parameter `t` (0-1). Writes into `out` so
 * the render loop can stay allocation-free.
 */
export function quadraticPoint(
  start: THREE.Vector3,
  control: THREE.Vector3,
  end: THREE.Vector3,
  t: number,
  out: THREE.Vector3,
): THREE.Vector3 {
  const it = 1 - t;
  const w0 = it * it;
  const w1 = 2 * it * t;
  const w2 = t * t;
  out.x = start.x * w0 + control.x * w1 + end.x * w2;
  out.y = start.y * w0 + control.y * w1 + end.y * w2;
  out.z = start.z * w0 + control.z * w1 + end.z * w2;
  return out;
}

/** Sample the full quadratic arc as a point list (for the drei `Line`). */
export function sampleConnectionCurve(
  start: THREE.Vector3,
  end: THREE.Vector3,
  segments = 20,
): THREE.Vector3[] {
  const control = connectionControlPoint(start, end, new THREE.Vector3());
  const points: THREE.Vector3[] = [];
  for (let i = 0; i <= segments; i += 1) {
    points.push(
      quadraticPoint(start, control, end, i / segments, new THREE.Vector3()),
    );
  }
  return points;
}

/* --------------------------------------------------------------------------
   Shared glow sprite texture (generated once, tinted per risk level)
   -------------------------------------------------------------------------- */

let glowTexture: THREE.CanvasTexture | null = null;

/**
 * Soft radial-gradient texture used by every additive glow sprite. The
 * canvas is generated at runtime so the scene ships with zero asset files.
 */
export function getGlowTexture(): THREE.CanvasTexture | null {
  if (typeof document === "undefined") return null;
  if (glowTexture) return glowTexture;

  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;

  const context = canvas.getContext("2d");
  if (!context) return null;

  const gradient = context.createRadialGradient(
    size / 2,
    size / 2,
    0,
    size / 2,
    size / 2,
    size / 2,
  );
  gradient.addColorStop(0, "rgba(255, 255, 255, 1)");
  gradient.addColorStop(0.25, "rgba(255, 255, 255, 0.55)");
  gradient.addColorStop(0.6, "rgba(255, 255, 255, 0.12)");
  gradient.addColorStop(1, "rgba(255, 255, 255, 0)");

  context.fillStyle = gradient;
  context.fillRect(0, 0, size, size);

  glowTexture = new THREE.CanvasTexture(canvas);
  glowTexture.needsUpdate = true;
  return glowTexture;
}

/** cubic ease-in-out used by camera transitions. */
export function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}
