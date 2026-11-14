import { describe, expect, it } from "vitest";

import type { GuideCard } from "@/lib/studyGuide/types";

import {
  SORTS,
  dateText,
  guideDate,
  libraryGuides,
  searchGuides,
  sortGuides,
  sortLabel,
  statusText,
} from "./guidesModel";

const NOW = new Date("2026-11-12T12:00:00Z");

const guide = (over: Partial<GuideCard>): GuideCard => ({
  id: "g1", title: "Loops and recursion", course_id: "c1", course_name: "Intro to CS", course_code: "CS101", semester: null,
  scope_kind: "exam", scope_label: "Midterm 2", goal: "exam_prep", depth: "standard", status: "ready",
  generated_at: "2026-11-10T12:00:00Z", created_at: "2026-11-10T11:00:00Z", saved_at: null,
  new_materials: 0, bars: [], counts: { sections: 0, blocks: 0, practice: 0, minutes: 0 },
  ...over,
});

const A = guide({ id: "a", title: "Loops and recursion", generated_at: "2026-11-10T12:00:00Z" });
const B = guide({ id: "b", title: "Limits", course_id: "c2", course_name: "Calculus", course_code: "MA225", scope_label: "Whole course", generated_at: "2026-11-11T12:00:00Z" });
const C = guide({ id: "c", title: "Arrays", scope_label: "Lab 5", generated_at: null, created_at: "2026-11-09T12:00:00Z" });
const ids = (guides: GuideCard[]) => guides.map(g => g.id);

describe("labels", () => {
  it("names every sort", () => {
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

  it("matches the title, the class name or code and the scope label, in any case", () => {
    expect(ids(searchGuides([A, B, C], "recurs"))).toEqual(["a"]);
    expect(ids(searchGuides([A, B, C], "CALC"))).toEqual(["b"]);
    expect(ids(searchGuides([A, B, C], "ma225"))).toEqual(["b"]);
    expect(ids(searchGuides([A, B, C], "lab 5"))).toEqual(["c"]);
    expect(searchGuides([A, B, C], "chemistry")).toEqual([]);
  });
});

describe("sortGuides", () => {
  it("puts the newest first, or the oldest", () => {
    expect(ids(sortGuides([A, B, C], "recent"))).toEqual(["b", "a", "c"]);
    expect(ids(sortGuides([A, B, C], "oldest"))).toEqual(["c", "a", "b"]);
  });

  it("groups by the class code a card shows, newest first inside a class", () => {
    // CS101 before MA225, though Calculus comes before Intro to CS.
    expect(ids(sortGuides([C, B, A], "class"))).toEqual(["a", "c", "b"]);
  });

  it("leaves the list it was given alone", () => {
    const list = [A, B, C];
    sortGuides(list, "oldest");
    expect(ids(list)).toEqual(["a", "b", "c"]);
  });
});

describe("dateText", () => {
  it("says Today, then the day", () => {
    expect(dateText(guide({ generated_at: "2026-11-12T12:00:00Z" }), NOW)).toBe("Today");
    expect(dateText(guide({ generated_at: "2026-11-11T12:00:00Z" }), NOW)).toBe("Nov 11");
    expect(dateText(A, NOW)).toBe("Nov 10");
  });

  it("says nothing for a date it cannot read", () => {
    expect(dateText(guide({ generated_at: "soon" }), NOW)).toBe("");
  });

  it("adds the year once it is not this one", () => {
    expect(dateText(guide({ generated_at: "2025-05-03T12:00:00Z" }), NOW)).toBe("May 3, 2025");
  });

  it("falls back to the row's date for a guide not written yet", () => {
    expect(dateText(C, NOW)).toBe("Nov 9");
  });
});

describe("statusText", () => {
  it("speaks only for a guide that is not ready", () => {
    expect(statusText("ready")).toBe("");
    // Nothing may be writing it: the card only knows it is not done.
    expect(statusText("generating")).toBe("Not finished");
    expect(statusText("failed")).toBe("Could not finish");
  });
});

describe("libraryGuides", () => {
  const savedA = { ...A, saved_at: "2026-11-11T00:00:00Z" };
  const savedB = { ...B, saved_at: "2026-11-11T00:00:00Z" };
  const all = [savedA, savedB, C];

  it("keeps only the guides saved to the Library", () => {
    expect(ids(libraryGuides(all, { category: "all", courseFilter: "all", query: "" }))).toEqual(["a", "b"]);
  });

  it("follows the course filter; a guide is never uncategorized", () => {
    expect(ids(libraryGuides(all, { category: "all", courseFilter: "c2", query: "" }))).toEqual(["b"]);
    expect(libraryGuides(all, { category: "all", courseFilter: "uncategorized", query: "" })).toEqual([]);
    expect(ids(libraryGuides(all, { category: "study_guide", courseFilter: "all", query: "" }))).toEqual(["a", "b"]);
    expect(libraryGuides(all, { category: "slides", courseFilter: "all", query: "" })).toEqual([]);
  });

  it("follows the search", () => {
    expect(ids(libraryGuides(all, { category: "all", courseFilter: "all", query: "limits" }))).toEqual(["b"]);
    expect(libraryGuides(all, { category: "all", courseFilter: "c1", query: "limits" })).toEqual([]);
  });
});
