/**
 * Which projected nodes the landing hero canvas draws a link between (#111).
 *
 * The rule: for an ordered pair i < j, link them when their 2D distance is
 * under `reach * points[i].sc`. The threshold comes from the FIRST point's
 * scale, so the relation is not symmetric and the ordering matters.
 *
 * This ran as an uncapped double loop on every frame — ~25k distance checks
 * for 226 nodes, to draw the few dozen pairs that actually qualify. Since a
 * point can only reach `reach * sc` pixels, binning into a grid whose cell is
 * the largest such radius means every possible partner lies in the 3x3 block
 * around it, and nothing else is ever measured.
 *
 * Extracted from the canvas so the fast version can be proved equivalent to
 * the obvious one (see linkPairs.test.ts) rather than merely believed to be.
 */
export type ProjectedPoint = { x: number; y: number; sc: number };
export type LinkPair = { i: number; j: number; d: number };

/**
 * The obvious all-pairs implementation. Kept as the executable definition of
 * correctness for the binned version below — not used to render.
 */
export function linkPairsNaive(points: ProjectedPoint[], reach: number): LinkPair[] {
  const out: LinkPair[] = [];
  for (let i = 0; i < points.length; i++) {
    const p1 = points[i];
    const threshold = reach * p1.sc;
    for (let j = i + 1; j < points.length; j++) {
      const p2 = points[j];
      const d = Math.hypot(p1.x - p2.x, p1.y - p2.y);
      if (d < threshold) out.push({ i, j, d });
    }
  }
  return out;
}

/**
 * Spatially binned equivalent. Emits pairs in the same order as
 * `linkPairsNaive` — ascending i, then ascending j — which matters because
 * the caller strokes translucent overlapping lines, and draw order decides
 * the composited result.
 */
export function linkPairs(points: ProjectedPoint[], reach: number): LinkPair[] {
  const out: LinkPair[] = [];
  if (points.length === 0) return out;

  let maxR = 0;
  for (const p of points) {
    const r = reach * p.sc;
    if (r > maxR) maxR = r;
  }
  // A non-positive reach links nothing; guard before it becomes a zero cell.
  if (maxR <= 0) return out;
  const cell = maxR;

  // Grid coords stay far inside +/-1024 for any plausible viewport, so they
  // pack into a single integer key with no collisions.
  const key = (gx: number, gy: number) => ((gx + 1024) << 12) | (gy + 1024);

  const grid = new Map<number, number[]>();
  for (let i = 0; i < points.length; i++) {
    const k = key(Math.floor(points[i].x / cell), Math.floor(points[i].y / cell));
    const bucket = grid.get(k);
    if (bucket) bucket.push(i);
    else grid.set(k, [i]);
  }

  const candidates: number[] = [];
  for (let i = 0; i < points.length; i++) {
    const p1 = points[i];
    const threshold = reach * p1.sc;
    const gx = Math.floor(p1.x / cell);
    const gy = Math.floor(p1.y / cell);

    candidates.length = 0;
    for (let ox = -1; ox <= 1; ox++) {
      for (let oy = -1; oy <= 1; oy++) {
        const bucket = grid.get(key(gx + ox, gy + oy));
        if (!bucket) continue;
        for (const j of bucket) if (j > i) candidates.push(j);
      }
    }
    candidates.sort((a, b) => a - b);

    for (const j of candidates) {
      const p2 = points[j];
      const d = Math.hypot(p1.x - p2.x, p1.y - p2.y);
      if (d < threshold) out.push({ i, j, d });
    }
  }
  return out;
}
