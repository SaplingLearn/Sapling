import { describe, it, expect } from "vitest";
import {
  CONCEPTS_PARAM,
  STUDY_TOOL_PATHS,
  consumeNewParam,
  decodeConcepts,
  encodeConcepts,
  flashcardsHref,
  studyGuideHref,
  studyGuideReaderHref,
  studyHref,
} from "./toolHrefs";

describe("studyHref", () => {
  it("opens the hub on a course, or plainly", () => {
    expect(studyHref("c1")).toBe("/study?course=c1");
    expect(studyHref()).toBe("/study");
    expect(studyHref(null)).toBe("/study");
  });
});

describe("studyGuideHref", () => {
  it("opens the Study Guides home", () => {
    expect(studyGuideHref()).toBe("/study/guide");
    expect(studyGuideHref(null)).toBe("/study/guide");
  });

  it("opens the New study guide dialog on a course when given one", () => {
    expect(studyGuideHref("c1")).toBe("/study/guide?new=1&course=c1");
    expect(studyGuideHref("a b")).toBe("/study/guide?new=1&course=a+b");
  });

  it("lives under /study, so the shell's auth and hide_study gates cover it", () => {
    expect(studyGuideHref("c1").startsWith("/study/")).toBe(true);
  });
});

describe("studyGuideReaderHref", () => {
  it("opens one guide in the reader, under the home", () => {
    expect(studyGuideReaderHref("g1")).toBe("/study/guide/g1");
    expect(studyGuideReaderHref("a/b")).toBe("/study/guide/a%2Fb");
  });
});

describe("consumeNewParam", () => {
  it("does nothing where there is no window", () => {
    expect(() => consumeNewParam()).not.toThrow();
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

describe("the concepts param", () => {
  const roundTrip = (names: string[]) =>
    decodeConcepts(new URL(flashcardsHref("c1", names), "http://x").searchParams.get(CONCEPTS_PARAM));

  it("reads back exactly what was written, whatever the names hold", () => {
    const names = [
      "Loops", "Read | Write", "AT&T syntax", "Big-O, formally", "100% coverage",
      "C:\\paths", "ends with \\", "a\\|b", "x=y?z#w + v",
    ];
    expect(roundTrip(names)).toEqual(names);
  });

  it("writes ordinary names as it always did", () => {
    expect(encodeConcepts(["Loops", "Recursion"])).toBe("Loops|Recursion");
    expect(encodeConcepts(["Read | Write"])).toBe("Read \\| Write");
  });

  it("still reads a link made before names were escaped", () => {
    expect(decodeConcepts("Loops|Recursion")).toEqual(["Loops", "Recursion"]);
    expect(decodeConcepts("Loops| Recursion ||")).toEqual(["Loops", "Recursion"]);
    // A lone backslash was never an escape: it stays part of the name.
    expect(decodeConcepts("C:\\dir\\file|Loops")).toEqual(["C:\\dir\\file", "Loops"]);
  });

  it("nothing in, nothing out", () => {
    expect(decodeConcepts(null)).toEqual([]);
    expect(decodeConcepts("")).toEqual([]);
    expect(encodeConcepts([])).toBe("");
  });
});

describe("STUDY_TOOL_PATHS", () => {
  it("lists the pages that keep Study selected in the nav", () => {
    expect(STUDY_TOOL_PATHS).toEqual(["/quiz", "/flashcards"]);
  });
});
