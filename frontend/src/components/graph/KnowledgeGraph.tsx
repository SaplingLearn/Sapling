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
 * flipping it on one graph flips every graph. A host that fixes the mode
 * (`colorMode`: the Tutor's session panel, which draws its own key under the
 * map) gets neither the toggle nor the in-graph key, and the stored choice
 * does not apply to it.
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
import styles from "./graph.module.css";
import {
  MASTERY_PALETTE,
  TIER_LABEL,
  TIER_OPACITY,
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
  /** W3.2: solid practiced outline by node id (forwarded to KnowledgeGraph2D). */
  practicedIds?: ReadonlySet<string> | readonly string[];
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
  zoomRequest?: { courseId: string | null; seq: number } | null;
  /** Fix the colour mode: no toggle and no in-graph key (the host shows the
   *  key), and the stored choice does not apply. Omitted: the shared toggle. */
  colorMode?: GraphColorMode;
  /** Keep every node and its caption in the window (see KnowledgeGraph2D). */
  fit?: boolean;
  /** Draw the zoom stack (default). */
  zoomControls?: boolean;
  /** `pinch`: only a pinch zooms, a plain wheel scrolls the host (see KnowledgeGraph2D). */
  wheelZoom?: "always" | "pinch";
};

const TIERS: MasteryTier[] = ["mastered", "learning", "struggling", "unexplored"];

/** Four overlapping tier dots — the toggle's glyph. */
function PaletteGlyph() {
  return (
    <svg width={22} height={12} viewBox="0 0 22 12" aria-hidden="true" className={styles.glyph}>
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
      className={styles.crash}
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
  const [storedMode, setColorMode] = useGraphColorMode();
  const fixed = props.colorMode !== undefined;
  const colorMode = props.colorMode ?? storedMode;
  const mastery = colorMode === "mastery";
  // The key fades in when the student flips the colours, not on first paint.
  const [switched, setSwitched] = React.useState(false);
  return (
    <div data-testid="graph-container" className={styles.container} style={{ width, height }}>
      <ErrorBoundary fallback={(error, reset) => <GraphCrashFallback error={error} reset={reset} />}>
        <KnowledgeGraph2D {...props} colorMode={colorMode} />
      </ErrorBoundary>
      {!fixed && (
        <button
          type="button"
          data-testid="graph-color-toggle"
          className={`btn btn--ghost btn--sm ${styles.toggle}${mastery ? ` ${styles.toggleOn}` : ""}`}
          // Constant name + aria-pressed: the label says what the switch
          // turns on, the pressed state says whether it is on.
          aria-pressed={mastery}
          title={mastery ? "Back to course colors" : "Color nodes by mastery"}
          onClick={() => {
            setSwitched(true);
            setColorMode(mastery ? "course" : "mastery");
          }}
          style={{ "--toggle-on": MASTERY_PALETTE.hub } as React.CSSProperties}
        >
          <PaletteGlyph />
          <span>Mastery colors</span>
        </button>
      )}
      {!fixed && (mastery || props.legible) && (
        // Mastery colors: one colour per tier. Course colors (legible graphs
        // only): the course's colour, with the tier carried by how solid the
        // node is, so the key shows the same dot at each tier's opacity.
        <ul
          data-testid={mastery ? "graph-color-legend" : "graph-tier-legend"}
          aria-label={mastery ? "Mastery colors" : "Mastery shown as how solid a node is"}
          key={mastery ? "mastery" : "tiers"}
          className={`${styles.panel} ${styles.legend}${switched ? ` ${styles.legendEnter}` : ""}`}
        >
          {TIERS.map((t) => (
            <li key={t} className={styles.legendItem}>
              <span
                aria-hidden="true"
                className={styles.legendDot}
                style={{
                  background: mastery ? MASTERY_PALETTE[t] : "var(--text)",
                  opacity: mastery ? 1 : TIER_OPACITY[t],
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
