"use client";

/**
 * KnowledgeGraph — the sized, crash-contained slot every screen mounts the
 * knowledge graph through. Renders the 2D SVG/d3-force graph plus the
 * colour-mode toggle.
 *
 * Colour modes (`lib/graph/nodeStyle::GraphColorMode`):
 *   - `course`  (default) — course colours, mastery tier as opacity.
 *   - `mastery` — one colour per mastery tier, brown course hubs, edges that
 *                 blend between their endpoints; a small legend explains it.
 * The choice persists in localStorage and is synced across mounted graphs
 * (the `storage` event for other tabs plus a same-tab custom event), so
 * flipping it on one graph flips every graph.
 *
 * (A 3D WebGL/three.js mode used to live behind a 2D⇄3D toggle in this same
 * corner; it was dropped. A stale `sapling.kg.mode` value is simply ignored.)
 *
 * The graph-local error boundary (#538) stays: a renderer failure degrades
 * to a placeholder in place instead of unmounting the whole app into the
 * root error page.
 */

import React from "react";
import type { GraphEdge, GraphNode } from "@/lib/data";
import {
  MASTERY_PALETTE,
  TIER_LABEL,
  type GraphColorMode,
  type MasteryTier,
} from "@/lib/graph/nodeStyle";
import { KnowledgeGraph2D } from "./KnowledgeGraph2D";
import { ErrorBoundary } from "../ErrorBoundary";

// Exported for the unit tests; e2e journeys mirror the literal by comment
// convention (they cannot import from src/).
export const GRAPH_COLOR_STORAGE_KEY = "sapling.kg.colors";
export const GRAPH_COLOR_SYNC_EVENT = "sapling:kg-colors-change";

function parseMode(v: unknown): GraphColorMode {
  return v === "mastery" ? "mastery" : "course";
}

function readColorMode(): GraphColorMode {
  try {
    return parseMode(window.localStorage.getItem(GRAPH_COLOR_STORAGE_KEY));
  } catch {
    return "course";
  }
}

function useGraphColorMode(): [GraphColorMode, (m: GraphColorMode) => void] {
  // SSR and the first client paint both render "course", so hydration
  // matches; the effect then applies the stored choice.
  const [mode, setMode] = React.useState<GraphColorMode>("course");
  React.useEffect(() => {
    setMode(readColorMode());
    const onStorage = (e: StorageEvent) => {
      if (e.key === GRAPH_COLOR_STORAGE_KEY) setMode(parseMode(e.newValue));
    };
    const onSync = (e: Event) => setMode(parseMode((e as CustomEvent).detail));
    window.addEventListener("storage", onStorage);
    window.addEventListener(GRAPH_COLOR_SYNC_EVENT, onSync);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(GRAPH_COLOR_SYNC_EVENT, onSync);
    };
  }, []);
  const update = React.useCallback((next: GraphColorMode) => {
    setMode(next);
    try {
      window.localStorage.setItem(GRAPH_COLOR_STORAGE_KEY, next);
    } catch {
      // quota / privacy mode — the toggle still works for this page
    }
    window.dispatchEvent(new CustomEvent(GRAPH_COLOR_SYNC_EVENT, { detail: next }));
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
  /** 2D only: top offset of the zoom stack, for a host that puts its own
   *  control (the Tree's Fullscreen icon) in the corner above it. */
  zoomControlsTop?: number;
  /** 2D only: Obsidian-style legibility (hover focus, zoom-faded labels,
   *  importance sizing, arrows, course legend). The Tree turns it on. */
  legible?: boolean;
  /** 2D legible: course focus / hover / zoom, wired to the host's course key. */
  focusCourseId?: string | null;
  onHoverCourse?: (courseId: string | null) => void;
  zoomRequest?: { courseId: string; seq: number } | null;
};

const TIERS: MasteryTier[] = ["mastered", "learning", "struggling", "unexplored"];

const PANEL: React.CSSProperties = {
  position: "absolute",
  left: 12,
  background: "var(--bg-panel)",
  border: "1px solid var(--border)",
  borderRadius: "var(--r-sm)",
  boxShadow: "var(--shadow-sm)",
  zIndex: 5,
};

/** Four overlapping tier dots — the toggle's glyph. */
function PaletteGlyph() {
  return (
    <svg width={22} height={12} viewBox="0 0 22 12" aria-hidden="true" style={{ display: "block" }}>
      {TIERS.map((t, i) => (
        <circle key={t} cx={5 + i * 4} cy={6} r={4.5} fill={MASTERY_PALETTE[t]} />
      ))}
    </svg>
  );
}

/**
 * Crash fallback for the graph slot. Renders a static placeholder — NEVER
 * another graph component: an error thrown while rendering a boundary's own
 * fallback cannot be caught by that boundary and would escape to the root
 * error page, the exact whole-app collapse this wrapper exists to prevent.
 */
function GraphCrashFallback({ error, reset }: { error: Error; reset: () => void }) {
  const fired = React.useRef(false);
  React.useEffect(() => {
    if (fired.current) return;
    fired.current = true;
    // The shared ErrorBoundary only logs outside production; graph crashes
    // at real users must stay operationally visible.
    console.error("[KnowledgeGraph] renderer crashed:", error);
  }, [error]);
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
  const { width = 800, height = 480 } = props;
  const [colorMode, setColorMode] = useGraphColorMode();
  const mastery = colorMode === "mastery";
  return (
    <div data-testid="graph-container" style={{ position: "relative", width, height }}>
      <ErrorBoundary fallback={(error, reset) => <GraphCrashFallback error={error} reset={reset} />}>
        <KnowledgeGraph2D {...props} colorMode={colorMode} />
      </ErrorBoundary>
      <button
        type="button"
        data-testid="graph-color-toggle"
        className="btn btn--ghost btn--sm"
        // Constant name + aria-pressed: the label says what the switch
        // turns on, the pressed state says whether it is on.
        aria-pressed={mastery}
        title={mastery ? "Back to course colors" : "Color nodes by mastery"}
        onClick={() => setColorMode(mastery ? "course" : "mastery")}
        style={{
          ...PANEL,
          top: 12,
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "3px 8px",
          fontSize: 11,
          ...(mastery
            ? { borderColor: MASTERY_PALETTE.hub, color: MASTERY_PALETTE.hub, fontWeight: 600 }
            : null),
        }}
      >
        <PaletteGlyph />
        <span>Mastery colors</span>
      </button>
      {mastery && (
        <ul
          data-testid="graph-color-legend"
          aria-label="Mastery colors"
          style={{
            ...PANEL,
            bottom: 12,
            listStyle: "none",
            margin: 0,
            padding: "6px 10px",
            display: "flex",
            flexWrap: "wrap",
            gap: "4px 12px",
            fontSize: 11,
            color: "var(--text-dim)",
            maxWidth: width - 24,
          }}
        >
          {TIERS.map((t) => (
            <li key={t} style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <span
                aria-hidden="true"
                style={{
                  width: 9,
                  height: 9,
                  borderRadius: "50%",
                  background: MASTERY_PALETTE[t],
                }}
              />
              {TIER_LABEL[t]}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
