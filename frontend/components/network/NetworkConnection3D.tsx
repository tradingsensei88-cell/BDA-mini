"use client";

import { useMemo, useRef } from "react";
import type { ComponentRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import type { ThreeEvent } from "@react-three/fiber";
import { Html, Line } from "@react-three/drei";
import type { NetworkConnection, NetworkNode } from "@/types/network";
import { RISK_ACCENTS, RISK_COLORS, RISK_LABELS } from "@/lib/network-data";
import { RISK_VISUALS, sampleConnectionCurve } from "./scene-utils";

export interface NetworkConnection3DProps {
  connection: NetworkConnection;
  source: NetworkNode;
  target: NetworkNode;
  isSelected: boolean;
  isHovered: boolean;
  /** Another element is focused - this line recedes to background noise. */
  isFaded: boolean;
  reducedMotion: boolean;
  onHoverChange: (connectionId: string | null) => void;
  onSelect: (connection: NetworkConnection) => void;
}

/**
 * A single flow between two assets: a dashed, glow-tinted quadratic arc with
 * an animated dash offset ("data flowing") and an invisible tube used as a
 * generous hover/click target. Endpoints highlight via the parent scene when
 * the flow is hovered.
 */
export default function NetworkConnection3D({
  connection,
  source,
  target,
  isSelected,
  isHovered,
  isFaded,
  reducedMotion,
  onHoverChange,
  onSelect,
}: NetworkConnection3DProps) {
  const lineRef = useRef<ComponentRef<typeof Line> | null>(null);

  const riskVisuals = RISK_VISUALS[connection.riskLevel];
  const riskColor = RISK_COLORS[connection.riskLevel];
  const riskAccent = RISK_ACCENTS[connection.riskLevel];

  const start = useMemo(
    () => new THREE.Vector3(...source.position),
    [source.position],
  );
  const end = useMemo(
    () => new THREE.Vector3(...target.position),
    [target.position],
  );

  /** Arc sample shared by the visual line and the tooltip anchor. */
  const points = useMemo(
    () => sampleConnectionCurve(start, end),
    [start, end],
  );

  const tooltipPosition = useMemo(() => {
    const middle = points[Math.floor(points.length / 2)];
    return new THREE.Vector3(middle.x, middle.y + 0.4, middle.z);
  }, [points]);

  /** Straight chord used for the invisible hover tube. */
  const hit = useMemo(() => {
    const midpoint = new THREE.Vector3()
      .addVectors(start, end)
      .multiplyScalar(0.5);
    const direction = new THREE.Vector3().subVectors(end, start);
    const length = direction.length();
    const quaternion = new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      direction.normalize(),
    );
    return { midpoint, length, quaternion };
  }, [start, end]);

  /* March the dashes along the arc - the "packets flowing" illusion. */
  useFrame((state, delta) => {
    if (reducedMotion) return;
    const line = lineRef.current;
    if (!line) return;
    const material = line.material as { dashOffset: number };
    material.dashOffset -= Math.min(delta, 0.05) * riskVisuals.flowSpeed;
  });

  const focused = isHovered || isSelected;
  const lineWidth =
    riskVisuals.lineWidth * (isHovered ? 1.65 : isSelected ? 1.5 : 1);
  const opacity = focused
    ? 1
    : isFaded
      ? riskVisuals.lineOpacity * 0.3
      : riskVisuals.lineOpacity;
  const lineColor = isSelected ? "#e6fbff" : isHovered ? riskAccent : riskColor;

  const handlePointerOver = (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    onHoverChange(connection.id);
    document.body.style.cursor = "pointer";
  };

  const handlePointerOut = (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    onHoverChange(null);
    document.body.style.cursor = "";
  };

  const handleClick = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    onSelect(connection);
  };

  return (
    <group>
      <Line
        ref={lineRef}
        points={points}
        color={lineColor}
        lineWidth={lineWidth}
        dashed
        dashSize={0.55}
        gapSize={0.32}
        transparent
        opacity={opacity}
        depthWrite={false}
        toneMapped={false}
      />

      {/* Invisible hover/click tube along the chord */}
      <mesh
        position={hit.midpoint}
        quaternion={hit.quaternion}
        onPointerOver={handlePointerOver}
        onPointerOut={handlePointerOut}
        onClick={handleClick}
      >
        <cylinderGeometry args={[0.45, 0.45, hit.length, 6]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {isHovered && !isSelected && (
        <Html
          position={tooltipPosition}
          center
          zIndexRange={[16, 0]}
          style={{ pointerEvents: "none" }}
        >
          <div className="glass-panel-strong pointer-events-none w-max rounded-lg border border-cyber-border/90 px-3 py-2 whitespace-nowrap shadow-panel">
            <p
              className="font-data text-[9px] tracking-[0.18em] uppercase"
              style={{ color: riskAccent }}
            >
              {connection.protocol} · {RISK_LABELS[connection.riskLevel]}
            </p>
            <p className="mt-0.5 text-[11px] font-semibold text-slate-100">
              {connection.prediction}
            </p>
            <p className="mt-0.5 font-data text-[9px] text-cyber-muted">
              {connection.eventCount.toLocaleString("en-US")} events ·{" "}
              {connection.confidence}% conf · click to inspect
            </p>
          </div>
        </Html>
      )}
    </group>
  );
}
