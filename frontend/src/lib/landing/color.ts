/**
 * Colour + easing maths for the v4 landing page.
 *
 * Ported verbatim from `Sapling Landing v4.dc.html`. These are the exact
 * functions the scroll engine uses to interpolate node tints, band
 * gradients, and stage transitions frame-by-frame, so the arithmetic is
 * deliberately unchanged — including `lerpTint`'s hue-borrowing rule,
 * which is what stops an unexplored (grey) node from washing through a
 * dead desaturated midpoint on its way to a tier colour.
 *
 * Called from inside the master rAF loop: keep these allocation-light and
 * free of any layout reads.
 */

export type Rgb = [number, number, number];
/** [hue, saturation, lightness], each normalised to 0..1. */
export type Hsl = [number, number, number];

export function hexToRgb(h: string): Rgb {
  return [
    parseInt(h.slice(1, 3), 16),
    parseInt(h.slice(3, 5), 16),
    parseInt(h.slice(5, 7), 16),
  ];
}

export function lerpColor(a: string, b: string, t: number): string {
  const A = hexToRgb(a);
  const B = hexToRgb(b);
  return (
    'rgb(' +
    Math.round(A[0] + (B[0] - A[0]) * t) +
    ',' +
    Math.round(A[1] + (B[1] - A[1]) * t) +
    ',' +
    Math.round(A[2] + (B[2] - A[2]) * t) +
    ')'
  );
}

export function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

export function rgbToHsl(c: Rgb): Hsl {
  const r = c[0] / 255,
    g = c[1] / 255,
    b = c[2] / 255,
    mx = Math.max(r, g, b),
    mn = Math.min(r, g, b),
    l = (mx + mn) / 2;
  let h = 0,
    sa = 0;
  if (mx !== mn) {
    const d = mx - mn;
    sa = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
    h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    h /= 6;
  }
  return [h, sa, l];
}

export function hslToCss(h: number, sa: number, l: number): string {
  return (
    'hsl(' +
    ((((h % 1) + 1) % 1) * 360).toFixed(1) +
    ',' +
    (sa * 100).toFixed(1) +
    '%,' +
    (l * 100).toFixed(1) +
    '%)'
  );
}

/**
 * Tint-aware interpolation: grey has no hue of its own, so borrow the
 * destination's and let saturation carry the change. Also takes the short
 * way round the colour wheel rather than through the far side.
 */
export function lerpTint(a: string, b: string, t: number): string {
  const A = rgbToHsl(hexToRgb(a));
  const B = rgbToHsl(hexToRgb(b));
  const ah = A[1] < 0.08 ? B[0] : A[0];
  let dh = B[0] - ah;
  if (dh > 0.5) dh -= 1;
  else if (dh < -0.5) dh += 1;
  return hslToCss(ah + dh * t, A[1] + (B[1] - A[1]) * t, A[2] + (B[2] - A[2]) * t);
}

/** Smoothstep. The default easing for scroll-driven progress. */
export function smooth(t: number): number {
  t = clamp01(t);
  return t * t * (3 - 2 * t);
}
