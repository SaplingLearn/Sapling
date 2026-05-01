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
        color: `var(--rarity-${rarity})`,
        background: `var(--rarity-${rarity}-bg)`,
        ...style,
      }}
    >
      {cosmetic.name}
    </span>
  );
}
