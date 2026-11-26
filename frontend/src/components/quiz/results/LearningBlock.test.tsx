// @vitest-environment jsdom
/**
 * The quiz results' learning block (learning-loop spec §13 A147 / W7.7,
 * `quiz_results_routing`): the skill meters that moved, what is due, and the
 * next steps on the Tree / Study / Tutor spine — review only where the
 * learning loop is on.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import React from "react";
import type { QuizLearning } from "@/lib/quiz/types";

const loop = vi.hoisted(() => ({ status: true as boolean | "error" | null, calls: [] as [string, boolean][] }));
const nav = vi.hoisted(() => ({ studyShown: true, flags: {} as Record<string, string> }));

vi.mock("@/components/learn/useLoopStatus", () => ({
  useLoopStatus: (userId: string, ready: boolean) => {
    loop.calls.push([userId, ready]);
    return { status: ready ? loop.status : null, retry: () => {} };
  },
}));
vi.mock("@/components/useRetentionNav", () => ({ useStudyNavShown: () => nav.studyShown }));
vi.mock("@/context/FlagsContext", () => ({ useFlag: (key: string) => nav.flags[key] ?? "off" }));
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "user_andres", userReady: true }),
}));

import {
  LearningBlock,
  changeLine,
  conceptTreeHref,
  dueIn,
  learnHref,
  reviewHref,
} from "./LearningBlock";

afterEach(() => {
  cleanup();
  loop.status = true;
  loop.calls = [];
  nav.studyShown = true;
  nav.flags = {};
});

const LEARNING: QuizLearning = {
  changes: [
    {
      concept_id: "n1",
      concept_name: "Recursion",
      before: 0.35,
      after: 0.62,
      band_before: "develop",
      band_after: "develop",
    },
    {
      concept_id: "n0",
      concept_name: "Functions",
      before: 0.78,
      after: 0.81,
      band_before: "develop",
      band_after: "profic",
    },
  ],
  review: { due_count: 2, next_due_at: null },
  next_step: "review",
  learn: { concept_id: "n2", concept_name: "Loops", course_id: "cs111" },
};

function renderBlock(
  learning: QuizLearning = LEARNING,
  opts: { conceptName?: string; conceptId?: string; courseId?: string | null } = {},
) {
  return render(
    <LearningBlock
      learning={learning}
      conceptName={opts.conceptName ?? "Recursion"}
      conceptId={opts.conceptId ?? "n1"}
      courseId={opts.courseId ?? "cs111"}
    />,
  );
}

describe("LearningBlock", () => {
  it("words each meter that moved, in the server's order", () => {
    renderBlock();
    const rows = screen.getAllByTestId("quiz-results-change").map(r => r.textContent);
    expect(rows).toEqual([
      "Recursion: rose from 35% to 62% (still developing)",
      "Functions: rose from 78% to 81% (now proficient)",
    ]);
  });

  it("offers Study review, Learn, and Tree on the shared spine", () => {
    renderBlock();
    expect(screen.getByTestId("quiz-results-due").textContent).toContain("2 concepts are due for review.");
    const review = screen.getByTestId("quiz-next-step-review");
    expect(review.getAttribute("href")).toBe("/study?course=cs111");
    expect(review.textContent).toBe("2 reviews due");
    expect(screen.getByTestId("quiz-next-step-learn").getAttribute("href")).toBe(
      "/learn?topic=Loops&concept=n2&mode=socratic&course=cs111",
    );
    const tree = screen.getByTestId("quiz-next-step-tree");
    expect(tree.getAttribute("href")).toBe("/tree?node=n1");
    expect(tree.textContent).toBe("See on your map");
    expect(loop.calls.at(-1)).toEqual(["user_andres", true]);
  });

  it("falls back to Learn when the review queue is not there", () => {
    loop.status = false;
    renderBlock();
    expect(screen.queryByTestId("quiz-next-step-review")).toBeNull();
    expect(screen.getByTestId("quiz-next-step-learn").className).toBe("btn btn--primary");
    expect(screen.getByTestId("quiz-next-step-tree").className).toBe("btn");
  });

  it("does not probe the loop for a Learn step, and says when the concept comes back", () => {
    const now = Date.now();
    renderBlock(
      {
        ...LEARNING,
        next_step: "learn",
        review: { due_count: 0, next_due_at: new Date(now + 3 * 86_400_000 - 60_000).toISOString() },
      },
    );
    expect(loop.calls.every(([, ready]) => ready === false)).toBe(true);
    expect(screen.getByTestId("quiz-results-due").textContent).toBe(
      "Nothing is due for review right now. Recursion comes back for review in 3 days.",
    );
    expect(screen.getByTestId("quiz-next-step-learn").textContent).toBe("Learn Loops");
  });

  it("never links to a page a hide flag hides (Z62): Study, Learn, Tree", () => {
    nav.studyShown = false;
    renderBlock();
    expect(screen.queryByTestId("quiz-next-step-review")).toBeNull();
    expect(screen.getByTestId("quiz-next-step-learn").className).toBe("btn btn--primary");
    expect(screen.getByTestId("quiz-next-step-tree")).toBeTruthy();
    cleanup();
    nav.studyShown = true;
    nav.flags = { hide_tutor: "on" };
    renderBlock();
    expect(screen.getByTestId("quiz-next-step-review")).toBeTruthy();
    expect(screen.queryByTestId("quiz-next-step-learn")).toBeNull();
    expect(screen.getByTestId("quiz-next-step-tree")).toBeTruthy();
    cleanup();
    nav.flags = { hide_tree: "on" };
    renderBlock();
    expect(screen.getByTestId("quiz-next-step-review")).toBeTruthy();
    expect(screen.getByTestId("quiz-next-step-learn")).toBeTruthy();
    expect(screen.queryByTestId("quiz-next-step-tree")).toBeNull();
    cleanup();
    nav.studyShown = false;
    nav.flags = { hide_tutor: "on", hide_tree: "on" };
    renderBlock({ changes: [], review: { due_count: 0, next_due_at: null }, next_step: "none", learn: null });
    expect(screen.queryByTestId("quiz-learning-next")).toBeNull();
    expect(screen.queryByText("Next:")).toBeNull();
  });

  it("still offers Tree when the server names no next step", () => {
    renderBlock({ changes: [], review: { due_count: 0, next_due_at: null }, next_step: "none", learn: null });
    expect(screen.getByTestId("quiz-results-no-change")).toBeTruthy();
    expect(screen.queryByTestId("quiz-next-step-learn")).toBeNull();
    expect(screen.queryByTestId("quiz-next-step-review")).toBeNull();
    const tree = screen.getByTestId("quiz-next-step-tree");
    expect(tree.getAttribute("href")).toBe("/tree?node=n1");
    expect(tree.className).toBe("btn btn--primary");
  });
});

describe("the block's words", () => {
  it("dueIn counts whole days from now", () => {
    const now = new Date("2026-11-08T12:00:00Z");
    expect(dueIn(null, now)).toBeNull();
    expect(dueIn("2026-11-08T13:00:00Z", now)).toBe("today");
    expect(dueIn("2026-11-08T11:00:00Z", now)).toBe("today");
    expect(dueIn("2026-11-09T12:00:00Z", now)).toBe("tomorrow");
    expect(dueIn("2026-11-12T11:00:00Z", now)).toBe("in 4 days");
    expect(dueIn("not a date", now)).toBeNull();
  });

  it("a falling meter says so", () => {
    expect(
      changeLine({ concept_id: "x", concept_name: "Trees", before: 0.6, after: 0.41, band_before: "develop", band_after: "develop" }),
    ).toBe("Trees: fell from 60% to 41% (still developing)");
  });

  it("the Learn link matches the shared handoff (mode + concept)", () => {
    expect(learnHref({ concept_id: "x", concept_name: "Big O", course_id: null })).toBe(
      "/learn?topic=Big+O&concept=x&mode=socratic",
    );
    const params = new URLSearchParams(
      learnHref({ concept_id: "n7", concept_name: "Big O", course_id: "c1" }).split("?")[1],
    );
    expect([params.get("topic"), params.get("concept"), params.get("course"), params.get("mode")]).toEqual([
      "Big O",
      "n7",
      "c1",
      "socratic",
    ]);
  });

  it("Study and Tree hrefs reuse the shared handoff builders", () => {
    expect(reviewHref("cs111")).toBe("/study?course=cs111");
    expect(reviewHref(null)).toBe("/study");
    expect(conceptTreeHref("n1")).toBe("/tree?node=n1");
  });
});
