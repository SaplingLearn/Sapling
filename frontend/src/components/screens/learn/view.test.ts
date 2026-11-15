import { describe, it, expect } from "vitest";
import { focusCardDescription, focusCardTitle, sessionSubtitle } from "./view";
import type { EnrolledCourse } from "@/lib/api";
import type { GraphNode } from "@/lib/data";

const concept = (extra: Partial<GraphNode> = {}): GraphNode => ({
  id: "n1", name: "Recursion", subject: "Intro CS", color: "#000",
  mastery_tier: "learning", mastery_score: 0.5, course_id: "c1", ...extra,
});
const course = (extra: Partial<EnrolledCourse> = {}) =>
  ({ course_id: "c1", course_code: "CS101", course_name: "Intro CS", ...extra }) as EnrolledCourse;

describe("sessionSubtitle", () => {
  it("prefixes the course code when there is one", () => {
    expect(sessionSubtitle("CS101", "Socratic", 4)).toBe("CS101 · Socratic Tutor · 4 Messages");
  });
  it("drops the prefix for a missing or empty code", () => {
    expect(sessionSubtitle(undefined, "Teach-back", 0)).toBe("Teach-back Tutor · 0 Messages");
    expect(sessionSubtitle("", "Expository", 1)).toBe("Expository Tutor · 1 Messages");
  });
});

describe("focusCardTitle", () => {
  it("names the focused concept first", () => {
    expect(focusCardTitle(concept(), course(), "Topic")).toBe("Recursion");
  });
  it("falls back to the course name, then the topic", () => {
    expect(focusCardTitle(null, course(), "Topic")).toBe("Intro CS");
    expect(focusCardTitle(null, null, "Topic")).toBe("Topic");
  });
  it("keeps an empty course name rather than falling through to the topic", () => {
    expect(focusCardTitle(null, course({ course_name: "" }), "Topic")).toBe("");
  });
});

describe("focusCardDescription", () => {
  it("prefers the stored description, even an empty one", () => {
    expect(focusCardDescription(concept({ description: "Self-reference." }), { n1: "cached" }, 2, 9)).toBe("Self-reference.");
    expect(focusCardDescription(concept({ description: "" }), { n1: "cached" }, 2, 9)).toBe("");
  });
  it("then the fetched blurb for that node", () => {
    expect(focusCardDescription(concept(), { n1: "cached", n2: "other" }, 2, 9)).toBe("cached");
  });
  it("then the connected-concepts sentence", () => {
    expect(focusCardDescription(concept(), { n2: "other" }, 3, 9)).toBe(
      "3 connected concepts · this is where your session is anchored on the course map.",
    );
  });
  it("counts the course's concepts for a course-anchored card", () => {
    expect(focusCardDescription(null, { n1: "cached" }, 3, 9)).toBe(
      "9 concepts in this course · pick one to anchor your session.",
    );
  });
});
