"use client";
import React from "react";
import { createPortal } from "react-dom";

import { useOverlayBehaviour } from "@/components/Dialog";
import { KnowledgeGraph } from "@/components/graph/KnowledgeGraph";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { useBoxSize } from "./KnowledgeMap";
import styles from "./Dashboard.module.css";

/**
 * Deliberate, full-screen map exploration ("Open full map"): the
 * interactive graph (pan/drag/zoom/reset, 2D/3D with the persisted
 * preference and the no-WebGL fallback) beside the selected topic's
 * details. A labelled modal dialog: focus moves in, Tab stays in, Escape
 * and Close return focus to the opener (Dialog's useOverlayBehaviour, which
 * also locks the shell's inner scroll container). Scope and selection are
 * the page's own state, so closing keeps both.
 */
export function FullMap({
  open,
  onClose,
  scopeLabel,
  nodes,
  edges,
  selectedId,
  highlightId,
  onSelect,
  side,
}: {
  open: boolean;
  onClose: () => void;
  scopeLabel: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  highlightId?: string;
  onSelect: (n: GraphNode) => void;
  /** The selected topic's details, or a hint. */
  side: React.ReactNode;
}) {
  const closeRef = React.useRef<HTMLButtonElement>(null);
  const { mounted, panelRef, onKeyDown } = useOverlayBehaviour({ open, onClose, initialFocusRef: closeRef });
  const [size, boxRef] = useBoxSize({ w: 900, h: 600 });
  const titleId = React.useId();

  if (!mounted || !open) return null;
  return createPortal(
    <div className={`sapling-surface ${styles.mapDialogBackdrop}`} onKeyDown={onKeyDown}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={styles.mapDialog}
        data-testid="dashboard-full-map"
      >
        <div className={styles.mapDialogHead}>
          <div>
            <h2 id={titleId} className={styles.mapDialogTitle}>Your knowledge map</h2>
            <p className={styles.counts}>{scopeLabel} · drag to move, scroll or use + / − to zoom, Esc to close</p>
          </div>
          <button ref={closeRef} type="button" className={styles.mapDialogClose} onClick={onClose} data-testid="dashboard-full-map-close">
            Close
          </button>
        </div>
        <div className={styles.mapDialogBody}>
          <div ref={boxRef} className={styles.mapDialogCanvas}>
            <KnowledgeGraph
              appearance="sapling"
              nodes={nodes}
              edges={edges}
              width={size.w}
              height={size.h}
              selectedId={selectedId}
              highlightId={highlightId}
              onNodeClick={onSelect}
            />
          </div>
          <div className={styles.mapDialogSide} data-testid="dashboard-full-map-side">{side}</div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
