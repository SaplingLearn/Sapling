import { describe, expect, it } from "vitest";
import { distinctTerms, courseInTerm } from "./useActiveSemester";

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

  it("flattens the per-course terms[] so every enrolled term surfaces (#449 fix)", () => {
    // A course collapsed across enrollments carries all its terms; the
    // singular `term` is only the most-recent representative.
    const cs101 = { term: "Spring 2026", terms: ["Fall 2025", "Spring 2026"] };
    const bio110 = { term: "Fall 2025", terms: ["Fall 2025"] };
    expect(distinctTerms([cs101, bio110])).toEqual(["Fall 2025", "Spring 2026"]);
  });
});

describe("courseInTerm", () => {
  const cs101 = { term: "Spring 2026", terms: ["Fall 2025", "Spring 2026"] };

  it("empty activeSemester (All semesters) matches every course", () => {
    expect(courseInTerm(cs101, "")).toBe(true);
  });

  it("matches by term MEMBERSHIP, not just the representative term (regression: #462 review)", () => {
    // The bug: filtering by the singular `term` ("Spring 2026") dropped a
    // Fall-2025-enrolled course from the Fall 2025 tab.
    expect(courseInTerm(cs101, "Fall 2025")).toBe(true);
    expect(courseInTerm(cs101, "Spring 2026")).toBe(true);
    expect(courseInTerm(cs101, "Summer 2026")).toBe(false);
  });

  it("falls back to the singular term for payloads without terms[]", () => {
    expect(courseInTerm({ term: "Fall 2025" }, "Fall 2025")).toBe(true);
    expect(courseInTerm({ term: "Fall 2025" }, "Spring 2026")).toBe(false);
  });
});
