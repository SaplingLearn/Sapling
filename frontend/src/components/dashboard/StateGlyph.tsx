import React from "react";

import { SOURCE_GRAPH_PALETTE, TIER_LABEL, type MasteryTier } from "@/lib/graph/nodeStyle";
import styles from "./Dashboard.module.css";

/**
 * A tier's mark: its source-palette colour AND a distinct shape (full disc,
 * half disc, triangle, ring), with an ink outline, so the four states stay
 * distinguishable without colour. Decorative: the tier NAME is always
 * rendered as text next to it.
 */
export function StateGlyph({ tier }: { tier: MasteryTier }) {
  const fill = SOURCE_GRAPH_PALETTE[tier];
  const stroke = "#253D2F";
  let shape: React.ReactNode;
  switch (tier) {
    case "mastered":
      shape = <circle cx="6" cy="6" r="5" fill={fill} stroke={stroke} strokeWidth="1" />;
      break;
    case "learning":
      shape = (
        <>
          <circle cx="6" cy="6" r="5" fill="#F7F4E9" stroke={stroke} strokeWidth="1" />
          <path d="M6 1a5 5 0 0 1 0 10Z" fill={fill} stroke={stroke} strokeWidth="1" />
        </>
      );
      break;
    case "struggling":
      shape = <path d="M6 1 11 10.5H1Z" fill={fill} stroke={stroke} strokeWidth="1" strokeLinejoin="round" />;
      break;
    default:
      shape = <circle cx="6" cy="6" r="4.5" fill={fill} stroke={stroke} strokeWidth="1" strokeDasharray="2 1.5" />;
  }
  return (
    <svg className={styles.glyph} viewBox="0 0 12 12" aria-hidden="true" focusable="false">
      {shape}
    </svg>
  );
}

export const TIERS: readonly MasteryTier[] = ["mastered", "learning", "struggling", "unexplored"];

export function tierOf(t: string | null | undefined): MasteryTier {
  return t && t in TIER_LABEL ? (t as MasteryTier) : "unexplored";
}
