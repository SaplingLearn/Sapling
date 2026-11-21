import { describe, expect, it } from "vitest";

import {
  fractionAt, insertTpl, matchClose, nextBox, slotCtx, slotList, slotTex, toTex,
} from "./mathSlots";

describe("matchClose", () => {
  it("finds the matching brace, nested groups included", () => {
    expect(matchClose("{a}", 0)).toBe(2);
    expect(matchClose("{a{b}c}d", 0)).toBe(6);
    expect(matchClose("[n]", 0)).toBe(2);
  });

  it("skips an escaped brace", () => {
    // `\}` is a literal brace in the output, not the end of the group.
    expect(matchClose("{a\\}b}", 0)).toBe(5);
  });

  it("answers -1 when the group never closes", () => {
    expect(matchClose("{abc", 0)).toBe(-1);
  });
});

describe("slotTex", () => {
  it("turns an empty group into a dashed slot, carrying its source position", () => {
    const out = slotTex("\\frac{}{}");
    expect(out).toContain("\\htmlClass{mslot}");
    // `\frac{` is 6 characters, so the first slot's content starts at 6.
    expect(out).toContain("pos=6");
  });

  it("makes a FILLED group clickable too, and recurses into it", () => {
    const out = slotTex("\\frac{a+b}{2}");
    expect(out).toContain("\\htmlClass{mgrp}");
    expect((out.match(/htmlClass\{mgrp\}/g) || []).length).toBe(2);
  });

  it("leaves the body of \\text alone", () => {
    const out = slotTex("\\text{hello}");
    expect(out).toBe("\\text{hello}");
  });

  it("does not split a control sequence", () => {
    expect(slotTex("\\lambda x")).toBe("\\lambda x");
  });

  it("treats a root index as a group", () => {
    expect(slotTex("\\sqrt[]{x}")).toContain("mslot");
  });

  it("offsets nested positions against the whole equation", () => {
    const out = slotTex("\\frac{\\sqrt{}}{2}");
    // `\sqrt`'s empty group opens at index 11, so its content starts at 12 —
    // counted against the whole equation, not against the fragment.
    expect(out).toContain("pos=12");
  });
});

describe("slotList", () => {
  it("lists where each empty slot starts, in source order", () => {
    expect(slotList("\\frac{}{}")).toEqual([6, 8]);
    expect(slotList("x^2")).toEqual([]);
  });
});

describe("slotCtx", () => {
  it("opens an empty group with the caret at its start", () => {
    const raw = "\\frac{}{}";
    expect(slotCtx(raw, 6)).toEqual({ ctx: { start: 6, end: 6, root: false }, caret: 0 });
  });

  it("opens a filled group with the caret at its END, so typing extends it", () => {
    const raw = "\\frac{ab}{2}";
    expect(slotCtx(raw, 6)).toEqual({ ctx: { start: 6, end: 8, root: false }, caret: 2 });
  });

  it("falls back to the whole equation when the position names no group", () => {
    const raw = "x + 1";
    expect(slotCtx(raw, 2).ctx).toEqual({ start: 0, end: raw.length, root: true });
  });
});

describe("nextBox", () => {
  const raw = "\\frac{}{}";

  it("Tab walks from one slot to the next", () => {
    const first = slotCtx(raw, 6);
    const second = nextBox(raw, first.ctx, first.caret);
    expect(second?.ctx.start).toBe(8);
  });

  it("Shift+Tab walks back", () => {
    const second = slotCtx(raw, 8);
    const back = nextBox(raw, second.ctx, second.caret, true);
    expect(back?.ctx.start).toBe(6);
  });

  it("steps out to the root past the trailing empty groups", () => {
    const last = slotCtx(raw, 8);
    const out = nextBox(raw, last.ctx, last.caret);
    expect(out?.ctx.root).toBe(true);
    expect(out?.caret).toBe(raw.length);
  });

  it("has nowhere to go from a root with no slots", () => {
    expect(nextBox("x+1", { start: 0, end: 3, root: true }, 3)).toBeNull();
  });
});

describe("insertTpl", () => {
  const root = (raw: string) => ({ start: 0, end: raw.length, root: true });

  it("inserts at the caret and lands in the template's first slot", () => {
    const out = insertTpl("", root(""), 0, 0, "\\frac{}{}");
    expect(out.raw).toBe("\\frac{}{}");
    expect(out.ctx.start).toBe(6);
  });

  it("puts the caret past a template with no slots", () => {
    const out = insertTpl("x", root("x"), 1, 1, "\\pi ");
    expect(out.raw).toBe("x\\pi ");
    expect(out.caret).toBe(5);
  });

  it("spaces a letter off the control sequence before it", () => {
    const out = insertTpl("\\alpha", root("\\alpha"), 6, 6, "x");
    expect(out.raw).toBe("\\alpha x");
  });

  it("replaces a selection", () => {
    const out = insertTpl("abc", root("abc"), 0, 3, "z");
    expect(out.raw).toBe("z");
  });
});

describe("fractionAt", () => {
  it("takes the term before the slash", () => {
    expect(fractionAt("12", 2)).toEqual({ term: "12", from: 0 });
    expect(fractionAt("x+ab", 4)).toEqual({ term: "ab", from: 2 });
    expect(fractionAt("\\pi", 3)).toEqual({ term: "\\pi", from: 0 });
  });

  it("is null when there is no term, so a bare slash stays a slash", () => {
    expect(fractionAt("x+", 2)).toBeNull();
    expect(fractionAt("", 0)).toBeNull();
  });
});

describe("toTex", () => {
  it("maps typed unicode onto the LaTeX it means", () => {
    // A replacement keeps its trailing space: `\pi x` must not become `\pix`.
    expect(toTex("x² + π")).toBe("x^2 + \\pi ");
    expect(toTex("a ≤ b")).toBe("a \\le  b");
  });
});
