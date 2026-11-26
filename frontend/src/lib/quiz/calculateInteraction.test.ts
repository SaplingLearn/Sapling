import { describe, it, expect } from "vitest";
import {
  asCalculateInteraction,
  decodeCalculateAnswer,
  encodeCalculateAnswer,
  isCalculateComplete,
} from "./calculateInteraction";

describe("asCalculateInteraction", () => {
  it("accepts kind-only and optional placeholders", () => {
    expect(asCalculateInteraction({ kind: "calculate" })).toEqual({ kind: "calculate" });
    expect(
      asCalculateInteraction({
        kind: "calculate",
        placeholder: "Your answer",
        unitLabel: "m/s",
      }),
    ).toEqual({
      kind: "calculate",
      placeholder: "Your answer",
      unitLabel: "m/s",
    });
  });

  it("rejects other kinds", () => {
    expect(asCalculateInteraction(undefined)).toBeNull();
  });
});

describe("encode / complete", () => {
  it("requires both value and unit", () => {
    expect(encodeCalculateAnswer("12", "m/s")).toBe("12|m/s");
    // W7.2: the encoding's third part is the optional working ("steps").
    expect(decodeCalculateAnswer("12|m/s")).toEqual({ value: "12", unit: "m/s", steps: "" });
    expect(isCalculateComplete("12|m/s")).toBe(true);
    expect(isCalculateComplete("12|")).toBe(false);
    expect(isCalculateComplete("12")).toBe(false);
  });
});
