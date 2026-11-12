import { describe, it, expect } from "vitest";
import { flashcardsHref, studyGuideHref, studyHref, STUDY_TOOL_PATHS } from "./toolHrefs";

describe("studyHref", () => {
  it("opens the hub on a course, or plainly", () => {
    expect(studyHref("c1")).toBe("/study?course=c1");
    expect(studyHref()).toBe("/study");
    expect(studyHref(null)).toBe("/study");
  });
});

describe("studyGuideHref", () => {
  it("opens the Study Guide page on the course and the selected exam", () => {
    expect(studyGuideHref("c1", "e2")).toBe("/study/guide?course=c1&exam=e2");
  });

  it("carries only what it is given", () => {
    expect(studyGuideHref("c1")).toBe("/study/guide?course=c1");
    expect(studyGuideHref()).toBe("/study/guide");
  });

  it("lives under /study, so the shell's auth and hide_study gates cover it", () => {
    expect(studyGuideHref("c1").startsWith("/study/")).toBe(true);
  });
});

describe("flashcardsHref", () => {
  it("carries the course and the picked concepts", () => {
    expect(flashcardsHref("c1", ["Loops", "Recursion"]))
      .toBe("/flashcards?course=c1&concepts=Loops%7CRecursion");
    expect(flashcardsHref("c1")).toBe("/flashcards?course=c1");
    expect(flashcardsHref()).toBe("/flashcards");
  });

  it("asks the page to start when told to", () => {
    expect(flashcardsHref("c1", ["Loops"], { start: true }))
      .toBe("/flashcards?course=c1&concepts=Loops&start=1");
  });
});

describe("STUDY_TOOL_PATHS", () => {
  it("lists the pages that keep Study selected in the nav", () => {
    expect(STUDY_TOOL_PATHS).toEqual(["/quiz", "/flashcards"]);
  });
});
