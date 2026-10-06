"use client";

import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import type { ThreeEvent } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import type { NetworkNode, NodeType } from "@/types/network";
import { RISK_ACCENTS, RISK_COLORS, RISK_LABELS } from "@/lib/network-data";
import {
  NODE_VISUALS,
  RISK_VISUALS,
  brightenColor,
  dimColor,
  getGlowTexture,
} from "./scene-utils";

export interface NetworkNode3DProps {
  node: NetworkNode;
  isSelected: boolean;
  isHovered: boolean;
  /** True when this node is an endpoint of the hovered/selected connection. */
  isLinkedHighlight: boolean;
  /** Filtered out by the risk filter - rendered as a dim ghost. */
  isDimmed: boolean;
  showLabel: boolean;
  reducedMotion: boolean;
  onHoverChange: (nodeId: string | null) => void;
  onSelect: (node: NetworkNode) => void;
}

/**
 * One asset of the stylized enterprise network. Renders the type-specific
 * primitive set, an additive glow halo, an expanding alert ring for risky
 * nodes, and HTML label/tooltip overlays. All animation is driven from a
 * single `useFrame` callback per node.
 */
export default function NetworkNode3D({
  node,
  isSelected,
  isHovered,
  isLinkedHighlight,
  isDimmed,
  showLabel,
  reducedMotion,
  onHoverChange,
  onSelect,
}: NetworkNode3DProps) {
  const groupRef = useRef<THREE.Group | null>(null);
  const glowRef = useRef<THREE.Sprite | null>(null);
  const alarmRingRef = useRef<THREE.Mesh | null>(null);
  const hoverLiftRef = useRef(0);

  const visuals = NODE_VISUALS[node.type];
  const riskVisuals = RISK_VISUALS[node.riskLevel];
  const riskColor = RISK_COLORS[node.riskLevel];
  const riskAccent = RISK_ACCENTS[node.riskLevel];
  const glowTexture = useMemo(() => getGlowTexture(), []);

  /** Stable per-node phase offset so pulses never sync up. */
  const phase = useMemo(() => {
    let hash = 0;
    for (let i = 0; i < node.id.length; i += 1) {
      hash = (hash * 31 + node.id.charCodeAt(i)) % 997;
    }
    return (hash / 997) * Math.PI * 2;
  }, [node.id]);

  /**
   * Single shared material instance drives every sub-mesh of this node so the
   * pulse/hover animation updates one object instead of N.
   */
  const material = useMemo(() => {
    return new THREE.MeshStandardMaterial({
      metalness: 0.62,
      roughness: 0.3,
      transparent: true,
    });
  }, []);

  useEffect(() => {
    return () => {
      material.dispose();
    };
  }, [material]);

  /* Sync static material props on state changes. */
  useEffect(() => {
    const shell = isDimmed
      ? dimColor(riskColor, 0.7)
      : new THREE.Color(riskColor).multiplyScalar(0.4);
    const emissive = isDimmed
      ? dimColor(riskColor, 0.72)
      : new THREE.Color(riskColor);
    material.color.copy(shell);
    material.emissive.copy(emissive);
    material.emissiveIntensity = isDimmed ? 0.1 : riskVisuals.emissive;
    material.opacity = isDimmed ? 0.35 : 1;
  }, [material, riskColor, riskVisuals.emissive, isDimmed]);

  /* Reset the cursor if the node unmounts while hovered. */
  useEffect(() => {
    return () => {
      document.body.style.cursor = "";
    };
  }, []);

  useFrame((state, delta) => {
    const elapsed = state.clock.elapsedTime;
    const step = Math.min(delta, 0.05);

    const pulse = reducedMotion
      ? 0.5
      : Math.sin(elapsed * riskVisuals.pulseSpeed + phase) * 0.5 + 0.5;

    const liftTarget = isHovered || isLinkedHighlight ? 1 : 0;
    hoverLiftRef.current +=
      (liftTarget - hoverLiftRef.current) * Math.min(1, step * 9);
    const lift = hoverLiftRef.current;

    /* Emissive surge on hover / selection, breathing pulse otherwise. */
    const targetIntensity = isDimmed
      ? 0.08
      : riskVisuals.emissive +
        pulse * riskVisuals.pulseAmp +
        lift * 0.85 +
        (isSelected ? 0.55 : 0);
    material.emissiveIntensity +=
      (targetIntensity - material.emissiveIntensity) * Math.min(1, step * 10);

    /* Breathing scale + hover lift - the whole cluster scales together. */
    if (groupRef.current) {
      const breath = reducedMotion ? 0 : pulse * 0.022;
      const scale = 1 + breath + lift * 0.14 + (isSelected ? 0.05 : 0);
      groupRef.current.scale.setScalar(scale);
    }

    /* Halo follows the pulse; brightens and grows on hover. */
    if (glowRef.current) {
      const glowMaterial = glowRef.current.material as THREE.SpriteMaterial;
      const targetOpacity = isDimmed
        ? 0.05
        : 0.22 + pulse * (0.12 + lift * 0.28) + (isSelected ? 0.14 : 0);
      glowMaterial.opacity +=
        (targetOpacity - glowMaterial.opacity) * Math.min(1, step * 8);
      const glowScale =
        visuals.glowScale * (1 + lift * 0.35 + (isSelected ? 0.18 : 0));
      glowRef.current.scale.set(glowScale, glowScale, 1);
    }

    /* Expanding ground ring - the "critical alert" radar ping. */
    const ring = alarmRingRef.current;
    if (ring) {
      const active = riskVisuals.ring !== "none" && !reducedMotion && !isDimmed;
      ring.visible = active;
      if (active) {
        const cycle = (elapsed / riskVisuals.ringPeriod + phase) % 1;
        const ringScale =
          1 + cycle * (riskVisuals.ring === "strong" ? 2.6 : 1.9);
        ring.scale.set(ringScale, ringScale, 1);
        const ringMaterial = ring.material as THREE.MeshBasicMaterial;
        ringMaterial.opacity =
          (1 - cycle) * (riskVisuals.ring === "strong" ? 0.55 : 0.32);
      }
    }
  });

  const handlePointerOver = (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    onHoverChange(node.id);
    document.body.style.cursor = "pointer";
  };

  const handlePointerOut = (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    onHoverChange(null);
    document.body.style.cursor = "";
  };

  const handleClick = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    onSelect(node);
  };

  const edgeColor = isDimmed ? "#1c2941" : riskAccent;
  const ringY = -(visuals.labelOffset * 0.7);

  return (
    <group position={node.position}>
      <group ref={groupRef}>
        <NodeGeometry type={node.type} material={material} edgeColor={edgeColor} />

        {/* Additive halo */}
        <sprite ref={glowRef} scale={[visuals.glowScale, visuals.glowScale, 1]}>
          <spriteMaterial
            map={glowTexture}
            color={riskColor}
            transparent
            opacity={0.3}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            toneMapped={false}
          />
        </sprite>

        {/* Static footprint ring - anchors the node to its vertical stratum */}
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, ringY, 0]}>
          <ringGeometry args={[0.94, 1.04, 32]} />
          <meshBasicMaterial
            color={riskColor}
            transparent
            opacity={isDimmed ? 0.04 : 0.16}
            side={THREE.DoubleSide}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            toneMapped={false}
          />
        </mesh>

        {/* Expanding alert ping (high + critical) */}
        <mesh
          ref={alarmRingRef}
          rotation={[-Math.PI / 2, 0, 0]}
          position={[0, ringY, 0]}
          visible={false}
        >
          <ringGeometry args={[1.12, 1.34, 40]} />
          <meshBasicMaterial
            color={riskAccent}
            transparent
            opacity={0.4}
            side={THREE.DoubleSide}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            toneMapped={false}
          />
        </mesh>

        {/* Selection marker */}
        {isSelected && (
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, ringY, 0]}>
            <ringGeometry args={[1.42, 1.56, 48]} />
            <meshBasicMaterial
              color="#67e8f9"
              transparent
              opacity={0.85}
              side={THREE.DoubleSide}
              depthWrite={false}
              blending={THREE.AdditiveBlending}
              toneMapped={false}
            />
          </mesh>
        )}

        {/* Invisible hover/click capture volume */}
        <mesh
          onPointerOver={handlePointerOver}
          onPointerOut={handlePointerOut}
          onClick={handleClick}
        >
          <sphereGeometry args={[visuals.hitRadius, 10, 10]} />
          <meshBasicMaterial transparent opacity={0} depthWrite={false} />
        </mesh>
      </group>

      {/* HTML overlays (outside the pulsing group so text stays steady) */}
      {showLabel && (
        <Html
          position={[0, -visuals.labelOffset, 0]}
          center
          zIndexRange={[15, 0]}
          style={{ pointerEvents: "none" }}
        >
          <div
            className="pointer-events-none flex items-center gap-1.5 whitespace-nowrap"
            style={{ opacity: isDimmed ? 0.4 : 1 }}
          >
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{
                backgroundColor: riskColor,
                boxShadow: `0 0 6px ${riskColor}`,
              }}
            />
            <span className="font-data text-[9px] tracking-wide text-slate-300">
              {node.name}
            </span>
          </div>
        </Html>
      )}

      {isHovered && (
        <Html
          position={[0, visuals.tooltipOffset + 0.5, 0]}
          center
          zIndexRange={[16, 0]}
          style={{ pointerEvents: "none" }}
        >
          <div className="glass-panel-strong pointer-events-none w-max rounded-lg border border-cyber-border/90 px-3 py-2 whitespace-nowrap shadow-panel">
            <p className="text-[11px] font-semibold text-slate-100">
              {node.name}
            </p>
            <p className="mt-0.5 font-data text-[9px] tracking-[0.14em] text-cyber-muted uppercase">
              {node.type} · risk score {node.riskScore}
            </p>
            <p
              className="mt-1 font-data text-[9px] tracking-wide"
              style={{ color: riskAccent }}
            >
              {RISK_LABELS[node.riskLevel]} · click to inspect
            </p>
          </div>
        </Html>
      )}
    </group>
  );
}

/* -------------------------------------------------------------------------- */

interface NodePrimitive {
  geometry: THREE.BufferGeometry;
  position?: [number, number, number];
  rotation?: [number, number, number];
  /** When set, an `EdgesGeometry` wireframe overlay is rendered. */
  edgesThreshold?: number;
}

/**
 * Builds the low-poly primitive set for a node archetype. Geometries are
 * tiny (<= 32 segments) and instantiated per node - 18 nodes cost ~55 small
 * buffer geometries, well within budget.
 */
function createNodePrimitives(type: NodeType): NodePrimitive[] {
  switch (type) {
    case "server":
      return [
        {
          geometry: new THREE.BoxGeometry(1.6, 1.6, 1.6),
          edgesThreshold: 15,
        },
      ];
    case "router":
      return [
        {
          geometry: new THREE.OctahedronGeometry(1.35, 0),
          edgesThreshold: 15,
        },
      ];
    case "gateway":
      return [
        {
          geometry: new THREE.CylinderGeometry(0.95, 1.15, 3.2, 10),
          position: [0, 1.6, 0],
          edgesThreshold: 40,
        },
        {
          geometry: new THREE.SphereGeometry(0.22, 12, 12),
          position: [0, 3.35, 0],
        },
      ];
    case "database":
      return [-0.78, 0, 0.78].map((y) => ({
        geometry: new THREE.CylinderGeometry(1.15, 1.15, 0.62, 18),
        position: [0, y, 0] as [number, number, number],
        edgesThreshold: 40,
      }));
    case "endpoint":
      return [{ geometry: new THREE.SphereGeometry(0.78, 16, 16) }];
    case "cloud":
      return (
        [
          [-0.95, 0.1, 0],
          [0.95, 0.1, 0],
          [0, 0.72, 0.1],
          [0, -0.28, 0.75],
        ] as Array<[number, number, number]>
      ).map((offset) => ({
        geometry: new THREE.SphereGeometry(0.92, 16, 16),
        position: offset,
      }));
    case "firewall":
      return [
        {
          geometry: new THREE.CylinderGeometry(1.5, 1.5, 0.34, 6),
          rotation: [Math.PI / 2, 0, 0],
          edgesThreshold: 40,
        },
      ];
    default:
      return [
        {
          geometry: new THREE.BoxGeometry(1.4, 1.4, 1.4),
          edgesThreshold: 15,
        },
      ];
  }
}

interface NodeGeometryProps {
  type: NodeType;
  material: THREE.MeshStandardMaterial;
  edgeColor: string;
}

/**
 * Type-specific primitive set. Every sub-mesh shares the node's single
 * material instance so the pulse animation touches exactly one object.
 */
function NodeGeometry({ type, material, edgeColor }: NodeGeometryProps) {
  const primitives = useMemo(() => createNodePrimitives(type), [type]);

  /* Dispose the geometry set when the node unmounts. */
  useEffect(() => {
    return () => {
      for (const primitive of primitives) {
        primitive.geometry.dispose();
      }
    };
  }, [primitives]);

  return (
    <>
      {primitives.map((primitive, index) => (
        <mesh
          key={index}
          geometry={primitive.geometry}
          material={material}
          position={primitive.position}
          rotation={primitive.rotation}
        >
          {primitive.edgesThreshold !== undefined && (
            <lineSegments>
              <edgesGeometry args={[primitive.geometry, primitive.edgesThreshold]} />
              <lineBasicMaterial
                color={edgeColor}
                transparent
                opacity={0.8}
                depthWrite={false}
                toneMapped={false}
              />
            </lineSegments>
          )}
        </mesh>
      ))}
    </>
  );
}
