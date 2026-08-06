/**
 * Pure helpers for the 3D knowledge graph ("Focused Minimal", spec
 * 2026-08-05). No three.js imports here — everything is deterministic
 * and unit-testable without mocks.
 *
 * Color contract: every function that returns a color returns #rrggbb
 * hex. Three.js's Color.setStyle silently renders space-separated
 * hsl() as BLACK, and cannot resolve CSS var() — resolved hex is the
 * only safe currency (see lib/data.ts).
 */

import { hashSeed, type GraphEdge, type GraphNode } from "@/lib/data";

export const NODE_OPACITY = 0.95;
export const DIM_NODE_OPACITY = 0.18;
export const DIM_LABEL_OPACITY = 0.12;
export const BASE_LINK_ALPHA = 0.45;
export const LIT_LINK_ALPHA = 0.85;
export const DIM_LINK_ALPHA = 0.06;

export type GraphTheme = {
  ink: string; // label text
  dim: string; // dimmed node / unexplored wash
  accent: string; // focus halo + highlighted node
};

// Hex mirrors of the app-shell tokens (globals.css): --ink-600,
// --ink-200, --accent. Used verbatim under SSR/jsdom where
// getComputedStyle can't resolve them.
export const FALLBACK_THEME: GraphTheme = {
  ink: "#3f3b31",
  dim: "#ddd6c6",
  accent: "#8a9a5b",
};

/** Resolve theme tokens to hex once per mount; hex fallbacks otherwise. */
export function resolveGraphTheme(): GraphTheme {
  if (typeof window === "undefined") return FALLBACK_THEME;
  const s = getComputedStyle(document.documentElement);
  const read = (name: string, fb: string) => {
    const raw = s.getPropertyValue(name).trim();
    return /^#[0-9a-f]{6}$/i.test(raw) ? raw : fb;
  };
  return {
    ink: read("--ink-600", FALLBACK_THEME.ink),
    dim: read("--ink-200", FALLBACK_THEME.dim),
    accent: read("--accent", FALLBACK_THEME.accent),
  };
}

/* ── moved verbatim from KnowledgeGraph3D.tsx ─────────────────────── */

function hexToHsl(hex: string): { h: number; s: number; l: number } | null {
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

function hslToHex(h: number, s: number, l: number): string {
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

export function shadeFor(baseHex: string, nodeId: string): string {
  const hsl = hexToHsl(baseHex);
  if (!hsl) return baseHex;
  const seed = hashSeed(nodeId);
  const dh = (seed % 51) - 25;
  const ds = ((seed >> 5) % 17) - 8;
  const dl = ((seed >> 10) % 25) - 12;
  const h = (hsl.h + dh + 360) % 360;
  const s = Math.max(20, Math.min(85, hsl.s + ds));
  const l = Math.max(28, Math.min(62, hsl.l + dl));
  // Return hex (#RRGGBB), not `hsl(...)`. Three.js's Color.setStyle only
  // accepts comma-separated `hsl(h, s%, l%)`, not the modern
  // space-separated form; the space-separated string silently renders
  // BLACK. Hex is unambiguous across consumers.
  return hslToHex(h, s, l);
}

/* ── new helpers ──────────────────────────────────────────────────── */

/** Channelwise linear blend of two #rrggbb colors; t=0 → a, t=1 → b. */
export function mixHex(a: string, b: string, t: number): string {
  const pa = /^#?([0-9a-f]{6})$/i.exec(a.trim());
  const pb = /^#?([0-9a-f]{6})$/i.exec(b.trim());
  if (!pa || !pb) return a;
  const ca = parseInt(pa[1], 16);
  const cb = parseInt(pb[1], 16);
  const mix = (x: number, y: number) => Math.round(x + (y - x) * t);
  const r = mix((ca >> 16) & 255, (cb >> 16) & 255);
  const g = mix((ca >> 8) & 255, (cb >> 8) & 255);
  const bl = mix(ca & 255, cb & 255);
  return `#${((r << 16) | (g << 8) | bl).toString(16).padStart(6, "0")}`;
}

/** Undirected 1-hop adjacency from the edge list. */
export function buildAdjacency(edges: GraphEdge[]): Map<string, Set<string>> {
  const adj = new Map<string, Set<string>>();
  for (const e of edges) {
    if (!adj.has(e.source)) adj.set(e.source, new Set());
    if (!adj.has(e.target)) adj.set(e.target, new Set());
    adj.get(e.source)!.add(e.target);
    adj.get(e.target)!.add(e.source);
  }
  return adj;
}

/**
 * Same visual scale the old `nodeVal` accessor produced: concepts
 * 4..10 with mastery, subject roots pinned to 22.
 */
export function nodeVal(n: GraphNode): number {
  if (n.is_subject_root) return 22;
  return 4 + (typeof n.mastery_score === "number" ? n.mastery_score : 0) * 6;
}

/**
 * react-force-graph's default sphere radius is cbrt(val) * nodeRelSize
 * (nodeRelSize defaults to 4). Reproducing that mapping keeps our
 * custom spheres exactly the size users see today.
 */
export function nodeRadius(n: GraphNode): number {
  return Math.cbrt(nodeVal(n)) * 4;
}

/**
 * Course-colored deterministic shade; unexplored concept nodes wash
 * 65% toward the theme's dim gray so attention lands on studied
 * material. Subject roots always keep full color.
 */
export function baseNodeColor(n: GraphNode, theme: GraphTheme): string {
  const shaded = shadeFor(n.color || theme.accent, n.id);
  if (n.mastery_tier === "unexplored" && !n.is_subject_root) {
    return mixHex(shaded, theme.dim, 0.65);
  }
  return shaded;
}

export type LabelSpec = { textHeight: number; fontWeight: string };

/** Root labels render larger and bold; concepts small and regular. */
export function labelSpec(n: GraphNode): LabelSpec {
  return n.is_subject_root
    ? { textHeight: 5, fontWeight: "700" }
    : { textHeight: 3.2, fontWeight: "400" };
}
