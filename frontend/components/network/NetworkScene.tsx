"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Grid, OrbitControls, Stars } from "@react-three/drei";
import type {
  NetworkConnection,
  NetworkNode,
  RiskFilter,
} from "@/types/network";
import { passesRiskFilter } from "@/lib/network-data";
import NetworkNode3D from "./NetworkNode3D";
import NetworkConnection3D from "./NetworkConnection3D";
import NetworkParticles from "./NetworkParticles";
import {
  DEFAULT_CAMERA_POSITION,
  DEFAULT_CAMERA_TARGET,
  FOCUS_CAMERA_DISTANCE,
  SCENE_BG,
  easeInOutCubic,
} from "./scene-utils";

export interface NetworkSceneProps {
  nodes: NetworkNode[];
  connections: NetworkConnection[];
  selectedNodeId: string | null;
  selectedConnectionId: string | null;
  /** Camera look-at point while something is selected (null = home). */
  focusTarget: [number, number, number] | null;
  /** Increment to fly the camera back to the default framing. */
  cameraResetSignal: number;
  showLabels: boolean;
  showParticles: boolean;
  riskFilter: RiskFilter;
  reducedMotion: boolean;
  onSelectNode: (node: NetworkNode | null) => void;
  onSelectConnection: (connection: NetworkConnection | null) => void;
  /** Click on empty space - clears every selection. */
  onDeselect: () => void;
}

/**
 * The 3D command-center view of the enterprise network. Owns the R3F canvas,
 * scene environment (fog, stars, grid, lights), and delegates every visual
 * entity to its dedicated component.
 */
export default function NetworkScene(props: NetworkSceneProps) {
  const { onDeselect } = props;

  return (
    <Canvas
      dpr={[1, 1.75]}
      camera={{
        position: DEFAULT_CAMERA_POSITION,
        fov: 48,
        near: 0.5,
        far: 400,
      }}
      gl={{ antialias: true, powerPreference: "high-performance" }}
      onPointerMissed={onDeselect}
      className="!absolute !inset-0"
    >
      <color attach="background" args={[SCENE_BG]} />
      <fog attach="fog" args={[SCENE_BG, 46, 118]} />

      <Suspense fallback={null}>
        <SceneContent {...props} />
      </Suspense>
    </Canvas>
  );
}

/* -------------------------------------------------------------------------- */

function SceneContent({
  nodes,
  connections,
  selectedNodeId,
  selectedConnectionId,
  focusTarget,
  cameraResetSignal,
  showLabels,
  showParticles,
  riskFilter,
  reducedMotion,
  onSelectNode,
  onSelectConnection,
}: NetworkSceneProps) {
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [hoveredConnectionId, setHoveredConnectionId] = useState<string | null>(
    null,
  );

  const nodesById = useMemo(
    () => new Map(nodes.map((node) => [node.id, node])),
    [nodes],
  );

  /** Connections surviving the active risk filter. */
  const visibleConnections = useMemo(
    () =>
      connections.filter((connection) =>
        passesRiskFilter(connection.riskLevel, riskFilter),
      ),
    [connections, riskFilter],
  );

  /** Endpoints of the hovered/selected connection - get a highlight lift. */
  const linkedNodeIds = useMemo(() => {
    const focusId = hoveredConnectionId ?? selectedConnectionId;
    if (!focusId) return new Set<string>();
    const connection = connections.find((item) => item.id === focusId);
    return new Set(
      connection ? [connection.source, connection.target] : [],
    );
  }, [hoveredConnectionId, selectedConnectionId, connections]);

  /** Focused node (hover wins over selection) - its flows stay bright. */
  const focusedNodeId = hoveredNodeId ?? selectedNodeId;

  return (
    <>
      {/* Environment ------------------------------------------------------ */}
      <ambientLight intensity={0.42} color="#7d9ac0" />
      <hemisphereLight args={["#3b5b8f", "#04070f", 0.55]} />
      <pointLight position={[0, 20, 12]} intensity={1.5} color="#22d3ee" decay={0} />
      <pointLight position={[-18, -4, -12]} intensity={0.8} color="#ef4444" decay={0} />
      <pointLight position={[16, 8, -14]} intensity={0.9} color="#38bdf8" decay={0} />
      <directionalLight position={[12, 24, 10]} intensity={0.35} color="#bfdbfe" />

      <Stars
        radius={95}
        depth={45}
        count={1400}
        factor={3.2}
        saturation={0}
        fade
        speed={reducedMotion ? 0 : 0.4}
      />

      <Grid
        position={[0, -9.6, 0]}
        args={[10, 10]}
        cellSize={1.4}
        cellThickness={0.55}
        cellColor="#10203a"
        sectionSize={7}
        sectionThickness={1}
        sectionColor="#1d3f66"
        fadeDistance={95}
        fadeStrength={1.5}
        infiniteGrid
      />

      <OrbitControls
        makeDefault
        enableDamping
        dampingFactor={0.08}
        minDistance={10}
        maxDistance={95}
        maxPolarAngle={Math.PI * 0.62}
        target={DEFAULT_CAMERA_TARGET}
        panSpeed={0.8}
      />

      <CameraRig
        focusTarget={focusTarget}
        resetSignal={cameraResetSignal}
        reducedMotion={reducedMotion}
      />

      {/* Flows ------------------------------------------------------------ */}
      {visibleConnections.map((connection) => {
        const source = nodesById.get(connection.source);
        const target = nodesById.get(connection.target);
        if (!source || !target) return null;

        const isHovered = hoveredConnectionId === connection.id;
        const isSelected = selectedConnectionId === connection.id;
        const isFaded = focusedNodeId
          ? connection.source !== focusedNodeId &&
            connection.target !== focusedNodeId
          : Boolean(hoveredConnectionId && !isHovered);

        return (
          <NetworkConnection3D
            key={connection.id}
            connection={connection}
            source={source}
            target={target}
            isSelected={isSelected}
            isHovered={isHovered}
            isFaded={isFaded}
            reducedMotion={reducedMotion}
            onHoverChange={setHoveredConnectionId}
            onSelect={(value) => onSelectConnection(value)}
          />
        );
      })}

      {/* Flowing packets ---------------------------------------------------- */}
      {showParticles && !reducedMotion && (
        <NetworkParticles
          connections={visibleConnections}
          nodesById={nodesById}
          reducedMotion={reducedMotion}
        />
      )}

      {/* Assets ------------------------------------------------------------- */}
      {nodes.map((node) => (
        <NetworkNode3D
          key={node.id}
          node={node}
          isSelected={selectedNodeId === node.id}
          isHovered={hoveredNodeId === node.id}
          isLinkedHighlight={
            linkedNodeIds.has(node.id) && hoveredNodeId !== node.id
          }
          isDimmed={!passesRiskFilter(node.riskLevel, riskFilter)}
          showLabel={showLabels}
          reducedMotion={reducedMotion}
          onHoverChange={setHoveredNodeId}
          onSelect={(value) => onSelectNode(value)}
        />
      ))}
    </>
  );
}

/* -------------------------------------------------------------------------- */

interface OrbitLike {
  target: THREE.Vector3;
  update: () => void;
}

interface CameraRigProps {
  focusTarget: [number, number, number] | null;
  resetSignal: number;
  reducedMotion: boolean;
}

/**
 * Smooth camera transitions: flying to a focused node (or connection
 * midpoint) and returning home. Mutates `OrbitControls.target` in lockstep so
 * orbiting continues naturally from the new framing.
 */
function CameraRig({ focusTarget, resetSignal, reducedMotion }: CameraRigProps) {
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls) as unknown as
    | OrbitLike
    | null;

  const animationRef = useRef<{
    active: boolean;
    t: number;
    duration: number;
    fromPosition: THREE.Vector3;
    toPosition: THREE.Vector3;
    fromTarget: THREE.Vector3;
    toTarget: THREE.Vector3;
  } | null>(null);

  const lastResetRef = useRef(resetSignal);
  const focusKey = focusTarget ? focusTarget.join(",") : "home";

  useEffect(() => {
    const isReset = resetSignal !== lastResetRef.current;
    lastResetRef.current = resetSignal;

    const fromPosition = camera.position.clone();
    const fromTarget = controls?.target.clone() ?? new THREE.Vector3(...DEFAULT_CAMERA_TARGET);

    let toPosition: THREE.Vector3;
    let toTarget: THREE.Vector3;

    if (focusTarget && !isReset) {
      toTarget = new THREE.Vector3(...focusTarget);
      const direction = new THREE.Vector3().subVectors(fromPosition, toTarget);
      if (direction.lengthSq() < 0.001) direction.set(0.55, 0.4, 0.75);
      direction.normalize();
      toPosition = new THREE.Vector3()
        .copy(toTarget)
        .addScaledVector(direction, FOCUS_CAMERA_DISTANCE);
      toPosition.y = Math.max(toPosition.y, toTarget.y + 4.5);
    } else {
      toTarget = new THREE.Vector3(...DEFAULT_CAMERA_TARGET);
      toPosition = new THREE.Vector3(...DEFAULT_CAMERA_POSITION);
    }

    if (reducedMotion) {
      camera.position.copy(toPosition);
      if (controls) {
        controls.target.copy(toTarget);
        controls.update();
      }
      animationRef.current = null;
      return;
    }

    animationRef.current = {
      active: true,
      t: 0,
      duration: 1.15,
      fromPosition,
      toPosition,
      fromTarget,
      toTarget,
    };
  }, [focusKey, resetSignal, camera, controls, reducedMotion, focusTarget]);

  useFrame((_, delta) => {
    const animation = animationRef.current;
    if (!animation || !animation.active) return;

    animation.t = Math.min(1, animation.t + delta / animation.duration);
    const eased = easeInOutCubic(animation.t);

    camera.position.lerpVectors(animation.fromPosition, animation.toPosition, eased);
    if (controls) {
      controls.target.lerpVectors(animation.fromTarget, animation.toTarget, eased);
      controls.update();
    }

    if (animation.t >= 1) animation.active = false;
  });

  return null;
}
