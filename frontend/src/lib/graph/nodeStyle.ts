/**
 * nodeStyle — how a concept node is painted, as pure functions.
 *
 * Extracted verbatim from `KnowledgeGraph2D` / `KnowledgeGraph3D` (#537),
 * which each carried their own byte-identical copy of `hexToHsl` + `shadeFor`
 * and their own tier→opacity / mastery→radius tables. Both renderers now
 * import from here, and so do the quiz surfaces (`ConceptNode`,
 * `ConceptNeighbourhood`), so a retune moves the tree and the quiz together
 * instead of drifting them apart.
 *
 * Nothing here touches React, d3 or the DOM: these are arithmetic, and the
 * renderers evaluate them during render, outside the simulation tick.
 *
 * Two things this module deliberately does NOT own:
 *   - the force-collide radius (`is_subject_root ? 36 : 18 + mastery * 6`,
 *     KnowledgeGraph2D). That is a *layout* radius, not a visual one; the two
 *     have always differed and the simulation keeps it.
 *   - `hashSeed`. It already lives in `lib/data.ts` and is shared. Note the
 *     unrelated same-named DJB2 hash in `Gradebook/CourseCard.tsx` — importing
 *     this one there would reshuffle every course watermark.
 */

import { hashSeed } from "@/lib/data";

export type MasteryTier = "mastered" | "learning" | "struggling" | "unexplored";

/** `#rrggbb` (with or without the hash) → HSL, or null for anything else —
 *  notably `var(--token)` strings, which callers pass straight through. */
export function hexToHsl(hex: string): { h: number; s: number; l: number } | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const r = parseInt(m[1].slice(0, 2), 16) / 255;
  const g = parseInt(m[1].slice(2, 4), 16) / 255;
  const b = parseInt(m[1].slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b),
    min = Math.min(r, g, b),
    l = (max + min) / 2;
  let h = 0,
    s = 0;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) * 60;
    else if (max === g) h = ((b - r) / d + 2) * 60;
    else h = ((r - g) / d + 4) * 60;
  }
  return { h, s: s * 100, l: l * 100 };
}

export function hslToHex(h: number, s: number, l: number): string {
  const sN = s / 100;
  const lN = l / 100;
  const c = (1 - Math.abs(2 * lN - 1)) * sN;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = lN - c / 2;
  let r = 0,
    g = 0,
    b = 0;
  if (h < 60) [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  const to = (v: number) =>
    Math.round((v + m) * 255)
      .toString(16)
      .padStart(2, "0");
  return `#${to(r)}${to(g)}${to(b)}`;
}

/**
 * Deterministic per-node shade derived from the course colour + node id.
 * Keeps each course visually unified while giving every node its own tone,
 * and produces identical output across pages because it depends only on the
 * stable inputs (no per-screen overrides).
 *
 * `as` picks the output form, and the choice is load-bearing:
 *   - `"css"` (default) → `hsl(h s% l%)`, what the SVG renderers use.
 *   - `"hex"` → `#rrggbb`, what the 3D renderer MUST use. Three.js's
 *     `Color.setStyle` only accepts the comma-separated `hsl(h, s%, l%)`
 *     form; the modern space-separated string silently renders BLACK.
 *
 * A non-hex base (e.g. `var(--c-sage)`) can't be jittered, so it passes
 * through unchanged — which silently disables shading. Callers that care
 * resolve the colour to hex first (`apiToGraphNode` does).
 */
export function shadeFor(baseHex: string, nodeId: string, as: "css" | "hex" = "css"): string {
  const hsl = hexToHsl(baseHex);
  if (!hsl) return baseHex;
  const seed = hashSeed(nodeId);
  const dh = (seed % 51) - 25;
  const ds = ((seed >> 5) % 17) - 8;
  const dl = ((seed >> 10) % 25) - 12;
  const h = (hsl.h + dh + 360) % 360;
  const s = Math.max(20, Math.min(85, hsl.s + ds));
  const l = Math.max(28, Math.min(62, hsl.l + dl));
  if (as === "hex") return hslToHex(h, s, l);
  return `hsl(${h.toFixed(0)} ${s.toFixed(0)}% ${l.toFixed(0)}%)`;
}

/** Visual radius of a concept mark, in the tree's own units. Subject roots are
 *  a flat 22 — they anchor a family and don't encode mastery. */
export function radiusFor(mastery: number, isRoot = false): number {
  if (isRoot) return 22;
  return 8 + (mastery || 0) * 12;
}

/**
 * score → tier. Mirrors `backend/config.py::get_mastery_tier`
 * (MASTERY_MASTERED_MIN 0.75 / MASTERY_LEARNING_MIN 0.45 /
 * MASTERY_STRUGGLING_MIN 0.1), pinned by the table test next to this file.
 *
 * Read the server's `mastery_tier` string wherever there is one — every graph
 * node carries it. This exists for the one case that has a score and no tier:
 * the quiz submit response's `mastery_after` (#537 R-12).
 */
export function tierFor(score: number): MasteryTier {
  if (score >= 0.75) return "mastered";
  if (score >= 0.45) return "learning";
  if (score >= 0.1) return "struggling";
  return "unexplored";
}

/** How the mark encodes its tier. Mirrored by `e2e/graph.spec.ts`'s
 *  TIER_OPACITY — a retune updates both in the same PR. */
export const TIER_OPACITY: Record<MasteryTier, number> = {
  mastered: 1,
  learning: 0.78,
  struggling: 0.55,
  unexplored: 0.28,
};

/**
 * Tier → opacity, tolerant of the strings that actually arrive on the wire.
 * `subject_root` reads as fully opaque (roots don't encode mastery); anything
 * else unrecognised falls to 0.6, exactly as the renderer's `|| 0.6` did.
 */
export function opacityFor(tier: string): number {
  if (tier === "subject_root") return 1;
  return TIER_OPACITY[tier as MasteryTier] ?? 0.6;
}

/** Edge stroke width from its 0..1 strength → 0.5 … 1.7. The backend's
 *  hub-spoke edges ship a fixed 0.7 (graph_service.py), i.e. 1.34. */
export function edgeWidthFor(strength: number): number {
  return 0.5 + (strength || 0.5) * 1.2;
}

/** The tree's concept-label rule: anything longer than `max` is cut to
 *  `max - 1` characters plus an ellipsis. Mirrored by `e2e/graph.spec.ts`. */
export function truncateLabel(name: string, max = 18): string {
  return name.length > max ? name.slice(0, max - 1) + "…" : name;
}

/** Resting stroke opacity of the node body. The tree raises it on hover (0.9)
 *  and while drag-pinned (1.0); static surfaces stay at rest. */
export const NODE_STROKE_OPACITY = 0.4;

/** The soft halo behind an `organism` node: a blurred disc at `r + pad`. */
export const GLOW = { pad: 8, opacity: 0.15, blur: 3 } as const;
