import { describe, expect, it } from "vitest";
import {
  conceptIdsFromNames,
  conceptIdsFromNotes,
  libraryNext,
  libraryQuizHref,
  libraryTreeHref,
  normalizeConceptName,
  quizReady,
} from "./libraryNext";

describe("conceptIdsFromNotes / conceptIdsFromNames", () => {
  it("reads stamped node ids off concept notes in note order", () => {
    expect(conceptIdsFromNotes(null)).toEqual([]);
    expect(conceptIdsFromNotes([])).toEqual([]);
    expect(
      conceptIdsFromNotes([
        { name: "A", description: "", node_id: "n1" },
        { name: "B", description: "" },
        { name: "C", description: "", node_id: "  n3  " },
        { name: "D", description: "", node_id: "" },
      ]),
    ).toEqual(["n1", "n3"]);
  });

  it("maps names to graph node ids with the same normalize as the backend", () => {
    expect(normalizeConceptName("  Linear   Regression ")).toBe("linear regression");
    const nodes = [
      { id: "n-rec", concept_name: "Recursion", course_id: "c1" },
      { id: "n-other", concept_name: "Recursion", course_id: "c2" },
      { id: "n-loops", concept_name: "  Loops ", course_id: "c1" },
    ];
    expect(conceptIdsFromNames(["recursion", "Loops"], nodes, "c1")).toEqual([
      "n-rec",
      "n-loops",
    ]);
    expect(conceptIdsFromNames(["Recursion"], nodes, "c2")).toEqual(["n-other"]);
    expect(conceptIdsFromNames(["Missing"], nodes, "c1")).toEqual([]);
    expect(conceptIdsFromNames(["Recursion"], nodes, null)).toEqual([]);
  });
});

describe("libraryTreeHref / libraryQuizHref", () => {
  it("opens Tree with course when present, else the bare graph", () => {
    expect(libraryTreeHref()).toBe("/tree");
    expect(libraryTreeHref(null)).toBe("/tree");
    expect(libraryTreeHref("  ")).toBe("/tree");
    expect(libraryTreeHref("c1")).toBe("/tree?course=c1");
    expect(libraryTreeHref("c 1")).toBe("/tree?course=c%201");
  });

  it("prefers concept-scoped Quiz when node ids exist; else course + start", () => {
    expect(libraryQuizHref("c1")).toBe(
      "/quiz?course=c1&from=link&return=%2Flibrary&start=1",
    );
    expect(libraryQuizHref("c1", [])).toBe(
      "/quiz?course=c1&from=link&return=%2Flibrary&start=1",
    );
    expect(libraryQuizHref("c1", ["  ", ""])).toBe(
      "/quiz?course=c1&from=link&return=%2Flibrary&start=1",
    );
    expect(libraryQuizHref("c1", ["node-rec", "node-loops"])).toBe(
      "/quiz?concept=node-rec&from=link&return=%2Flibrary&start=1",
    );
  });
});

describe("libraryNext", () => {
  const base = {
    courseId: "c1",
    conceptCount: 3,
    loopOn: true,
    treeHidden: false,
    quizHidden: false,
  };

  it("says concepts added and checks drafting while pending", () => {
    const next = libraryNext({ ...base, checkItemsStatus: "pending" });
    expect(next.statusLine).toBe("3 concepts added · Checks drafting");
    expect(next.treeHref).toBe("/tree?course=c1");
    expect(next.quizHref).toBeNull();
  });

  it("offers Quiz these concepts when checks are done (course-scoped without ids)", () => {
    const next = libraryNext({ ...base, checkItemsStatus: "done" });
    expect(next.statusLine).toBe("3 concepts added · Checks ready");
    expect(next.quizHref).toBe("/quiz?course=c1&from=link&return=%2Flibrary&start=1");
  });

  it("offers concept-scoped Quiz when concept node ids exist", () => {
    const next = libraryNext({
      ...base,
      checkItemsStatus: "done",
      conceptIds: ["node-rec"],
    });
    expect(next.quizHref).toBe(
      "/quiz?concept=node-rec&from=link&return=%2Flibrary&start=1",
    );
  });

  it("treats a just-finished upload as drafting when status is not back yet", () => {
    const next = libraryNext({
      ...base,
      checkItemsStatus: null,
      justUploaded: true,
    });
    expect(next.statusLine).toBe("3 concepts added · Checks drafting");
    expect(next.quizHref).toBeNull();
  });

  it("hides Tree / Quiz when their nav flags are on", () => {
    expect(libraryNext({ ...base, checkItemsStatus: "done", treeHidden: true }).treeHref).toBeNull();
    expect(libraryNext({ ...base, checkItemsStatus: "done", quizHidden: true }).quizHref).toBeNull();
  });

  it("omits drafting copy when the learning loop is off", () => {
    const next = libraryNext({
      ...base,
      loopOn: false,
      checkItemsStatus: "pending",
    });
    expect(next.statusLine).toBe("3 concepts added");
    expect(quizReady({ ...base, loopOn: false, checkItemsStatus: "pending" })).toBe(true);
  });

  it("needs a course for Quiz", () => {
    expect(quizReady({ ...base, courseId: null, checkItemsStatus: "done" })).toBe(false);
  });

  it("opens bare Tree when the document has no course", () => {
    expect(libraryNext({ ...base, courseId: null, checkItemsStatus: "pending" }).treeHref).toBe(
      "/tree",
    );
  });
});
