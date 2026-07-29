import { describe, expect, it } from "vitest";
import { distinctTerms } from "./useActiveSemester";

const c = (term: string) => ({ term });

// Note: there is deliberately no default-resolution helper here. The empty
// stored value IS the default and means "All semesters" (unscoped) — scoping
// only starts when the user picks a term in the Courses & Semesters hub
// (see ManageCoursesModal.test.tsx for that behavior).

describe("distinctTerms", () => {
  it("dedups preserving first-seen order and drops blanks", () => {
    expect(distinctTerms([c("Fall 2025"), c("Spring 2026"), c("Fall 2025"), c("")]))
      .toEqual(["Fall 2025", "Spring 2026"]);
  });
});
