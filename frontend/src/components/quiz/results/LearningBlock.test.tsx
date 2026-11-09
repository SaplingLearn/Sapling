// @vitest-environment jsdom
/**
 * The quiz results' learning block (learning-loop spec §13 A147,
 * `quiz_results_routing`): the skill meters that moved, what is due, and the
 * next step — the review queue only where the learning loop is on.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import React from "react";
import type { QuizLearning } from "@/lib/quiz/types";

const loop = vi.hoisted(() => ({ status: true as boolean | "error" | null, calls: [] as [string, boolean][] }));

vi.mock("@/components/learn/useLoopStatus", () => ({
  useLoopStatus: (userId: string, ready: boolean) => {
    loop.calls.push([userId, ready]);
    return { status: ready ? loop.status : null, retry: () => {} };
  },
}));
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "user_andres", userReady: true }),
}));

import { LearningBlock, changeLine, dueIn, learnHref } from "./LearningBlock";

afterEach(() => {
  cleanup();
  loop.status = true;
  loop.calls = [];
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

describe("LearningBlock", () => {
  it("words each meter that moved, in the server's order", () => {
    render(<LearningBlock learning={LEARNING} conceptName="Recursion" />);
    const rows = screen.getAllByTestId("quiz-results-change").map(r => r.textContent);
    expect(rows).toEqual([
      "Recursion: rose from 35% to 62% (still developing)",
      "Functions: rose from 78% to 81% (now proficient)",
    ]);
  });

  it("offers the review queue first when something is due and the loop is on", () => {
    render(<LearningBlock learning={LEARNING} conceptName="Recursion" />);
    expect(screen.getByTestId("quiz-results-due").textContent).toContain("2 concepts are due for review.");
    const review = screen.getByTestId("quiz-next-step-review");
    expect(review.getAttribute("href")).toBe("/study?mode=cards");
    expect(review.textContent).toBe("Review what's due (2)");
    expect(screen.getByTestId("quiz-next-step-learn").getAttribute("href")).toBe("/learn?topic=Loops&course=cs111");
    expect(loop.calls.at(-1)).toEqual(["user_andres", true]);
  });

  it("falls back to Learn when the review queue is not there", () => {
    loop.status = false;
    render(<LearningBlock learning={LEARNING} conceptName="Recursion" />);
    expect(screen.queryByTestId("quiz-next-step-review")).toBeNull();
    expect(screen.getByTestId("quiz-next-step-learn").className).toBe("btn btn--primary");
  });

  it("does not probe the loop for a Learn step, and says when the concept comes back", () => {
    const now = Date.now();
    render(
      <LearningBlock
        learning={{
          ...LEARNING,
          next_step: "learn",
          review: { due_count: 0, next_due_at: new Date(now + 3 * 86_400_000 - 60_000).toISOString() },
        }}
        conceptName="Recursion"
      />,
    );
    expect(loop.calls.every(([, ready]) => ready === false)).toBe(true);
    expect(screen.getByTestId("quiz-results-due").textContent).toBe(
      "Nothing is due for review right now. Recursion comes back for review in 3 days.",
    );
    expect(screen.getByTestId("quiz-next-step-learn").textContent).toBe("Practise Loops in Learn");
  });

  it("says plainly when no meter moved and offers no step when there is none", () => {
    render(
      <LearningBlock
        learning={{ changes: [], review: { due_count: 0, next_due_at: null }, next_step: "none", learn: null }}
        conceptName="Recursion"
      />,
    );
    expect(screen.getByTestId("quiz-results-no-change")).toBeTruthy();
    expect(screen.queryByTestId("quiz-next-step-learn")).toBeNull();
    expect(screen.queryByTestId("quiz-next-step-review")).toBeNull();
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

  it("the Learn link omits a missing course", () => {
    expect(learnHref({ concept_id: "x", concept_name: "Big O", course_id: null })).toBe("/learn?topic=Big+O");
  });
});
