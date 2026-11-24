import { describe, it, expect } from "vitest";
import {
  asExplainInteraction,
  decodeExplainAnswer,
  encodeExplainAnswer,
  isExplainComplete,
} from "./explainInteraction";

describe("asExplainInteraction", () => {
  it("accepts kind-only and cleans optional fields", () => {
    expect(asExplainInteraction({ kind: "explain" })).toEqual({ kind: "explain" });
    expect(
      asExplainInteraction({
        kind: "explain",
        placeholder: "  Type your explanation  ",
        rubric: ["First criterion", "", "First criterion", "Second"],
      }),
    ).toEqual({
      kind: "explain",
      placeholder: "Type your explanation",
      rubric: ["First criterion", "Second"],
    });
  });

  it("rejects other kinds", () => {
    expect(asExplainInteraction(undefined)).toBeNull();
    expect(asExplainInteraction({ kind: "compare" } as never)).toBeNull();
  });
});

describe("encode / complete", () => {
  it("treats trimmed prose as the answer", () => {
    expect(encodeExplainAnswer("  hello  ")).toBe("hello");
    expect(decodeExplainAnswer("hello")).toBe("hello");
    expect(isExplainComplete("")).toBe(false);
    expect(isExplainComplete("  x  ")).toBe(true);
  });
});
