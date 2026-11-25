/**
 * Reading the design handoff's own markup, so a test can check the rebuild
 * against it rather than against a number somebody typed twice.
 *
 * The `.dc.html` prototypes are inline-styled with literal values. These
 * helpers pull those literals back out — every declaration in the file, the
 * copy it shows, the icon path data, the keyframe names it animates with —
 * which is what `designParity.test.tsx` asserts the rebuilt components carry.
 */

/** One `style="…"` declaration: `padding: 0 14px` → `["padding", "0 14px"]`. */
export type Declaration = [property: string, value: string];

/** Normalise whitespace so `0  14px` and `0 14px` compare equal. */
const tidy = (s: string) => s.trim().replace(/\s+/g, " ");

/** Every `style="…"` attribute in the file, as declaration pairs. */
export function declarations(html: string): Declaration[] {
  const out: Declaration[] = [];
  for (const m of html.matchAll(/\sstyle="([^"]*)"/g)) {
    for (const part of m[1].split(";")) {
      const i = part.indexOf(":");
      if (i < 0) continue;
      const property = tidy(part.slice(0, i));
      const value = tidy(part.slice(i + 1));
      if (property && value) out.push([property, value]);
    }
  }
  return out;
}

/**
 * The distinct values the design uses for one property, with its `{{ … }}`
 * placeholders dropped — those are computed per row and have no literal.
 */
export function valuesFor(html: string, property: string): Set<string> {
  const out = new Set<string>();
  for (const [p, v] of declarations(html)) {
    if (p !== property) continue;
    if (v.includes("{{")) continue;
    out.add(v);
  }
  return out;
}

/**
 * One spelling per colour, so the design's literal and what React serialises
 * compare equal: hex uppercased, `rgba()` whitespace dropped, and a trailing
 * zero trimmed off the alpha (the design writes `0.10`, React writes `0.1`).
 */
export function normalizeColor(c: string): string {
  if (c.startsWith("#")) return c.toUpperCase();
  return c
    .replace(/\s+/g, "")
    .replace(/(\.[0-9]*?)0+\)/, "$1)")
    .replace(/\.\)/, ")");
}

/** Every colour literal the design names, in that one spelling. */
export function colors(html: string): Set<string> {
  const out = new Set<string>();
  for (const m of html.matchAll(/#[0-9A-Fa-f]{6}\b/g)) out.add(normalizeColor(m[0]));
  for (const m of html.matchAll(/rgba\([^)]*\)/gi)) out.add(normalizeColor(m[0]));
  return out;
}

/** Every `@keyframes` name the design declares. */
export function keyframeNames(html: string): Set<string> {
  return new Set([...html.matchAll(/@keyframes\s+([A-Za-z][\w-]*)/g)].map(m => m[1]));
}

/** Every animation shorthand the design applies, placeholders dropped. */
export function animations(html: string): Set<string> {
  return valuesFor(html, "animation");
}

/** The `d=` path data of every inline `<path>`, so icons can be compared. */
export function paths(html: string): Set<string> {
  const out = new Set<string>();
  for (const m of html.matchAll(/\sd="([^"]+)"/g)) {
    if (!m[1].includes("{{")) out.add(tidy(m[1]));
  }
  return out;
}

/**
 * The literal text the design shows: what is between tags, with the
 * `{{ … }}` holes and the whitespace-only runs removed.
 */
export function copy(html: string): Set<string> {
  const body = html
    // The `<script>` blocks are logic, not copy.
    .replace(/<script[\s\S]*?<\/script>/g, "")
    .replace(/<style[\s\S]*?<\/style>/g, "");
  const out = new Set<string>();
  for (const m of body.matchAll(/>([^<>]+)</g)) {
    const text = tidy(m[1].replace(/\{\{[^}]*\}\}/g, ""));
    if (text && /[A-Za-z]/.test(text)) out.add(text);
  }
  return out;
}

/**
 * Does the design declare this exact string anywhere?
 *
 * Not every label is markup: the prototype keeps its type names, sort names
 * and menu labels in the data tables at the bottom of the file (`TYPES`,
 * `SORTS`, …) and renders them through a `{{ … }}` hole. Those are still the
 * design's copy, so a parity check looks at the whole file.
 */
export function declares(html: string, text: string): boolean {
  return html.includes(text);
}

/** Collect the inline styles React rendered, the same shape as `declarations`. */
export function renderedDeclarations(root: HTMLElement): Declaration[] {
  const out: Declaration[] = [];
  const walk = (el: Element) => {
    const style = el.getAttribute("style");
    if (style) {
      for (const part of style.split(";")) {
        const i = part.indexOf(":");
        if (i < 0) continue;
        const property = tidy(part.slice(0, i));
        const value = tidy(part.slice(i + 1));
        if (property && value) out.push([property, value]);
      }
    }
    for (const child of el.children) walk(child);
  };
  walk(root);
  return out;
}

/** The distinct rendered values for one property. */
export function renderedValuesFor(root: HTMLElement, property: string): Set<string> {
  return new Set(
    renderedDeclarations(root).filter(([p]) => p === property).map(([, v]) => v),
  );
}

/** Every colour the rendered DOM uses, in the same one spelling. */
export function renderedColors(root: HTMLElement): Set<string> {
  const out = new Set<string>();
  const seen = `${root.innerHTML}`;
  for (const m of seen.matchAll(/#[0-9A-Fa-f]{6}\b/g)) out.add(normalizeColor(m[0]));
  for (const m of seen.matchAll(/rgba\([^)]*\)/gi)) out.add(normalizeColor(m[0]));
  return out;
}

/** The path data the rendered DOM carries. */
export function renderedPaths(root: HTMLElement): Set<string> {
  return new Set(
    [...root.querySelectorAll("path")]
      .map(p => tidy(p.getAttribute("d") || ""))
      .filter(Boolean),
  );
}

/** The animation shorthands the rendered DOM applies. */
export function renderedAnimations(root: HTMLElement): Set<string> {
  return renderedValuesFor(root, "animation");
}

/** The keyframe names referenced by an animation shorthand. */
export function keyframesUsed(animationValues: Iterable<string>): Set<string> {
  const out = new Set<string>();
  for (const v of animationValues) {
    const name = v.trim().split(/\s+/)[0];
    if (name && name !== "none" && /^[A-Za-z]/.test(name)) out.add(name);
  }
  return out;
}
