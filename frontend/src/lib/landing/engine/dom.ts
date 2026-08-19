/**
 * DOM write helpers for the landing engine.
 *
 * Ported from `Sapling Landing v4.dc.html`. Everything here runs inside the
 * frame loop, so the rules are strict: no layout reads, and no DOM write
 * unless the value actually changed.
 */

/** Anything the engine writes styles to. */
type Styled = HTMLElement | SVGElement;

/**
 * Memoised style write. Caches the last value on the element itself under
 * `__p_<prop>` and skips the assignment when nothing changed — an unchanged
 * value never touches the DOM, which is what keeps the per-frame cost flat
 * across the ~200 elements the engine drives.
 *
 * Accepts both camelCase (`pointerEvents`) and dashed (`text-shadow`)
 * property names, matching the source's mixed usage.
 */
export function put(el: Styled | null | undefined, prop: string, val: string): void {
  if (!el) return;
  const k = '__p_' + prop;
  const rec = el as unknown as Record<string, unknown>;
  if (rec[k] === val) return;
  rec[k] = val;
  if (prop.includes('-')) el.style.setProperty(prop, val);
  else (el.style as unknown as Record<string, string>)[prop] = val;
}

export interface CanvasCache {
  ctx: CanvasRenderingContext2D;
  /** CSS pixels, not device pixels. */
  w: number;
  h: number;
  dpr: number;
}

/**
 * Cached 2D context + size for a canvas, keyed on the element.
 *
 * The size is read once and reused; `invalidateCanvas` drops the cache when
 * the viewport changes (called from the measure pass, never per frame). DPR
 * is capped at 1.5 — above that the fill rate cost outweighs the sharpness
 * on these mostly-soft renders.
 *
 * Re-applies the DPR transform on every call, so callers draw in CSS pixels.
 */
export function cv(canvas: HTMLCanvasElement): CanvasCache {
  const rec = canvas as unknown as Record<string, unknown>;
  let c = rec.__cv as CanvasCache | null | undefined;
  if (!c) {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    let ctx = rec.__ctx as CanvasRenderingContext2D | undefined;
    if (!ctx) {
      ctx = canvas.getContext('2d') as CanvasRenderingContext2D;
      rec.__ctx = ctx;
    }
    c = { ctx, w, h, dpr };
    rec.__cv = c;
    const pw = Math.round(w * dpr);
    const ph = Math.round(h * dpr);
    // Assigning width/height clears the canvas, so only do it when it moved.
    if (canvas.width !== pw || canvas.height !== ph) {
      canvas.width = pw;
      canvas.height = ph;
    }
  }
  c.ctx.setTransform(c.dpr, 0, 0, c.dpr, 0, 0);
  return c;
}

/** Drop a canvas's cached size so the next `cv()` re-reads it. */
export function invalidateCanvas(canvas: HTMLCanvasElement | null | undefined): void {
  if (canvas) (canvas as unknown as Record<string, unknown>).__cv = null;
}

/**
 * Scroll progress through a section that is taller than the viewport, as
 * 0..1 over the distance its sticky child stays pinned.
 *
 * @param lag Shifts the zero point, for stages that should start late.
 */
export function sectionProgress(el: Element, vh: number, lag?: number): number {
  const r = el.getBoundingClientRect();
  const total = r.height - vh;
  if (total <= 0) return 0;
  const v = -(r.top + (lag || 0)) / total;
  return Math.max(0, Math.min(1, v));
}
