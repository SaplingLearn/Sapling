import { describe, expect, it } from "vitest";
import { distinctTerms, resolveActiveSemester } from "./useActiveSemester";

const c = (term: string) => ({ term });

describe("distinctTerms", () => {
  it("dedups preserving first-seen order and drops blanks", () => {
    expect(distinctTerms([c("Fall 2025"), c("Spring 2026"), c("Fall 2025"), c("")]))
      .toEqual(["Fall 2025", "Spring 2026"]);
  });
});

describe("resolveActiveSemester", () => {
  it("keeps the active value when it is among the enrolled terms", () => {
    expect(resolveActiveSemester("Fall 2025", [c("Fall 2025"), c("Spring 2026")]))
      .toBe("Fall 2025");
  });

  it("defaults to the most-recently-enrolled term when active is unset/stale", () => {
    // courses arrive enrolled_at ascending → last is most recent.
    expect(resolveActiveSemester("", [c("Fall 2025"), c("Spring 2026")]))
      .toBe("Spring 2026");
    expect(resolveActiveSemester("Winter 1999", [c("Fall 2025"), c("Spring 2026")]))
      .toBe("Spring 2026");
  });

  it("returns empty string when there are no terms", () => {
    expect(resolveActiveSemester("", [])).toBe("");
  });
});
