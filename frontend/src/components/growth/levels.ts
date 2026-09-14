import type { RarityTier } from "@/lib/types";

// Disc palettes copied verbatim from the design's disc() map:
// band = outer ring, gl/gd = inner radial gradient stops, br = border ring.
export const RARITY_DISC: Record<RarityTier, { band: string; gl: string; gd: string; br: string }> = {
  common:    { band: "#c9c6bd", gl: "#a8a498", gd: "#807b6d", br: "#645f51" },
  uncommon:  { band: "#a7c49a", gl: "#7a9e79", gd: "#4f7757", br: "#38603f" },
  rare:      { band: "#9ad3d8", gl: "#72bcc3", gd: "#3f8f98", br: "#2f727a" },
  epic:      { band: "#cdb9f6", gl: "#ab8ef0", gd: "#8059d6", br: "#6842b8" },
  legendary: { band: "#eed79c", gl: "#dcbd6f", gd: "#b4934a", br: "#8f7333" },
};

export const LOCKED_DISC = { band: "#eceae4", gl: "#ffffff", gd: "#e4e1d8", br: "#c3bfb2" };

export function discFor(rarity: RarityTier, locked: boolean) {
  if (locked) return LOCKED_DISC;
  return RARITY_DISC[rarity] ?? RARITY_DISC.common;
}

export const STAGE_SLUGS = [
  "bare", "soil", "seed", "sprout", "seedling",
  "sapling", "young", "branch", "bloom", "fruit", "old",
] as const;

export function stageAssetPath(slug: string): string {
  return `/growth/${slug}.svg`;
}
