/**
 * Token contract for the redesign foundation (prompt 01): the approved
 * values are present, the legacy remap is scoped, graph colours are left
 * alone, and no clay/peach/red decorative surface is introduced.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(path.join(__dirname, "sapling.css"), "utf8");
const block = (selector: string) => {
  const start = css.indexOf(`${selector} {`);
  return css.slice(start, css.indexOf("\n}", start));
};

describe("sapling.css tokens", () => {
  it("declares the approved palette exactly", () => {
    const root = block(":root");
    for (const [name, hex] of Object.entries({
      paper: "#F7F4E9", "chat-surface": "#EEEFE3", sage: "#E5EBDD", ink: "#253D2F",
      primary: "#416207", muted: "#626B5A", line: "#D6D8C7", white: "#FFFFFF",
      lavender: "#E9E4F2", plum: "#675574",
    })) {
      expect(root).toContain(`--sapling-${name}: ${hex};`);
    }
    expect(root).toContain("--sapling-control-min: 44px;");
  });

  it("declares ONE type scale, and the redesigned surfaces size text only through it", () => {
    const root = block(":root");
    for (const role of ["page", "section", "card", "item", "body", "meta", "eyebrow", "control"]) {
      expect(root).toMatch(new RegExp(`--sapling-text-${role}: `));
      expect(root).toMatch(new RegExp(`--sapling-leading-${role}: `));
    }
    // No literal px font sizes left in the redesigned surfaces' modules
    // (icon glyphs and code are not text roles and say so in place).
    const modules = [
      "../dashboard/Dashboard.module.css",
      "../screens/Library.module.css",
      "../DocumentUploadModal.module.css",
      "../learn/TutorView.module.css",
    ];
    for (const m of modules) {
      const text = readFileSync(path.join(__dirname, m), "utf8");
      expect(text, m).not.toMatch(/font-size:\s*[\d.]+px|font:\s*\d{3}\s+[\d.]+px/);
    }
  });

  it("uses the packaged faces for headings, body and code", () => {
    const root = block(":root");
    expect(root).toMatch(/--sapling-font-heading: var\(--font-aleo\)/);
    expect(root).toMatch(/--sapling-font-body: var\(--font-suse\)/);
    expect(root).toMatch(/--sapling-font-code: var\(--font-plex-mono\)/);
  });

  it("remaps legacy role tokens only inside .sapling-surface, never on :root", () => {
    expect(block(":root")).not.toMatch(/\n\s*--(bg|text|accent|border|fa26-[a-z]+|font-sans|font-display):/);
    expect(block(".sapling-surface")).toMatch(/--bg: var\(--sapling-paper\)/);
    expect(block(".sapling-surface")).toMatch(/--fa26-tan: var\(--sapling-chat-surface\)/);
  });

  it("leaves the knowledge-graph state colours alone", () => {
    expect(css).not.toMatch(/--state-[a-z]+\s*:/);
  });

  it("introduces no clay, peach or red hex values", () => {
    const hexes = [...css.matchAll(/#[0-9a-fA-F]{6}\b/g)].map((m) => m[0].toUpperCase());
    for (const hex of hexes) {
      const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
      // Warm, red-dominant colours (clay / salmon / peach / red) are not approved.
      expect(r > g + 24 && r > b + 24, `${hex} is a warm red/clay tone`).toBe(false);
    }
  });
});
