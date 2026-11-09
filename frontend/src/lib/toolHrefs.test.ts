import { describe, it, expect } from "vitest";
import { libraryHref, flashcardsHref, studyGuideHref, STUDY_TOOL_PATHS } from "./toolHrefs";

describe("libraryHref", () => {
  it("narrows by course, type and search", () => {
    expect(libraryHref("c1", "study_guide")).toBe("/library?course=c1&type=study_guide");
    expect(libraryHref("c1", undefined, "Recursion")).toBe("/library?course=c1&q=Recursion");
    expect(libraryHref()).toBe("/library");
  });

  it("escapes a concept name with spaces", () => {
    expect(libraryHref("c1", undefined, "Pointers and Memory"))
      .toBe("/library?course=c1&q=Pointers+and+Memory");
  });
});

describe("studyGuideHref", () => {
  it("searches the course's material for ONE concept", () => {
    // Not type=study_guide: that answers "which uploads are study guides",
    // which on a course without one is an empty shelf and a dead end.
    expect(studyGuideHref("c1", "Recursion")).toBe("/library?course=c1&q=Recursion");
  });

  it("falls back to the course's study-guide shelf with no concept", () => {
    expect(studyGuideHref("c1")).toBe("/library?course=c1&type=study_guide");
  });
});

describe("flashcardsHref", () => {
  it("carries the course and the picked concepts", () => {
    expect(flashcardsHref("c1", ["Loops", "Recursion"]))
      .toBe("/flashcards?course=c1&concepts=Loops%7CRecursion");
    expect(flashcardsHref("c1")).toBe("/flashcards?course=c1");
    expect(flashcardsHref()).toBe("/flashcards");
  });
});

describe("STUDY_TOOL_PATHS", () => {
  it("lists the pages that keep Study selected in the nav", () => {
    expect(STUDY_TOOL_PATHS).toEqual(["/quiz", "/flashcards"]);
  });
});
