/**
 * blobShape — the hand-drawn outline of a concept node, as pure functions.
 *
 * A node is no longer a perfect circle. Its outline is a circle of radius `r`
 * bent by three low harmonics:
 *
 *     radius(θ) = r · (1 + a2·sin(2θ + p2) + a3·sin(3θ + p3) + a4·sin(4θ + p4))
 *
 * The amplitudes and phases come from the node's id, so a concept keeps the
 * same shape on every screen and every render. There is no first harmonic: it
 * would only shift the shape off its centre, and the layout, the hit area and
 * the label all assume the mark sits on (cx, cy). The harmonics average to
 * zero, so a blob covers about the area of the circle it replaces and the
 * mastery → size reading is unchanged.
 *
 * `rimRadius` answers "where is the outline in this direction": links stop at
 * the drawn edge rather than at the nominal radius, so a link never floats
 * off a dent or stabs through a bulge.
 *
 * Nothing here touches React or the DOM.
 */

import { hashSeed } from "@/lib/data";

/** The outline's harmonics: amplitudes (fractions of the radius) and phases. */
export interface BlobProfile {
  readonly a2: number;
  readonly p2: number;
  readonly a3: number;
  readonly p3: number;
  readonly a4: number;
  readonly p4: number;
}

/** Points sampled around the outline. Three harmonics up to 4θ need few. */
const SAMPLES = 16;
const STEP = (Math.PI * 2) / SAMPLES;

/** mulberry32: a small seeded generator, so a shape depends only on its id. */
function seeded(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * How far the outline may leave the circle, as a fraction of the radius.
 * Small marks get relatively more, or their wobble would be under a pixel and
 * they would read as plain dots; large marks get less, or they would look
 * lumpy. About ±1px at r 8 and ±1.8px at r 22. A radius that is not a
 * number gets the small-mark value, so the answer is always usable as a key.
 */
export function wobbleFor(r: number): number {
  const size = Number.isFinite(r) ? Math.max(r, 1) : 1;
  return Math.max(0.07, Math.min(0.13, 0.055 + 0.6 / size));
}

const profileCache = new Map<string, BlobProfile>();
const PROFILE_CACHE_MAX = 4000;

/**
 * The outline harmonics for one node. `wobble` is the largest fraction of the
 * radius the outline can leave the circle by (`wobbleFor`).
 */
export function blobProfile(nodeId: string, wobble: number): BlobProfile {
  const key = `${nodeId}|${wobble.toFixed(4)}`;
  const hit = profileCache.get(key);
  if (hit) return hit;
  const rand = seeded(hashSeed(`blob:${nodeId}`));
  // Weights fall with frequency: the shape is mostly an oval-ish lean (2θ)
  // with a little three- and four-lobed irregularity on top.
  const w2 = 0.55 + rand() * 0.45;
  const w3 = 0.3 + rand() * 0.45;
  const w4 = 0.12 + rand() * 0.3;
  const k = wobble / (w2 + w3 + w4);
  const profile: BlobProfile = {
    a2: w2 * k,
    p2: rand() * Math.PI * 2,
    a3: w3 * k,
    p3: rand() * Math.PI * 2,
    a4: w4 * k,
    p4: rand() * Math.PI * 2,
  };
  if (profileCache.size >= PROFILE_CACHE_MAX) profileCache.clear();
  profileCache.set(key, profile);
  return profile;
}

/** The outline's radius in direction `theta`, as a multiple of the nominal radius. */
export function rimFactor(p: BlobProfile, theta: number): number {
  return (
    1 +
    p.a2 * Math.sin(2 * theta + p.p2) +
    p.a3 * Math.sin(3 * theta + p.p3) +
    p.a4 * Math.sin(4 * theta + p.p4)
  );
}

/** The outline's radius in direction `theta` for a mark of nominal radius `r`. */
export function rimRadius(p: BlobProfile, r: number, theta: number): number {
  return r * rimFactor(p, theta);
}

const fmt = (v: number) => {
  const s = v.toFixed(2);
  // "12.00" → "12", "-0.00" → "0": shorter markup, identical geometry.
  const t = s.replace(/\.?0+$/, "");
  return t === "-0" || t === "" ? "0" : t;
};

/**
 * The outline as an SVG path: a closed, smooth curve through `SAMPLES` points
 * of the profile (Catmull-Rom, written as cubic Béziers), centred on (cx, cy).
 */
export function blobPath(p: BlobProfile, r: number, cx = 0, cy = 0): string {
  const xs: number[] = new Array(SAMPLES);
  const ys: number[] = new Array(SAMPLES);
  for (let i = 0; i < SAMPLES; i++) {
    const theta = i * STEP;
    const rr = rimRadius(p, r, theta);
    xs[i] = cx + rr * Math.cos(theta);
    ys[i] = cy + rr * Math.sin(theta);
  }
  let d = `M${fmt(xs[0])} ${fmt(ys[0])}`;
  for (let i = 0; i < SAMPLES; i++) {
    const i0 = (i - 1 + SAMPLES) % SAMPLES;
    const i1 = i;
    const i2 = (i + 1) % SAMPLES;
    const i3 = (i + 2) % SAMPLES;
    const c1x = xs[i1] + (xs[i2] - xs[i0]) / 6;
    const c1y = ys[i1] + (ys[i2] - ys[i0]) / 6;
    const c2x = xs[i2] - (xs[i3] - xs[i1]) / 6;
    const c2y = ys[i2] - (ys[i3] - ys[i1]) / 6;
    d += `C${fmt(c1x)} ${fmt(c1y)} ${fmt(c2x)} ${fmt(c2y)} ${fmt(xs[i2])} ${fmt(ys[i2])}`;
  }
  return d + "Z";
}

const pathCache = new Map<string, string>();
const PATH_CACHE_MAX = 6000;

/**
 * `blobPath` for a node about the origin, memoised on (id, radius, wobble).
 * A graph re-renders on every hover and zoom step; the outline of a node that
 * did not change size is reused instead of rebuilt.
 */
export function nodeBlobPath(nodeId: string, r: number, wobble: number): string {
  const key = `${nodeId}|${r.toFixed(2)}|${wobble.toFixed(4)}`;
  const hit = pathCache.get(key);
  if (hit !== undefined) return hit;
  const d = blobPath(blobProfile(nodeId, wobble), r);
  if (pathCache.size >= PATH_CACHE_MAX) pathCache.clear();
  pathCache.set(key, d);
  return d;
}

/**
 * A node's outline centred on (cx, cy), for a mark that cannot be placed with
 * a `transform` attribute: a CSS transform on the same element (the quiz's
 * growth animation) replaces the attribute, so the centre has to be in the
 * path itself. Not memoised: these marks are few and static.
 */
export function nodeBlobPathAt(nodeId: string, r: number, wobble: number, cx: number, cy: number): string {
  return blobPath(blobProfile(nodeId, wobble), r, cx, cy);
}
