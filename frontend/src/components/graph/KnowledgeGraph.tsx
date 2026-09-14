"use client";

/**
 * KnowledgeGraph — wrapper that toggles between the 2D SVG/d3-force
 * and the 3D WebGL/three.js implementations.
 *
 * Defaults to 2D. The mode is persisted in localStorage and synced
 * across mounted instances via the `storage` event plus a same-tab
 * custom event so toggling on one graph updates them all.
 *
 * #538: the persisted mode is a WISH, not a command. Three r163+
 * throws from the WebGLRenderer constructor when WebGL2 is
 * unavailable, so the wrapper derives the EFFECTIVE mode from the
 * persisted wish + a capability probe, and contains any residual
 * renderer crash in a graph-local error boundary. The persisted
 * preference is never rewritten by capability or crashes — it survives
 * for the profile's WebGL-capable browsers.
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

// Exported for the unit tests; the e2e journey mirrors the literals by
// comment convention (it cannot import from src/).
export const GRAPH_MODE_STORAGE_KEY = "sapling.kg.mode";
export const GRAPH_MODE_SYNC_EVENT = "sapling:kg-mode-change";
const STORAGE_KEY = GRAPH_MODE_STORAGE_KEY;
const SYNC_EVENT = GRAPH_MODE_SYNC_EVENT;

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
 * obtainable. The verdict is memoized module-wide (a real probe is a
 * 5–50ms GPU-process handshake — slowest exactly on the software-
 * rasterized machines this gate protects); `force` re-probes, and the
 * crash-containment path uses it as the one signal that capability may
 * have changed since the cache was primed. The probe context is
 * released via WEBGL_lose_context so probes never count toward the
 * browser's per-page live-context cap.
 */
let webgl2Verdict: boolean | null = null;
export function probeWebgl2(force = false): boolean {
  if (!force && webgl2Verdict !== null) return webgl2Verdict;
  try {
    const ctx = document.createElement("canvas").getContext("webgl2");
    if (ctx) {
      ctx.getExtension?.("WEBGL_lose_context")?.loseContext();
      webgl2Verdict = true;
    } else {
      webgl2Verdict = false;
    }
  } catch {
    webgl2Verdict = false;
  }
  return webgl2Verdict;
}

function writeMode(mode: Mode) {
  try {
    window.localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // ignore quota / privacy mode failures — toggle still works in-tab
  }
  window.dispatchEvent(new CustomEvent<Mode>(SYNC_EVENT, { detail: mode }));
}

/**
 * The raw persisted/synced mode — deliberately UNGATED. Capability
 * gating happens exactly once, where the wrapper derives `effective`
 * from this wish at render; gating the listeners or the setter would
 * re-encode the same rule in three places (and rewrite state the
 * ignore-don't-rewrite contract says to leave alone).
 */
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

const SR_ONLY: React.CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0,0,0,0)",
  whiteSpace: "nowrap",
  border: 0,
};

/**
 * Crash fallback for the graph slot (#538). Renders a static
 * placeholder — NEVER another graph component: an error thrown while
 * rendering a boundary's own fallback cannot be caught by that
 * boundary and would escape to the root error page, the exact
 * whole-app collapse this wrapper exists to prevent. Recovery instead
 * flows through the parent: `onCrash` re-probes capability pre-paint,
 * and if WebGL2 is really gone the parent's `effective` mode flips,
 * changing the boundary's key and mounting the 2D graph inside a
 * FRESH boundary. For transient crashes the placeholder stays up with
 * the boundary's own reset wired to "Try again".
 */
function GraphCrashFallback({
  crashedMode,
  error,
  reset,
  onCrash,
}: {
  crashedMode: Mode;
  error: Error;
  reset: () => void;
  onCrash: (crashed: Mode, error: unknown) => void;
}) {
  const fired = React.useRef(false);
  // Layout effect: pre-paint, so a capability downgrade swaps in the 2D
  // graph without a painted placeholder flash — and the discarded
  // fallback never boots a graph, keeping test-mode PRNG consumption
  // identical to a clean load.
  React.useLayoutEffect(() => {
    if (fired.current) return;
    fired.current = true;
    onCrash(crashedMode, error);
  }, [crashedMode, error, onCrash]);
  return (
    <div
      role="status"
      data-testid="graph-crash-fallback"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        alignItems: "center",
        justifyContent: "center",
        height: "100%",
        color: "var(--text-dim)",
        fontSize: 13,
      }}
    >
      <span>The graph couldn&apos;t render here.</span>
      <button
        type="button"
        data-testid="graph-crash-retry"
        className="btn btn--ghost btn--sm"
        onClick={reset}
      >
        Try again
      </button>
    </div>
  );
}

export function KnowledgeGraph(props: Props) {
  const [mode, setMode] = useGraphMode();
  // Optimistic `true` matches the SSR markup; the mount effect corrects
  // it in the same effect flush that first moves `mode` off "2d", so the
  // 3D renderer can never mount against an unprobed verdict.
  const [webglOk, setWebglOk] = React.useState(true);
  React.useEffect(() => {
    setWebglOk(probeWebgl2());
  }, []);

  // THE one encoding of the #538 rule: a persisted/synced "3d" wish is
  // ignored — not rewritten — while WebGL2 is unavailable.
  const effective: Mode = webglOk ? mode : "2d";
  const next: Mode = effective === "2d" ? "3d" : "2d";
  const { width = 800, height = 480 } = props;
  const descId = React.useId();

  const handleCrash = React.useCallback((crashed: Mode, error: unknown) => {
    // The shared ErrorBoundary only logs outside production; graph
    // crashes at real users must stay operationally visible.
    console.error(
      `[KnowledgeGraph] ${crashed.toUpperCase()} renderer crashed:`,
      error,
    );
    // A 3D crash is the one signal the cached capability verdict may be
    // stale (GPU process died, context cap hit): re-probe. Really gone →
    // `effective` flips to 2D, preference untouched. Still fine → the
    // crash was transient; the placeholder + retry handle it.
    if (crashed === "3d") setWebglOk(probeWebgl2(true));
  }, []);

  return (
    <div data-testid="graph-container" style={{ position: "relative", width, height }}>
      {/* Local boundary so a renderer failure degrades in place instead
          of unmounting the whole app into the root fallback (#538).
          Keyed by the EFFECTIVE mode: a capability downgrade or a mode
          toggle remounts a fresh boundary, so an errored slot never
          wedges the other renderer. */}
      <ErrorBoundary
        key={effective}
        fallback={(error, reset) => (
          <GraphCrashFallback
            crashedMode={effective}
            error={error}
            reset={reset}
            onCrash={handleCrash}
          />
        )}
      >
        {effective === "2d" ? (
          <KnowledgeGraph2D {...props} />
        ) : (
          <KnowledgeGraph3D {...props} />
        )}
      </ErrorBoundary>
      <button
        type="button"
        data-testid="graph-mode-toggle"
        className="btn btn--ghost btn--sm"
        onClick={() => {
          if (webglOk) setMode(next);
        }}
        // aria-disabled, NOT native disabled: a natively disabled button
        // leaves the tab order, making the "requires WebGL" reason
        // unreachable to keyboard and screen-reader users. The accessible
        // NAME stays the action; the reason rides aria-describedby.
        aria-disabled={!webglOk}
        aria-describedby={webglOk ? undefined : descId}
        title={webglOk ? `Switch to ${next.toUpperCase()} graph` : "3D requires WebGL"}
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
          ...(webglOk ? null : { opacity: 0.55, cursor: "not-allowed" }),
        }}
      >
        {effective.toUpperCase()}
      </button>
      {!webglOk && (
        <span id={descId} style={SR_ONLY}>
          3D requires WebGL, which this browser doesn&apos;t have available.
        </span>
      )}
    </div>
  );
}
