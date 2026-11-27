import { describe, it, expect } from "vitest";
import {
  asHighlightInteraction,
  decodeHighlightAnswer,
  encodeHighlightAnswer,
  isHighlightComplete,
  toggleHighlightPassage,
} from "./highlightInteraction";
import type { HighlightInteraction } from "./types";

const POEM: HighlightInteraction = {
  kind: "highlight",
  note: "Select the lines that claim immortality.",
  minSelected: 1,
  passages: [
    { id: "l0", label: "But thy eternal summer shall not fade," },
    { id: "l4", label: "So long as men can breathe or eyes can see," },
    { id: "l5", label: "So long lives this, and this gives life to thee." },
  ],
};

describe("asHighlightInteraction", () => {
  it("accepts ≥2 passages", () => {
    expect(asHighlightInteraction(POEM)).toEqual(POEM);
  });

  it("rejects too few passages and unsafe ids", () => {
    expect(asHighlightInteraction(undefined)).toBeNull();
    expect(
      asHighlightInteraction({
        kind: "highlight",
        passages: [{ id: "only", label: "One" }],
      }),
    ).toBeNull();
    expect(
      asHighlightInteraction({
        kind: "highlight",
        passages: [
          { id: "bad,id", label: "Nope" },
          { id: "ok", label: "Ok" },
        ],
      }),
    ).toBeNull();
  });
});

describe("encode / toggle / complete", () => {
  it("round-trips a sorted selection", () => {
    const encoded = encodeHighlightAnswer(["l5", "l4"]);
    expect(encoded).toBe("l4,l5");
    expect(decodeHighlightAnswer(POEM, encoded)).toEqual(["l4", "l5"]);
    expect(isHighlightComplete(POEM, encoded)).toBe(true);
    expect(isHighlightComplete(POEM, "")).toBe(false);
  });

  it("toggles passages in and out", () => {
    expect(toggleHighlightPassage([], "l4")).toEqual(["l4"]);
    expect(toggleHighlightPassage(["l4"], "l4")).toEqual([]);
    expect(toggleHighlightPassage(["l4"], "l5")).toEqual(["l4", "l5"]);
  });
});
