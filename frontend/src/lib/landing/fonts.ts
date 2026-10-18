/**
 * The landing's four font stacks, in one place.
 *
 * Every family is loaded by `next/font/local` (see `app/layout.tsx`), which
 * assigns each one a generated family name and publishes it as a CSS variable.
 * That generated name is NOT the human name: a `const playfairDisplay` becomes
 * the family `playfairDisplay`, so a stack written as `'Playfair Display',
 * serif` matches nothing and silently renders Times. It looks almost right —
 * the metric-adjusted fallback sees to that — which is exactly why it went
 * unnoticed across 23 files.
 *
 * So the variable comes first and the human name second, as a fallback for the
 * rare visitor who has the font installed locally. Never write a bare family
 * name in a style; use these.
 */

export const FONT_DISPLAY = "var(--font-spectral), 'Spectral', Georgia, serif";
export const FONT_SERIF = "var(--font-playfair), 'Playfair Display', Georgia, serif";
export const FONT_SANS = "var(--font-dm-sans), 'DM Sans', system-ui, sans-serif";
export const FONT_MONO = "var(--font-jetbrains), 'JetBrains Mono', ui-monospace, monospace";

type FontKind = 'display' | 'serif' | 'sans' | 'mono';

const CSS_VAR: Record<FontKind, string> = {
  display: '--font-spectral',
  serif: '--font-playfair',
  sans: '--font-dm-sans',
  mono: '--font-jetbrains',
};

const BARE: Record<FontKind, string> = {
  display: "'Spectral', Georgia, serif",
  serif: "'Playfair Display', Georgia, serif",
  sans: "'DM Sans', system-ui, sans-serif",
  mono: "'JetBrains Mono', ui-monospace, monospace",
};

const resolved: Partial<Record<FontKind, string>> = {};

/**
 * The same stack, but for `ctx.font`.
 *
 * A canvas font string is parsed by the CSS font shorthand grammar, which has
 * no `var()` — the whole assignment is dropped and the canvas keeps whatever
 * it had, usually 10px sans-serif. So resolve the variable to its real family
 * name first and hand canvas that.
 *
 * Cached per kind: this runs per frame on the graph and plant canvases, and
 * `getComputedStyle` is a layout read. Only a non-empty result is cached, so a
 * call that somehow lands before the variables exist doesn't poison it.
 */
export function canvasFont(kind: FontKind): string {
  const hit = resolved[kind];
  if (hit) return hit;
  if (typeof document === 'undefined') return BARE[kind];
  const v = getComputedStyle(document.documentElement).getPropertyValue(CSS_VAR[kind]).trim();
  if (!v) return BARE[kind];
  const stack = v + ', ' + BARE[kind];
  resolved[kind] = stack;
  return stack;
}
