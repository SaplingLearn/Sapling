"use client";

import React from "react";
import type { Cosmetic } from "@/lib/types";

interface TitleFlairProps {
  cosmetic?: Cosmetic | null;
  className?: string;
  style?: React.CSSProperties;
}

export function TitleFlair({ cosmetic, className, style }: TitleFlairProps) {
  if (!cosmetic) return null;
  const rarity = cosmetic.rarity ?? "common";
  // Rarity is never conveyed by colored text (fails 4.5:1 on several tiers);
  // the border carries the color and the literal tier name carries the cue.
  return (
    <span
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 8px",
        fontSize: 10,
        fontFamily: "var(--font-mono)",
        letterSpacing: "0.1em",
        textTransform: "uppercase",
        borderRadius: "var(--r-full)",
        border: `1px solid var(--rarity-${rarity})`,
        color: "var(--text)",
        background: `var(--rarity-${rarity}-bg)`,
        ...style,
      }}
    >
      {cosmetic.name} · {rarity}
    </span>
  );
}
