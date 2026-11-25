/**
 * Journey — the Library redesign matches its design handoff in a REAL browser,
 * not just in jsdom.
 *
 * `src/components/library/designParity.test.tsx` and `designCoverage.test.tsx`
 * already prove that every declaration in the prototype reached the code
 * and that none was dropped. They cannot prove three things, because jsdom has
 * no CSS cascade and no layout engine:
 *
 *   1. that a value landed on the RIGHT element (a unit test that finds
 *      `padding: 0 14px` somewhere in the source is satisfied by it being on
 *      the wrong button),
 *   2. that `app/library-notes.css` actually applies — it is reached through
 *      an `@import` in globals.css, and a scoping or specificity mistake would
 *      be invisible to a test that never loads a stylesheet,
 *   3. that the hover states work at all. The handoff expresses them as
 *      `style-hover="…"` attributes, which the rebuild re-expresses as
 *      `.sapHover*` classes; nothing in the unit lane ever hovers.
 *
 * This spec reads the handoff fixture itself — the same file the unit tests
 * read — and asserts the browser's own `getComputedStyle` against it.
 *
 * What it deliberately does NOT do: diff a screenshot against the prototype.
 * The prototype paints mock content (its own document names) into a fixed
 * 1920x1080 artboard with its own sidebar, while the app paints seeded data
 * inside the repo's shell and the real SideNav. Such a diff
 * would be almost entirely content noise and would fail for reasons that have
 * nothing to do with design fidelity, so it would be a test nobody trusts.
 * Computed style is the strongest claim that is also a true one.
 *
 * Selectors: the `library-*` testids (docs/frontend-testids.md).
 * Data: the rich seed's `linear-algebra-notes.pdf` (db/seed_local_rich.py).
 */
import fs from "node:fs";
import path from "node:path";

import { expect, test } from "./support/fixtures";

const SRC = path.join(__dirname, "..", "src");
const LIBRARY_DESIGN = fs.readFileSync(
  path.join(SRC, "components/library/__fixtures__/library-v2.design.html"), "utf8");
const PORTED_CSS = fs.readFileSync(path.join(SRC, "app/library-notes.css"), "utf8");

/**
 * One spelling per colour, the one the CSSOM uses: `#F2F6EE` becomes
 * `rgb(242, 246, 238)`, and `rgba(255,255,255,0.12)` gains the spaces the
 * browser puts after each comma. Without that last step an rgba() hover value
 * compares unequal to its own rule.
 */
function rgb(value: string): string {
  const hex = value.trim().match(/^#([0-9a-f]{6})$/i);
  if (hex) {
    const n = parseInt(hex[1], 16);
    return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
  }
  return value.trim().replace(/\s+/g, "").replace(/,/g, ", ");
}

/**
 * Every `.sapHoverX` rule, as the class name and the declarations it sets.
 * These are the rebuild's translation of the handoff's `style-hover=`.
 */
function hoverRules(): Array<{ cls: string; decls: Array<[string, string]> }> {
  const out: Array<{ cls: string; decls: Array<[string, string]> }> = [];
  for (const m of PORTED_CSS.matchAll(/\.(sapHover\w*):hover\s*\{([^}]*)\}/g)) {
    const decls: Array<[string, string]> = [];
    for (const part of m[2].split(";")) {
      const i = part.indexOf(":");
      if (i < 0) continue;
      decls.push([part.slice(0, i).trim(), part.slice(i + 1).replace("!important", "").trim()]);
    }
    if (decls.length) out.push({ cls: m[1], decls });
  }
  return out;
}

/** The literal hover declarations the handoff asks for, as "prop:value". */
function designHovers(design: string): Set<string> {
  const out = new Set<string>();
  for (const m of design.matchAll(/style-hover="([^"]*)"/g)) {
    for (const part of m[1].split(";")) {
      const i = part.indexOf(":");
      if (i < 0) continue;
      const value = part.slice(i + 1).trim();
      if (value.includes("{{")) continue; // computed per row, no literal
      out.add(`${part.slice(0, i).trim()}:${value}`);
    }
  }
  return out;
}

test.describe("the Library matches the design handoff in a browser", () => {
  test("the ported stylesheet is actually live on the Library", async ({ page }) => {
    await page.goto("/library");
    await expect(page.getByTestId("library-search")).toBeVisible({ timeout: 30_000 });

    // `library-notes.css` scopes its resets to `[data-sap-surface]`. If the
    // @import never resolved, or the scope attribute was dropped, the surface
    // is unstyled and everything below this is meaningless — so assert the
    // stylesheet reached the document before asserting anything it declares.
    const ported = await page.evaluate(() =>
      [...document.styleSheets].some(sheet => {
        try {
          return [...(sheet.cssRules ?? [])].some(r => r.cssText.includes("sapHoverMenu"));
        } catch {
          return false; // cross-origin sheet; not ours
        }
      }));
    expect(ported, "library-notes.css is loaded in the page").toBe(true);

    await expect(page.locator("[data-sap-surface]").first()).toBeVisible();
  });

  test("every hover state the handoff declares is live in the browser", async ({ page }) => {
    await page.goto("/library");
    await expect(page.getByTestId("library-search")).toBeVisible({ timeout: 30_000 });

    // 1. The rebuild must not invent hover colours: every literal the handoff
    //    declares has to exist as a `.sapHover*` rule in the source.
    const declared = new Set(
      hoverRules().flatMap(r => r.decls.map(([p, v]) => `${p}:${v}`)));
    const wanted = designHovers(LIBRARY_DESIGN);
    expect(
      [...wanted].filter(w => !declared.has(w)),
      "handoff hover declarations with no .sapHover* rule",
    ).toEqual([]);

    // 2. Those rules have to have SURVIVED into the live stylesheet with the
    //    same values. Reading the CSSOM rather than hovering every element
    //    keeps this off the flaky path: a class whose only instance happens to
    //    be scrolled out or covered would otherwise fail for no design reason.
    const live = await page.evaluate(() => {
      const out: Record<string, string> = {};
      for (const sheet of [...document.styleSheets]) {
        let rules: CSSRule[];
        try { rules = [...(sheet.cssRules ?? [])]; } catch { continue; }
        for (const rule of rules) {
          const text = rule.cssText;
          const m = /\.(sapHover\w*):hover/.exec(text);
          if (m) out[m[1]] = text;
        }
      }
      return out;
    });
    for (const { cls, decls } of hoverRules()) {
      const text = live[cls];
      expect(text, `.${cls}:hover reached the browser`).toBeTruthy();
      for (const [prop, value] of decls) {
        // The CSSOM normalises colours to rgb() and keeps !important.
        expect(text, `.${cls}:hover still sets ${prop}`).toContain(prop);
        expect(
          text.replace(/\s+/g, " "),
          `.${cls}:hover still sets ${prop}: ${value}`,
        ).toContain(rgb(value));
      }
    }

    // 3. And a hover has to actually repaint. One element is enough to prove
    //    the mechanism; the rest is the CSSOM assertion above. The row's
    //    "Details and actions" button is the `.sapHoverStone` instance that is
    //    always on screen — `library-doc-menu` is the dialog it opens, not a
    //    hover target.
    const menuButton = page.getByRole("button", { name: "Details and actions" }).first();
    await expect(menuButton).toBeVisible();
    await menuButton.hover();
    await expect(menuButton, "the row's menu button repaints on hover")
      .toHaveCSS("background-color", rgb("#E4DFD3"));
  });
});
