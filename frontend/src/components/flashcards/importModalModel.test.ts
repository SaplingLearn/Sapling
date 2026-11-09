import { describe, it, expect } from "vitest";
import type { EnrolledCourse } from "@/lib/api";
import {
  buildFinalCards, commitBlocker, commitLabel, courseOptions, importedMessage,
  initialCourseId, isCommitDisabled, tabButtonStyle, validCardsOf,
} from "./importModalModel";

const course = (id: string, code: string, name: string): EnrolledCourse => ({
  enrollment_id: `e-${id}`, course_id: id, course_code: code, course_name: name,
  school: "X", department: "CS", color: null, nickname: null, node_count: 0,
  enrolled_at: "2026-01-01", term: "Spring 2026",
});

describe("initialCourseId", () => {
  it("prefers the default, then the first course, then blank", () => {
    expect(initialCourseId("d", [course("c1", "A", "a")])).toBe("d");
    expect(initialCourseId(undefined, [course("c1", "A", "a"), course("c2", "B", "b")])).toBe("c1");
    expect(initialCourseId(undefined, [])).toBe("");
  });

  it("keeps an empty-string default (?? not ||)", () => {
    expect(initialCourseId("", [course("c1", "A", "a")])).toBe("");
  });
});

describe("validCardsOf / buildFinalCards", () => {
  const cards = [
    { front: "a", back: "b", row: 1 },
    { front: "", back: "x", row: 2 },
    { front: "c", back: "d", row: 3, error: "bad" },
    { front: "e", back: "f", row: 4 },
  ];

  it("keeps only valid cards", () => {
    expect(validCardsOf(cards).map(c => c.row)).toEqual([1, 4]);
  });

  it("strips to front/back, and interleaves flips when reversed", () => {
    const valid = validCardsOf(cards);
    expect(buildFinalCards(valid, false)).toEqual([{ front: "a", back: "b" }, { front: "e", back: "f" }]);
    expect(buildFinalCards(valid, true)).toEqual([
      { front: "a", back: "b" }, { front: "b", back: "a" },
      { front: "e", back: "f" }, { front: "f", back: "e" },
    ]);
    expect(buildFinalCards([], true)).toEqual([]);
  });
});

describe("commitBlocker", () => {
  it("checks course, then topic, then cards", () => {
    expect(commitBlocker("", "", 0)).toBe("Pick a course first.");
    expect(commitBlocker("c", "  ", 0)).toBe("Add a topic name.");
    expect(commitBlocker("c", "t", 0)).toBe("No valid cards to import.");
    expect(commitBlocker("c", "t", 1)).toBeNull();
  });
});

describe("isCommitDisabled", () => {
  it("is enabled only when idle with cards, a course and a non-blank topic", () => {
    expect(isCommitDisabled(false, 1, "c", "t")).toBe(false);
    expect(isCommitDisabled(true, 1, "c", "t")).toBe(true);
    expect(isCommitDisabled(false, 0, "c", "t")).toBe(true);
    expect(isCommitDisabled(false, 1, "", "t")).toBe(true);
    expect(isCommitDisabled(false, 1, "c", " ")).toBe(true);
  });
});

describe("labels", () => {
  it("commitLabel pluralises and shows the busy label", () => {
    expect(commitLabel(false, 0)).toBe("Import 0 cards");
    expect(commitLabel(false, 1)).toBe("Import 1 card");
    expect(commitLabel(false, 2)).toBe("Import 2 cards");
    expect(commitLabel(true, 2)).toBe("Importing…");
  });

  it("importedMessage adds the skip note only when something was skipped", () => {
    expect(importedMessage({ inserted: 1, skipped_duplicates: 0 })).toBe("Imported 1 card.");
    expect(importedMessage({ inserted: 0, skipped_duplicates: 2 })).toBe("Imported 0 cards. 2 skipped (duplicates).");
  });
});

describe("courseOptions", () => {
  it("labels by code with the name as description, falling back to the name", () => {
    expect(courseOptions([course("c1", "CS101", "Intro"), course("c2", "", "Bio")])).toEqual([
      { value: "c1", label: "CS101", description: "Intro" },
      { value: "c2", label: "Bio", description: undefined },
    ]);
  });
});

describe("tabButtonStyle", () => {
  it("marks the active tab with weight, accent colour and underline", () => {
    expect(tabButtonStyle(true)).toEqual({
      padding: "8px 14px", fontSize: 13, fontWeight: 600, color: "var(--accent)",
      background: "transparent", borderBottom: "2px solid var(--accent)",
    });
    expect(tabButtonStyle(false)).toEqual({
      padding: "8px 14px", fontSize: 13, fontWeight: 500, color: "var(--text-dim)",
      background: "transparent", borderBottom: "2px solid transparent",
    });
  });
});
