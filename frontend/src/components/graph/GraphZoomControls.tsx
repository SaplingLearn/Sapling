"use client";

import React from "react";

import s from "./graph.module.css";

/** Each press zooms by this factor (in) or its inverse (out). */
export const ZOOM_STEP = 1.25;

/**
 * The knowledge graph's zoom stack — in, out, reset — in the graph's top-right
 * corner. Markup only: KnowledgeGraph2D owns the view and passes the actions
 * in. (Moved out of KnowledgeGraph2D unchanged, so a host can leave it off —
 * the Tutor's session panel, a small overview that links to the full map.)
 */
export function GraphZoomControls({
  top,
  onZoom,
  onReset,
}: {
  /** Top offset of the stack in px (12, `--sp-6`, = flush with the corner). */
  top: number;
  /** Zoom by this factor (in: ZOOM_STEP, out: 1 / ZOOM_STEP). */
  onZoom: (factor: number) => void;
  onReset: () => void;
}) {
  return (
    // `top` is the host's, so it stays inline; the rest is graph.module.css.
    <div data-testid="graph-zoom-controls" className={s.zoom} style={{ top }}>
      <button
        data-testid="graph-zoom-in"
        className={`btn btn--ghost btn--sm ${s.zoomBtn}`}
        onClick={() => onZoom(ZOOM_STEP)}
        title="Zoom in"
      >
        +
      </button>
      <button
        data-testid="graph-zoom-out"
        className={`btn btn--ghost btn--sm ${s.zoomBtn}`}
        onClick={() => onZoom(1 / ZOOM_STEP)}
        title="Zoom out"
      >
        −
      </button>
      <button
        data-testid="graph-zoom-reset"
        className={`btn btn--ghost btn--sm ${s.zoomReset}`}
        onClick={onReset}
        title="Reset view"
      >
        ⟲
      </button>
    </div>
  );
}
