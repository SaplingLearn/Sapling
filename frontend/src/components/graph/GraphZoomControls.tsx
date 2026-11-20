"use client";

import React from "react";

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
  /** Top offset of the stack (12 = flush with the corner). */
  top: number;
  /** Zoom by this factor (in: 1.25, out: 1 / 1.25). */
  onZoom: (factor: number) => void;
  onReset: () => void;
}) {
  return (
    <div
      data-testid="graph-zoom-controls"
      style={{
        position: "absolute",
        top,
        right: 12,
        display: "flex",
        flexDirection: "column",
        gap: 4,
        background: "var(--bg-panel)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-sm)",
        padding: 4,
        boxShadow: "var(--shadow-sm)",
      }}
    >
      <button
        data-testid="graph-zoom-in"
        className="btn btn--ghost btn--sm"
        style={{ padding: "2px 8px", fontFamily: "var(--font-mono)" }}
        onClick={() => onZoom(1.25)}
        title="Zoom in"
      >
        +
      </button>
      <button
        data-testid="graph-zoom-out"
        className="btn btn--ghost btn--sm"
        style={{ padding: "2px 8px", fontFamily: "var(--font-mono)" }}
        onClick={() => onZoom(1 / 1.25)}
        title="Zoom out"
      >
        −
      </button>
      <button
        data-testid="graph-zoom-reset"
        className="btn btn--ghost btn--sm"
        style={{ padding: "2px 8px", fontSize: 10 }}
        onClick={onReset}
        title="Reset view"
      >
        ⟲
      </button>
    </div>
  );
}
