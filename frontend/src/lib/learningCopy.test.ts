import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

import { BANNED_STUDENT_TERMS, LEARNING_COPY, plural } from "./learningCopy";

describe("plural", () => {
  it("counts one and many, with an irregular plural when given", () => {
    expect(plural(1, "concept")).toBe("1 concept");
    expect(plural(0, "concept")).toBe("0 concepts");
    expect(plural(3, "course")).toBe("3 courses");
    expect(plural(2, "quiz", "quizzes")).toBe("2 quizzes");
  });
});

describe("LEARNING_COPY", () => {
  it("names each idea once: start, resume, learn, review", () => {
    expect(LEARNING_COPY.newSession).toBe("New session");
    expect(LEARNING_COPY.continueSession("Recursion")).toBe("Continue Recursion");
    expect(LEARNING_COPY.learnConcept("Loops")).toBe("Learn Loops");
    expect(LEARNING_COPY.startPlan).toBe("Start this plan");
    expect(LEARNING_COPY.review).toBe("Review");
    expect(LEARNING_COPY.reviewLink(0)).toBe("Review");
    expect(LEARNING_COPY.reviewLink(null)).toBe("Review");
    expect(LEARNING_COPY.reviewLink(1)).toBe("1 review due");
    expect(LEARNING_COPY.reviewLink(4)).toBe("4 reviews due");
    expect(LEARNING_COPY.reviewsDue(0)).toBe("Nothing due right now");
    expect(LEARNING_COPY.practiceDue).not.toMatch(/learn|teach|tutor/i);
  });

  it("uses no banned term, no middle dot and no em-dash fragment", () => {
    const words = Object.values(LEARNING_COPY).map((v) => (typeof v === "function" ? v(2 as never) : v));
    for (const w of words) {
      expect(w).not.toMatch(BANNED_STUDENT_TERMS);
      expect(w).not.toMatch(/ · | — |\(optional\)/);
    }
  });
});

/** The retired names of these ideas (the audit's seven "start" labels and
 *  seven "due" labels): none may come back on a learning surface. */
const RETIRED = [
  "Due on Study", "Start a guided session", "Start a new session", "Review flashcards",
  "Continue learning:", "Continue in Tutor", "Start review",
];
const SURFACES = ["components/learn", "components/study", "components/quiz", "components/flashcards", "lib"];
// The loop-off app (main's pre-loop Learn screen) keeps its own words.
const EXEMPT = new Set(["components/screens/Learn.tsx"]);

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.|\.characterize\./.test(name) ? [path] : [];
  });
}

describe("retired labels", () => {
  const root = join(__dirname, "..");
  it.each(SURFACES)("none in src/%s", (surface) => {
    const hits: string[] = [];
    for (const file of sources(join(root, surface))) {
      const rel = relative(root, file);
      if (EXEMPT.has(rel) || rel === "lib/learningCopy.ts") continue;
      // Code only: comments may name the history.
      const code = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
      for (const label of RETIRED) if (code.includes(label)) hits.push(`${rel}: ${label}`);
    }
    expect(hits).toEqual([]);
  });
});
