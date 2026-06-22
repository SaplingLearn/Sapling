"use client";

/**
 * KnowledgeGraph — wrapper that toggles between the 2D SVG/d3-force
 * and the 3D WebGL/three.js implementations.
 *
 * Defaults to 2D. The mode is persisted in localStorage and synced
 * across mounted instances via the `storage` event plus a same-tab
 * custom event so toggling on one graph updates them all.
 */

import React from "react";
import dynamic from "next/dynamic";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { KnowledgeGraph2D } from "./KnowledgeGraph2D";

// The 3D graph pulls in three.js + react-force-graph-3d + d3-force-3d.
// Static-importing it bloats the OpenNext worker bundle past Cloudflare's
// size limit even on paid plans. Lazy-load it (ssr:false) so the three.js
// stack only enters the bundle as a client chunk when 3D mode is toggled.
const KnowledgeGraph3D = dynamic(
  () => import("./KnowledgeGraph3D").then((m) => m.KnowledgeGraph3D),
  { ssr: false, loading: () => null },
);

type Mode = "2d" | "3d";

const STORAGE_KEY = "sapling.kg.mode";
const SYNC_EVENT = "sapling:kg-mode-change";

function readMode(): Mode {
  if (typeof window === "undefined") return "2d";
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    return v === "3d" ? "3d" : "2d";
  } catch {
    return "2d";
  }
}

function writeMode(mode: Mode) {
  try {
    window.localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // ignore quota / privacy mode failures — toggle still works in-tab
  }
  window.dispatchEvent(new CustomEvent<Mode>(SYNC_EVENT, { detail: mode }));
}

function useGraphMode(): [Mode, (m: Mode) => void] {
  // SSR returns "2d"; client may compute the same. The wrapper renders
  // identical markup at first paint either way, so no hydration mismatch.
  const [mode, setMode] = React.useState<Mode>("2d");
  React.useEffect(() => {
    setMode(readMode());
    const onStorage = (e: StorageEvent) => {
      if (e.key !== STORAGE_KEY) return;
      setMode(e.newValue === "3d" ? "3d" : "2d");
    };
    const onCustom = (e: Event) => {
      const detail = (e as CustomEvent<Mode>).detail;
      if (detail === "2d" || detail === "3d") setMode(detail);
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(SYNC_EVENT, onCustom);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(SYNC_EVENT, onCustom);
    };
  }, []);
  const update = React.useCallback((next: Mode) => {
    setMode(next);
    writeMode(next);
  }, []);
  return [mode, update];
}

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  width?: number;
  height?: number;
  highlightId?: string;
  onNodeClick?: (n: GraphNode) => void;
};

export function KnowledgeGraph(props: Props) {
  const [mode, setMode] = useGraphMode();
  const next: Mode = mode === "2d" ? "3d" : "2d";
  const { width = 800, height = 480 } = props;

  return (
    <div style={{ position: "relative", width, height }}>
      {mode === "2d" ? (
        <KnowledgeGraph2D {...props} />
      ) : (
        <KnowledgeGraph3D {...props} />
      )}
      <button
        type="button"
        className="btn btn--ghost btn--sm"
        onClick={() => setMode(next)}
        title={`Switch to ${next.toUpperCase()} graph`}
        aria-label={`Switch to ${next.toUpperCase()} graph`}
        style={{
          position: "absolute",
          top: 12,
          left: 12,
          padding: "2px 10px",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          background: "var(--bg-panel)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-sm)",
          boxShadow: "var(--shadow-sm)",
          zIndex: 5,
        }}
      >
        {mode.toUpperCase()}
      </button>
    </div>
  );
}
