import { describe, expect, it } from "vitest";

import type { GuideCard } from "@/lib/studyGuide/types";

import {
  DEPTH_LABEL,
  GOAL_LABEL,
  SORTS,
  dateText,
  guideDate,
  libraryGuides,
  newLecturesText,
  searchGuides,
  sortGuides,
  sortLabel,
  statusText,
} from "./guidesModel";

const NOW = new Date("2026-11-12T12:00:00Z");

const guide = (over: Partial<GuideCard>): GuideCard => ({
  id: "g1", title: "Loops and recursion", course_id: "c1", course_name: "Intro to CS", semester: null,
  scope_kind: "exam", scope_label: "Midterm 2", goal: "exam_prep", depth: "standard", status: "ready",
  generated_at: "2026-11-10T12:00:00Z", created_at: "2026-11-10T11:00:00Z", saved_at: null,
  new_materials: 0, bars: [], counts: { sections: 0, blocks: 0, practice: 0, minutes: 0 },
  ...over,
});

const A = guide({ id: "a", title: "Loops and recursion", generated_at: "2026-11-10T12:00:00Z" });
const B = guide({ id: "b", title: "Limits", course_id: "c2", course_name: "Calculus", scope_label: "Whole course", generated_at: "2026-11-11T12:00:00Z" });
const C = guide({ id: "c", title: "Arrays", scope_label: "Lab 5", generated_at: null, created_at: "2026-11-09T12:00:00Z" });
const ids = (guides: GuideCard[]) => guides.map(g => g.id);

describe("labels", () => {
  it("names every goal, depth and sort", () => {
    expect(GOAL_LABEL).toEqual({ practice: "Practice", review: "Review", exam_prep: "Exam prep" });
    expect(DEPTH_LABEL).toEqual({ cram: "Cram sheet", standard: "Standard", deep: "Deep review" });
    expect(SORTS.map(s => s.label)).toEqual(["Most recent", "Oldest", "Class"]);
    expect(sortLabel("class")).toBe("Class");
  });
});

describe("guideDate", () => {
  it("is when the guide was written, or its row's date while it has not been", () => {
    expect(guideDate(A)).toBe("2026-11-10T12:00:00Z");
    expect(guideDate(C)).toBe("2026-11-09T12:00:00Z");
  });
});

describe("searchGuides", () => {
  it("keeps everything for a blank query", () => {
    expect(searchGuides([A, B, C], "   ")).toEqual([A, B, C]);
  });

  it("matches the title, the class name and the scope label, in any case", () => {
    expect(ids(searchGuides([A, B, C], "recurs"))).toEqual(["a"]);
    expect(ids(searchGuides([A, B, C], "CALC"))).toEqual(["b"]);
    expect(ids(searchGuides([A, B, C], "lab 5"))).toEqual(["c"]);
    expect(searchGuides([A, B, C], "chemistry")).toEqual([]);
  });
});

describe("sortGuides", () => {
  it("puts the newest first, or the oldest", () => {
    expect(ids(sortGuides([A, B, C], "recent"))).toEqual(["b", "a", "c"]);
    expect(ids(sortGuides([A, B, C], "oldest"))).toEqual(["c", "a", "b"]);
  });

  it("groups by class name, newest first inside a class", () => {
    expect(ids(sortGuides([C, A, B], "class"))).toEqual(["b", "a", "c"]);
  });

  it("leaves the list it was given alone", () => {
    const list = [A, B, C];
    sortGuides(list, "oldest");
    expect(ids(list)).toEqual(["a", "b", "c"]);
  });
});

describe("dateText", () => {
  it("says Today and Yesterday, then the day", () => {
    expect(dateText(guide({ generated_at: "2026-11-12T12:00:00Z" }), NOW)).toBe("Today");
    expect(dateText(guide({ generated_at: "2026-11-11T12:00:00Z" }), NOW)).toBe("Yesterday");
    expect(dateText(A, NOW)).toBe("Nov 10");
  });

  it("adds the year once it is not this one", () => {
    expect(dateText(guide({ generated_at: "2025-05-03T12:00:00Z" }), NOW)).toBe("May 3, 2025");
  });

  it("falls back to the row's date for a guide not written yet", () => {
    expect(dateText(C, NOW)).toBe("Nov 9");
  });
});

describe("newLecturesText", () => {
  it("counts the lectures added since, and says nothing for none", () => {
    expect(newLecturesText(0)).toBe("");
    expect(newLecturesText(1)).toBe("1 new lecture");
    expect(newLecturesText(2)).toBe("2 new lectures");
  });
});

describe("statusText", () => {
  it("speaks only for a guide that is not ready", () => {
    expect(statusText("ready")).toBe("");
    expect(statusText("generating")).toBe("Writing…");
    expect(statusText("failed")).toBe("Could not finish");
  });
});

describe("libraryGuides", () => {
  const savedA = { ...A, saved_at: "2026-11-11T00:00:00Z" };
  const savedB = { ...B, saved_at: "2026-11-11T00:00:00Z" };
  const all = [savedA, savedB, C];

  it("keeps only the guides saved to the Library", () => {
    expect(ids(libraryGuides(all, "all", ""))).toEqual(["a", "b"]);
  });

  it("follows the course filter; a guide is never uncategorized", () => {
    expect(ids(libraryGuides(all, "c2", ""))).toEqual(["b"]);
    expect(libraryGuides(all, "uncategorized", "")).toEqual([]);
  });

  it("follows the search", () => {
    expect(ids(libraryGuides(all, "all", "limits"))).toEqual(["b"]);
    expect(libraryGuides(all, "c1", "limits")).toEqual([]);
  });
});
