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
import { ErrorBoundary } from "../ErrorBoundary";

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

/**
 * Three r163+ requires WebGL2 and THROWS from the WebGLRenderer
 * constructor when the context can't be created (#538) — so the 3D
 * variant must never mount unless a webgl2 context is actually
 * obtainable. Probed per wrapper mount; the probe context is released
 * via WEBGL_lose_context so repeated mounts don't count toward the
 * browser's per-page live-context cap.
 */
function webgl2Available(): boolean {
  try {
    const ctx = document.createElement("canvas").getContext("webgl2");
    if (!ctx) return false;
    ctx.getExtension?.("WEBGL_lose_context")?.loseContext();
    return true;
  } catch {
    return false;
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

function useGraphMode(): [Mode, (m: Mode) => void, boolean] {
  // SSR returns "2d"; client may compute the same. The wrapper renders
  // identical markup at first paint either way, so no hydration mismatch.
  const [mode, setMode] = React.useState<Mode>("2d");
  // Optimistic `true` matches the SSR markup (toggle enabled); the
  // mount effect corrects it before 3D could ever mount, because mode
  // only leaves "2d" inside that same effect.
  const [webglOk, setWebglOk] = React.useState(true);
  React.useEffect(() => {
    const ok = webgl2Available();
    // Without WebGL2 a persisted "3d" is ignored (NOT rewritten): the
    // preference survives for this profile's WebGL-capable browsers.
    const gate = (m: Mode): Mode => (m === "3d" && ok ? "3d" : "2d");
    setWebglOk(ok);
    setMode(gate(readMode()));
    const onStorage = (e: StorageEvent) => {
      if (e.key !== STORAGE_KEY) return;
      setMode(gate(e.newValue === "3d" ? "3d" : "2d"));
    };
    const onCustom = (e: Event) => {
      const detail = (e as CustomEvent<Mode>).detail;
      if (detail === "2d" || detail === "3d") setMode(gate(detail));
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(SYNC_EVENT, onCustom);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(SYNC_EVENT, onCustom);
    };
  }, []);
  const update = React.useCallback(
    (next: Mode) => {
      const gated = next === "3d" && !webglOk ? "2d" : next;
      setMode(gated);
      writeMode(gated);
    },
    [webglOk],
  );
  return [mode, update, webglOk];
}

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  width?: number;
  height?: number;
  highlightId?: string;
  onNodeClick?: (n: GraphNode) => void;
};

/**
 * Crash fallback for the graph slot (#538). A 3D crash (context
 * creation failing despite a successful probe — GPU process crash,
 * context-limit exhaustion) degrades to the 2D graph inline and heals
 * the persisted mode to "2d"; the heal flips the boundary's `key`, so
 * the error state clears and the normal 2D child takes over. A 2D
 * crash (no known cause) renders a minimal placeholder rather than
 * re-mounting the component that just threw.
 */
function GraphCrashFallback({
  crashedMode,
  graphProps,
  heal,
}: {
  crashedMode: Mode;
  graphProps: Props;
  heal: (m: Mode) => void;
}) {
  React.useEffect(() => {
    if (crashedMode === "3d") heal("2d");
  }, [crashedMode, heal]);
  if (crashedMode === "3d") return <KnowledgeGraph2D {...graphProps} />;
  return (
    <div
      role="status"
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: "100%",
        color: "var(--text-dim)",
        fontSize: 13,
      }}
    >
      The graph couldn&apos;t render here. Reload to try again.
    </div>
  );
}

export function KnowledgeGraph(props: Props) {
  const [mode, setMode, webglOk] = useGraphMode();
  const next: Mode = mode === "2d" ? "3d" : "2d";
  const { width = 800, height = 480 } = props;

  return (
    <div data-testid="graph-container" style={{ position: "relative", width, height }}>
      {/* Local boundary so a renderer failure degrades in place instead
          of unmounting the whole app into the root fallback (#538).
          Keyed by mode: flipping modes remounts a fresh boundary, so a
          crash in one renderer never wedges the other. */}
      <ErrorBoundary
        key={mode}
        fallback={() => (
          <GraphCrashFallback crashedMode={mode} graphProps={props} heal={setMode} />
        )}
      >
        {mode === "2d" ? (
          <KnowledgeGraph2D {...props} />
        ) : (
          <KnowledgeGraph3D {...props} />
        )}
      </ErrorBoundary>
      <button
        type="button"
        data-testid="graph-mode-toggle"
        className="btn btn--ghost btn--sm"
        onClick={() => setMode(next)}
        disabled={!webglOk}
        title={webglOk ? `Switch to ${next.toUpperCase()} graph` : "3D requires WebGL"}
        aria-label={webglOk ? `Switch to ${next.toUpperCase()} graph` : "3D requires WebGL"}
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
