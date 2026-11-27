import { describe, it, expect } from "vitest";
import { skillChipLabel } from "./skillChip";

describe("skillChipLabel", () => {
  it("prefers kit kind", () => {
    expect(skillChipLabel({ type: "short_answer", interactionKind: "sort" })).toBe("Create");
    expect(skillChipLabel({ type: "short_answer", interactionKind: "compare" })).toBe("Analyze");
    expect(skillChipLabel({ type: "short_answer", interactionKind: "calculate" })).toBe("Apply");
  });

  it("maps core types", () => {
    expect(skillChipLabel({ type: "multiple_choice", difficulty: "easy" })).toBe("Remember");
    expect(skillChipLabel({ type: "multiple_choice", difficulty: "hard" })).toBe("Understand");
    expect(skillChipLabel({ type: "numeric" })).toBe("Apply");
  });
});
