"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import dynamic from "next/dynamic";
import { AnimatePresence } from "framer-motion";
import { Radar } from "lucide-react";
import clsx from "clsx";
import NetworkStatsBar from "@/components/network/NetworkStatsBar";
import SceneControls from "@/components/network/SceneControls";
import RiskLegend from "@/components/network/RiskLegend";
import NodeDetailPanel from "@/components/network/NodeDetailPanel";
import ConnectionDetailPanel from "@/components/network/ConnectionDetailPanel";
import usePrefersReducedMotion from "@/hooks/usePrefersReducedMotion";
import {
  NETWORK_CONNECTIONS,
  NETWORK_NODES,
  computeNetworkStats,
  getNodeById,
  passesRiskFilter,
} from "@/lib/network-data";
import type {
  NetworkConnection,
  NetworkNode,
  RiskFilter,
} from "@/types/network";

/** WebGL scene is client-only - never touched by SSR. */
const NetworkScene = dynamic(() => import("@/components/network/NetworkScene"), {
  ssr: false,
  loading: () => <SceneBootFallback />,
});

const NETWORK_STATS = computeNetworkStats();

/**
 * Live Network - the 3D SOC topology viewport. A full-bleed R3F scene of the
 * enterprise network with floating glass overlays: headline stats, the
 * interactive control bar, the risk legend, and slide-in detail panels for
 * assets and flows.
 */
export default function NetworkPage() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const reducedMotion = usePrefersReducedMotion();

  const [selectedNode, setSelectedNode] = useState<NetworkNode | null>(null);
  const [selectedConnection, setSelectedConnection] =
    useState<NetworkConnection | null>(null);
  const [showLabels, setShowLabels] = useState(true);
  const [showParticles, setShowParticles] = useState(true);
  const [riskFilter, setRiskFilter] = useState<RiskFilter>("all");
  const [cameraResetSignal, setCameraResetSignal] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);

  /* Reduced motion kills the packet animation entirely. */
  useEffect(() => {
    if (reducedMotion) setShowParticles(false);
  }, [reducedMotion]);

  /* A flow hidden by the behavioral filter cannot stay selected. */
  useEffect(() => {
    if (
      selectedConnection &&
      !passesRiskFilter(selectedConnection.riskLevel, riskFilter)
    ) {
      setSelectedConnection(null);
    }
  }, [riskFilter, selectedConnection]);

  /* Escape clears the selection. */
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSelectedNode(null);
        setSelectedConnection(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  /* Keep the fullscreen button state in sync with the browser. */
  useEffect(() => {
    const onChange = () =>
      setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  const toggleFullscreen = useCallback(() => {
    const element = containerRef.current;
    if (!element) return;
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => undefined);
    } else {
      void element.requestFullscreen().catch(() => undefined);
    }
  }, []);

  const handleSelectNode = useCallback((node: NetworkNode | null) => {
    setSelectedNode(node);
    setSelectedConnection(null);
  }, []);

  const handleSelectConnection = useCallback(
    (connection: NetworkConnection | null) => {
      setSelectedConnection(connection);
      setSelectedNode(null);
    },
    [],
  );

  const handleDeselect = useCallback(() => {
    setSelectedNode(null);
    setSelectedConnection(null);
  }, []);

  /** Stable camera look-at point for the current selection. */
  const focusTarget = useMemo<[number, number, number] | null>(() => {
    if (selectedNode) return selectedNode.position;
    if (selectedConnection) {
      const source = getNodeById(selectedConnection.source);
      const target = getNodeById(selectedConnection.target);
      if (source && target) {
        return [
          (source.position[0] + target.position[0]) / 2,
          (source.position[1] + target.position[1]) / 2,
          (source.position[2] + target.position[2]) / 2,
        ];
      }
    }
    return null;
  }, [selectedNode, selectedConnection]);

  return (
    <section
      ref={containerRef}
      role="region"
      aria-label="Live network topology"
      className={clsx(
        "relative overflow-hidden border-cyber-border/80 bg-cyber-bg",
        isFullscreen
          ? "h-dvh w-screen rounded-none border-0"
          : "hairline-top h-[calc(100dvh-7rem)] min-h-[540px] rounded-xl border md:h-[calc(100dvh-8rem)]",
      )}
    >
      <NetworkScene
        nodes={NETWORK_NODES}
        connections={NETWORK_CONNECTIONS}
        selectedNodeId={selectedNode?.id ?? null}
        selectedConnectionId={selectedConnection?.id ?? null}
        focusTarget={focusTarget}
        cameraResetSignal={cameraResetSignal}
        showLabels={showLabels}
        showParticles={showParticles}
        riskFilter={riskFilter}
        reducedMotion={reducedMotion}
        onSelectNode={handleSelectNode}
        onSelectConnection={handleSelectConnection}
        onDeselect={handleDeselect}
      />

      {/* Top overlay: headline stats + live topology chip */}
      <div className="pointer-events-none absolute inset-x-3 top-3 z-20 flex items-start justify-between gap-3">
        <NetworkStatsBar
          stats={NETWORK_STATS}
          reducedMotion={reducedMotion}
        />

        <div className="glass-panel-strong hidden items-center gap-2 rounded-xl border border-cyber-border/90 px-3 py-2 shadow-panel lg:flex">
          <span className="relative flex h-2 w-2">
            {!reducedMotion && (
              <span
                className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyber-accent opacity-70"
                style={{ animationDuration: "2.6s" }}
              />
            )}
            <span className="relative inline-flex h-2 w-2 rounded-full bg-cyber-accent shadow-[0_0_10px_rgba(34,211,238,0.9)]" />
          </span>
          <Radar
            className="h-3.5 w-3.5 text-cyber-accent"
            strokeWidth={1.9}
            aria-hidden="true"
          />
          <span className="font-data text-[10px] tracking-[0.2em] text-cyber-muted uppercase">
            Topology · live
          </span>
        </div>
      </div>

      {/* Bottom-left legend */}
      <RiskLegend className="pointer-events-auto absolute bottom-5 left-3 z-20 hidden sm:block" />

      {/* Bottom-center control bar */}
      <div className="pointer-events-none absolute inset-x-0 bottom-4 z-20 flex justify-center px-3">
        <SceneControls
          showLabels={showLabels}
          onToggleLabels={() => setShowLabels((value) => !value)}
          showParticles={showParticles}
          onToggleParticles={() => setShowParticles((value) => !value)}
          particlesDisabled={reducedMotion}
          riskFilter={riskFilter}
          onRiskFilterChange={setRiskFilter}
          onResetCamera={() => setCameraResetSignal((value) => value + 1)}
          isFullscreen={isFullscreen}
          onToggleFullscreen={toggleFullscreen}
        />
      </div>

      {/* Detail panels */}
      <AnimatePresence>
        {selectedNode && (
          <NodeDetailPanel
            key={`node-${selectedNode.id}`}
            node={selectedNode}
            onClose={() => setSelectedNode(null)}
          />
        )}
      </AnimatePresence>
      <AnimatePresence>
        {selectedConnection && (
          <ConnectionDetailPanel
            key={`connection-${selectedConnection.id}`}
            connection={selectedConnection}
            onClose={() => setSelectedConnection(null)}
          />
        )}
      </AnimatePresence>
    </section>
  );
}

/* -------------------------------------------------------------------------- */

/** Shown while the WebGL scene chunk loads (or on devices without WebGL). */
function SceneBootFallback() {
  return (
    <div className="bg-cyber-grid-fixed absolute inset-0 flex flex-col items-center justify-center gap-4 bg-cyber-bg">
      <span className="relative flex h-14 w-14 items-center justify-center">
        <span
          className="absolute inset-0 animate-ping rounded-full border border-cyber-accent/30"
          style={{ animationDuration: "2.4s" }}
        />
        <span
          className="absolute inset-1 animate-spin rounded-full border-2 border-cyber-accent/20 border-t-cyber-accent"
          style={{ animationDuration: "1.4s" }}
        />
        <Radar
          className="h-4 w-4 text-cyber-accent-bright"
          strokeWidth={1.9}
          aria-hidden="true"
        />
      </span>
      <p className="font-data text-[10px] tracking-[0.3em] text-cyber-muted uppercase">
        Initializing topology renderer
        <span className="animate-caret-blink text-cyber-accent">▊</span>
      </p>
    </div>
  );
}
