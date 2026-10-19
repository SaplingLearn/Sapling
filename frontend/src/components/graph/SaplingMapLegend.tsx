import React from "react";

import { SOURCE_GRAPH_PALETTE, TIER_LABEL, type MasteryTier } from "@/lib/graph/nodeStyle";
import styles from "./SaplingMapLegend.module.css";

const TIERS: readonly MasteryTier[] = ["mastered", "learning", "struggling", "unexplored"];

/**
 * The ONE legend for every `appearance="sapling"` map (Home, Learn's rail,
 * the tutor's map panel). Swatches come from the same SOURCE_GRAPH_PALETTE
 * the renderer fills nodes with, so a legend can't describe colours the
 * canvas doesn't draw. A disc per state, exactly as the canvas draws the
 * node (the map encodes state by fill only; the text names it).
 */
export function SaplingMapLegend({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <ul className={`${styles.legend} ${compact ? styles.compact : ""} ${className ?? ""}`} aria-label="Map key" data-testid="graph-legend">
      {TIERS.map((t) => (
        <li key={t}>
          <svg className={styles.swatch} viewBox="0 0 12 12" aria-hidden="true" focusable="false">
            <circle cx="6" cy="6" r="5.5" fill={SOURCE_GRAPH_PALETTE[t]} />
          </svg>
          {TIER_LABEL[t]}
        </li>
      ))}
      <li className={styles.note}>Brown circles are courses. Color shows the recorded knowledge state.</li>
    </ul>
  );
}
