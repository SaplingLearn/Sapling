"use client";

import React from "react";
import type { Cosmetic } from "@/lib/types";
import { Badge } from "@/components/ui";

interface TitleFlairProps {
  cosmetic?: Cosmetic | null;
  className?: string;
  style?: React.CSSProperties;
}

export function TitleFlair({ cosmetic, className, style }: TitleFlairProps) {
  if (!cosmetic) return null;
  const rarity = cosmetic.rarity ?? "common";
  // The rarity hue is carried by the border + soft bg; the text stays neutral
  // (Badge enforces this) — colored text fails 4.5:1 on several tiers.
  return (
    <Badge
      className={className}
      color={`var(--rarity-${rarity})`}
      bg={`var(--rarity-${rarity}-bg)`}
      style={style}
    >
      {cosmetic.name} · {rarity}
    </Badge>
  );
}
