/**
 * Style rules a DOM test cannot see, pinned in the stylesheets themselves:
 * what the printout keeps, what follows the sticky top bar, where a long
 * word may break, and the smallest target a finger gets.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const sheet = (file: string) => fs.readFileSync(path.resolve(__dirname, file), "utf8");
const READER = sheet("reader/reader.module.css");
const RAIL = sheet("reader/rail/rail.module.css");
const BLOCKS = sheet("reader/blocks/blocks.module.css");
const HOME = sheet("home/home.module.css");
const NEW_GUIDE = sheet("home/newGuide.module.css");

/** The declarations of the first rule whose selector is exactly `selector`. */
function rule(css: string, selector: string): string {
  const at = css.split("\n").findIndex(line => line.startsWith(`${selector} {`));
  if (at < 0) throw new Error(`no rule for ${selector}`);
  const rest = css.split("\n").slice(at).join("\n");
  return rest.slice(rest.indexOf("{") + 1, rest.indexOf("}"));
}

/** Everything inside the sheet's `@media print` block. */
const printed = (css: string) => css.slice(css.indexOf("@media print"));

describe("the printed guide", () => {
  it("keeps its background colours: the space bar, tier swatches, key terms and block tints", () => {
    expect(printed(READER)).toMatch(/\.page \{[^}]*-webkit-print-color-adjust: exact;[^}]*print-color-adjust: exact;/);
  });

  it("opens a collapsed section and shows every step of a worked example", () => {
    expect(printed(READER)).toContain(".sectionBody[hidden] { display: flex !important; }");
    expect(printed(BLOCKS)).toContain(".step[hidden] { display: flex !important; }");
  });
});

describe("what sits under the sticky top bar", () => {
  it("is placed from the bar's measured height, not a fixed guess", () => {
    expect(rule(READER, ".banner")).toContain("top: calc(var(--guide-bar, 80px) + 4px)");
    expect(rule(READER, ".section")).toContain("scroll-margin-top: calc(var(--guide-bar, 80px) + 10px)");
    expect(rule(READER, ".sources")).toContain("scroll-margin-top: calc(var(--guide-bar, 80px) + 10px)");
    expect(rule(RAIL, ".rail")).toContain("top: calc(var(--guide-bar, 80px) + 16px)");
  });
});

describe("a long word with no spaces", () => {
  it("breaks inside the guide title, a section heading, a check question and a card title", () => {
    expect(rule(READER, ".header .title")).toContain("overflow-wrap: anywhere");
    expect(rule(READER, ".sectionTitle h3")).toContain("overflow-wrap: anywhere");
    expect(rule(BLOCKS, ".question")).toContain("overflow-wrap: anywhere");
    expect(rule(HOME, ".card .title")).toContain("overflow-wrap: anywhere");
  });
});

describe("the materials' quick picks", () => {
  it("are at least 32px tall", () => {
    expect(rule(NEW_GUIDE, ".pick")).toContain("min-height: 32px");
  });
});
