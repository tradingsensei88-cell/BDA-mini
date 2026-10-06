"use client";

import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import type { NetworkConnection, NetworkNode } from "@/types/network";
import { RISK_COLORS, RISK_ORDER, mulberry32 } from "@/lib/network-data";
import { brightenColor, connectionControlPoint, quadraticPoint } from "./scene-utils";

export interface NetworkParticlesProps {
  /** Connections that passed the active risk filter. */
  connections: NetworkConnection[];
  nodesById: Map<string, NetworkNode>;
  reducedMotion: boolean;
}

/** Hard ceiling - keeps the instanced draw at two buffers of 100 quads. */
const MAX_PARTICLES = 100;

/** Progress-per-second ranges per risk tier (normal slow -> attack fast). */
const SPEED_RANGES: Record<NetworkConnection["riskLevel"], [number, number]> = {
  normal: [0.07, 0.13],
  suspicious: [0.16, 0.24],
  high: [0.28, 0.38],
  critical: [0.42, 0.58],
};

interface ParticleSpec {
  connectionIndex: number;
  progress: number;
  speed: number;
  size: number;
  isAttack: boolean;
}

interface ConnectionCurve {
  start: THREE.Vector3;
  control: THREE.Vector3;
  end: THREE.Vector3;
  color: THREE.Color;
  coreColor: THREE.Color;
}

/**
 * Data-in-motion layer: up to 100 additive-blended particles riding the same
 * quadratic arcs as the connection lines. Implemented with two instanced
 * meshes (core + halo) so the whole fleet costs exactly two draw calls.
 */
export default function NetworkParticles({
  connections,
  nodesById,
  reducedMotion,
}: NetworkParticlesProps) {
  const coreRef = useRef<THREE.InstancedMesh | null>(null);
  const haloRef = useRef<THREE.InstancedMesh | null>(null);

  /* Resolved arcs + palette per connection (parallel to `connections`). */
  const curves = useMemo<Array<ConnectionCurve | null>>(() => {
    return connections.map((connection) => {
      const source = nodesById.get(connection.source);
      const target = nodesById.get(connection.target);
      if (!source || !target) return null;

      const start = new THREE.Vector3(...source.position);
      const end = new THREE.Vector3(...target.position);
      const control = connectionControlPoint(start, end, new THREE.Vector3());
      const color = new THREE.Color(RISK_COLORS[connection.riskLevel]);
      return { start, control, end, color, coreColor: brightenColor(RISK_COLORS[connection.riskLevel], 0.4).multiplyScalar(1.15) };
    });
  }, [connections, nodesById]);

  /**
   * Particle allocation: riskier flows get more (and faster) packets. Highest
   * risk first so the 100-slot budget always favors attacks. Seeded PRNG keeps
   * the layout stable between renders and reloads.
   */
  const specs = useMemo<ParticleSpec[]>(() => {
    const random = mulberry32(20261);
    const specs: ParticleSpec[] = [];

    const ranked = connections
      .map((connection, index) => ({ connection, index }))
      .sort(
        (a, b) =>
          RISK_ORDER[b.connection.riskLevel] - RISK_ORDER[a.connection.riskLevel] ||
          b.connection.eventCount - a.connection.eventCount,
      );

    for (const { connection, index } of ranked) {
      if (specs.length >= MAX_PARTICLES) break;

      const perFlow = Math.min(
        4,
        Math.max(1, Math.round(connection.eventCount / 14000)),
      );
      const [speedMin, speedMax] = SPEED_RANGES[connection.riskLevel];

      for (let i = 0; i < perFlow && specs.length < MAX_PARTICLES; i += 1) {
        const isAttack =
          connection.riskLevel === "critical" ||
          (connection.riskLevel === "high" && random() < 0.5);
        specs.push({
          connectionIndex: index,
          progress: random(),
          speed: speedMin + random() * (speedMax - speedMin),
          size: isAttack
            ? 0.13
            : connection.riskLevel === "suspicious"
              ? 0.105
              : 0.085,
          isAttack,
        });
      }
    }
    return specs;
  }, [connections]);

  /* Instanced resources - created once, disposed on unmount. */
  const coreGeometry = useMemo(
    () => new THREE.SphereGeometry(1, 8, 8),
    [],
  );
  const haloGeometry = useMemo(
    () => new THREE.SphereGeometry(1, 8, 8),
    [],
  );
  const coreMaterial = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        transparent: true,
        opacity: 0.95,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        toneMapped: false,
      }),
    [],
  );
  const haloMaterial = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        transparent: true,
        opacity: 0.2,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        toneMapped: false,
      }),
    [],
  );

  useEffect(() => {
    return () => {
      coreGeometry.dispose();
      haloGeometry.dispose();
      coreMaterial.dispose();
      haloMaterial.dispose();
    };
  }, [coreGeometry, haloGeometry, coreMaterial, haloMaterial]);

  /* Scratch objects reused by the frame loop (zero per-frame allocation). */
  const scratch = useMemo(
    () => ({ dummy: new THREE.Object3D(), position: new THREE.Vector3() }),
    [],
  );

  /* Per-instance colors + initial zeroed matrices. */
  useEffect(() => {
    const core = coreRef.current;
    const halo = haloRef.current;
    if (!core || !halo) return;

    const black = new THREE.Color(0, 0, 0);
    const { dummy } = scratch;
    dummy.position.set(0, 0, 0);
    dummy.scale.setScalar(0);
    dummy.updateMatrix();

    for (let i = 0; i < MAX_PARTICLES; i += 1) {
      const spec = specs[i];
      const curve = spec ? curves[spec.connectionIndex] : null;

      if (spec && curve) {
        core.setColorAt(i, curve.coreColor);
        halo.setColorAt(i, curve.color);
      } else {
        core.setColorAt(i, black);
        halo.setColorAt(i, black);
      }
      core.setMatrixAt(i, dummy.matrix);
      halo.setMatrixAt(i, dummy.matrix);
    }

    if (core.instanceColor) core.instanceColor.needsUpdate = true;
    if (halo.instanceColor) halo.instanceColor.needsUpdate = true;
    core.instanceMatrix.needsUpdate = true;
    halo.instanceMatrix.needsUpdate = true;
  }, [specs, curves, scratch]);

  useFrame((state, delta) => {
    const core = coreRef.current;
    const halo = haloRef.current;
    if (!core || !halo) return;

    const step = Math.min(delta, 0.05);
    const { dummy, position } = scratch;
    const elapsed = state.clock.elapsedTime;

    for (let i = 0; i < MAX_PARTICLES; i += 1) {
      const spec = specs[i];
      const curve = spec ? curves[spec.connectionIndex] : null;

      if (!spec || !curve) {
        dummy.position.set(0, 0, 0);
        dummy.scale.setScalar(0);
        dummy.updateMatrix();
        core.setMatrixAt(i, dummy.matrix);
        halo.setMatrixAt(i, dummy.matrix);
        continue;
      }

      spec.progress += step * spec.speed;
      if (spec.progress >= 1) spec.progress -= 1;

      quadraticPoint(curve.start, curve.control, curve.end, spec.progress, position);
      dummy.position.copy(position);

      /* Subtle twinkle so steady flows still feel alive. */
      const twinkle = reducedMotion
        ? 1
        : 1 + Math.sin(elapsed * 5 + i * 1.7) * (spec.isAttack ? 0.28 : 0.12);

      dummy.scale.setScalar(spec.size * twinkle);
      dummy.updateMatrix();
      core.setMatrixAt(i, dummy.matrix);

      dummy.scale.setScalar(spec.size * 2.6 * twinkle);
      dummy.updateMatrix();
      halo.setMatrixAt(i, dummy.matrix);
    }

    core.instanceMatrix.needsUpdate = true;
    halo.instanceMatrix.needsUpdate = true;
  });

  return (
    <group>
      <instancedMesh
        ref={coreRef}
        args={[coreGeometry, coreMaterial, MAX_PARTICLES]}
        frustumCulled={false}
      />
      <instancedMesh
        ref={haloRef}
        args={[haloGeometry, haloMaterial, MAX_PARTICLES]}
        frustumCulled={false}
      />
    </group>
  );
}
