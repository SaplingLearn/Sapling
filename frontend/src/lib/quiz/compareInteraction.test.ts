import { describe, it, expect } from "vitest";
import {
  asCompareInteraction,
  decodeCompareAnswer,
  encodeCompareAnswer,
  isCompareComplete,
} from "./compareInteraction";
import type { CompareInteraction } from "./types";

const MITOSIS: CompareInteraction = {
  kind: "compare",
  left: { id: "mitosis", label: "Mitosis" },
  right: { id: "meiosis", label: "Meiosis" },
  options: [
    { id: "left_only", label: "Only the left" },
    { id: "right_only", label: "Only the right" },
    { id: "both", label: "Both" },
    { id: "neither", label: "Neither" },
  ],
};

describe("asCompareInteraction", () => {
  it("accepts two sides and ≥2 options", () => {
    expect(asCompareInteraction(MITOSIS)).toEqual(MITOSIS);
  });

  it("rejects missing kind, duplicate sides, too few options, and unsafe ids", () => {
    expect(asCompareInteraction(undefined)).toBeNull();
    expect(
      asCompareInteraction({
        kind: "compare",
        left: MITOSIS.left,
        right: MITOSIS.left,
        options: MITOSIS.options,
      }),
    ).toBeNull();
    expect(
      asCompareInteraction({
        kind: "compare",
        left: MITOSIS.left,
        right: MITOSIS.right,
        options: [MITOSIS.options[0]],
      }),
    ).toBeNull();
    expect(
      asCompareInteraction({
        kind: "compare",
        left: MITOSIS.left,
        right: MITOSIS.right,
        options: [{ id: "bad=id", label: "Nope" }, { id: "ok", label: "Ok" }],
      }),
    ).toBeNull();
    expect(
      asCompareInteraction({
        kind: "compare",
        left: MITOSIS.left,
        right: MITOSIS.right,
        options: [
          { id: "mitosis", label: "Collides with left" },
          { id: "both", label: "Both" },
        ],
      }),
    ).toBeNull();
  });
});

describe("encode / decode", () => {
  it("round-trips a chosen option", () => {
    expect(encodeCompareAnswer("both")).toBe("both");
    expect(decodeCompareAnswer(MITOSIS, "both")).toBe("both");
    expect(isCompareComplete(MITOSIS, "both")).toBe(true);
  });

  it("starts empty and ignores unknown ids", () => {
    expect(encodeCompareAnswer(null)).toBe("");
    expect(decodeCompareAnswer(MITOSIS, "")).toBeNull();
    expect(decodeCompareAnswer(MITOSIS, "nope")).toBeNull();
    expect(isCompareComplete(MITOSIS, "")).toBe(false);
  });
});
