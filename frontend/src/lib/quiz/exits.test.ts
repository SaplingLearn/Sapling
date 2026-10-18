import { describe, expect, it } from "vitest";
import { cancelTarget, returnToSource, sourceLabel } from "./exits";
import { initialSession } from "./machine";
import type { QuizConfig, QuizPrefs, QuizSession, QuizSource } from "./types";

const CONFIG: QuizConfig = {
  num_questions: { min: 1, max: 10, options: [3, 5, 10] },
  difficulties: ["easy", "medium", "hard", "adaptive"],
  question_types: ["multiple_choice"],
};
const PREFS: QuizPrefs = { count: null, difficulty: null, feedback: "at-end" };

function sessionFrom(source: QuizSource, concept?: string): QuizSession {
  return initialSession({ source, concept }, CONFIG, PREFS);
}

describe("returnToSource", () => {
  it("honours an explicit same-origin return", () => {
    expect(returnToSource(sessionFrom({ kind: "tree", returnTo: "/tree?node=n1" })))
      .toBe("/tree?node=n1");
    expect(returnToSource(sessionFrom({ kind: "notes", returnTo: "/notetaker?note=n7" })))
      .toBe("/notetaker?note=n7");
  });

  it("falls back to the tree focused on the concept", () => {
    expect(returnToSource(sessionFrom({ kind: "link" }, "node-1"))).toBe("/tree?node=node-1");
    expect(returnToSource(sessionFrom({ kind: "nav" }))).toBe("/tree");
  });

  it("encodes a concept id with URL-hostile characters", () => {
    expect(returnToSource(sessionFrom({ kind: "link" }, "a b&c"))).toBe("/tree?node=a%20b%26c");
  });

  it("re-checks the stored return — localStorage is not trusted input", () => {
    const poisoned = sessionFrom({ kind: "tree", conceptId: "n1" });
    poisoned.source.returnTo = "https://evil.com";
    expect(returnToSource(poisoned)).toBe("/tree?node=n1");
  });

  it("never lands on /learn", () => {
    for (const kind of ["tree", "dashboard", "notes", "nav", "link", "quiz"] as const) {
      expect(returnToSource(sessionFrom({ kind }))).not.toContain("/learn");
    }
  });
});

describe("sourceLabel", () => {
  it("names the origin", () => {
    expect(sourceLabel("tree")).toBe("Back to your tree");
    expect(sourceLabel("notes")).toBe("Back to your note");
    expect(sourceLabel("dashboard")).toBe("Back to dashboard");
  });

  it("reads as the tree for every other origin, matching the fallback exit", () => {
    expect(sourceLabel("nav")).toBe("Back to your tree");
    expect(sourceLabel("link")).toBe("Back to your tree");
    expect(sourceLabel("quiz")).toBe("Back to your tree");
  });
});

describe("cancelTarget", () => {
  it("returns to the origin when there was one", () => {
    expect(cancelTarget(sessionFrom({ kind: "tree", returnTo: "/tree?node=n1" })))
      .toBe("/tree?node=n1");
  });

  it("goes to the dashboard when the quiz was opened cold", () => {
    expect(cancelTarget(sessionFrom({ kind: "nav" }))).toBe("/dashboard");
  });
});
