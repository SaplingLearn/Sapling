// @vitest-environment jsdom
/**
 * W7.5 study-guide drawer: leak-safe scaffold — cards + concept Ask, never
 * quiz answers or guide detail keys.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { __resetScrollLocksForTests } from "@/lib/useScrollLock";
import {
  composeGuideAskMessage,
  guidesForCourse,
  StudyGuideDrawer,
} from "./StudyGuideDrawer";

const listGuides = vi.hoisted(() => vi.fn());
vi.mock("@/lib/studyGuide/api", () => ({ listGuides }));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("next/dynamic", () => ({
  default: () =>
    function MarkdownStub({ children }: { children: React.ReactNode }) {
      return <div>{children}</div>;
    },
}));

const askTurn = vi.hoisted(() => ({
  openTutorSession: vi.fn(),
  chatWithFallback: vi.fn(),
  askErrorCopy: vi.fn(() => "Couldn't ask."),
  turnPauseOf: vi.fn(() => null),
  ABORTED: Symbol("aborted"),
}));
vi.mock("./askTurn", () => askTurn);

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, newTurnId: () => "turn-guide-1" };
});

const GUIDE = {
  id: "g1",
  title: "Recursion prep",
  course_id: "course-cs101",
  course_name: "CS",
  course_code: "CS101",
  semester: null,
  scope_kind: "course" as const,
  scope_label: "Whole course",
  goal: "exam_prep" as const,
  depth: "standard" as const,
  status: "ready" as const,
  generated_at: null,
  created_at: "2026-01-01",
  saved_at: null,
  new_materials: 0,
  bars: [],
  counts: { sections: 1, blocks: 1, practice: 0, minutes: 5 },
};

describe("composeGuideAskMessage", () => {
  it("names the concept and never includes a quiz answer key", () => {
    const msg = composeGuideAskMessage("Recursion", "What is a base case?");
    expect(msg).toContain("Recursion");
    expect(msg).toContain("What is a base case?");
    expect(msg).toMatch(/not the answer/i);
    expect(msg).not.toMatch(/correct answer|you chose|explanation given/i);
  });
});

describe("guidesForCourse", () => {
  it("keeps only this course's cards", () => {
    const other = { ...GUIDE, id: "g2", course_id: "other" };
    expect(guidesForCourse([GUIDE, other], "course-cs101")).toEqual([GUIDE]);
    expect(guidesForCourse([GUIDE], null)).toEqual([]);
  });
});

describe("StudyGuideDrawer", () => {
  beforeEach(() => {
    listGuides.mockReset();
    listGuides.mockResolvedValue({ guides: [GUIDE, { ...GUIDE, id: "g2", course_id: "other" }] });
    askTurn.openTutorSession.mockReset();
    askTurn.chatWithFallback.mockReset();
  });
  afterEach(() => {
    cleanup();
    __resetScrollLocksForTests();
  });

  it("lists course guide cards and deep-links without loading answer keys", async () => {
    render(
      <StudyGuideDrawer
        open
        onClose={() => {}}
        userId="user-1"
        conceptName="Recursion"
        courseId="course-cs101"
        courseLabel="CS101"
      />,
    );
    expect(screen.getByTestId("quiz-guide-drawer")).toHaveAttribute("data-testid", "quiz-guide-drawer");
    expect(screen.getByText(/Answer keys stay hidden/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("quiz-guide-list")).toBeInTheDocument());
    expect(screen.getByTestId("quiz-guide-card-g1")).toHaveAttribute("href", "/study/guide/g1");
    expect(screen.queryByTestId("quiz-guide-card-g2")).not.toBeInTheDocument();
    expect(listGuides).toHaveBeenCalledWith("user-1");
    // Scaffold never asks for guide detail (answer-bearing).
    expect(screen.queryByText(/correct_id|The answer is/i)).not.toBeInTheDocument();
  });

  it("sends a concept-only Ask via guide_ask (AskPanel pattern, no quiz seed)", async () => {
    askTurn.openTutorSession.mockResolvedValue("sess-1");
    askTurn.chatWithFallback.mockResolvedValue("A base case stops the recursion.");
    render(
      <StudyGuideDrawer
        open
        onClose={() => {}}
        userId="user-1"
        conceptName="Recursion"
        courseId="course-cs101"
      />,
    );
    fireEvent.change(screen.getByTestId("quiz-guide-ask-input"), {
      target: { value: "Remind me what a base case is" },
    });
    fireEvent.click(screen.getByTestId("quiz-guide-ask-send"));
    await waitFor(() => expect(askTurn.openTutorSession).toHaveBeenCalled());
    expect(askTurn.openTutorSession).toHaveBeenCalledWith(
      "user-1",
      "Recursion",
      "course-cs101",
      expect.any(AbortSignal),
      { guide: true },
    );
    await waitFor(() => expect(askTurn.chatWithFallback).toHaveBeenCalled());
    const args = askTurn.chatWithFallback.mock.calls[0][0];
    expect(args.message).toMatch(/not the answer to the current question/i);
    expect(args.message).not.toMatch(/The correct answer is/i);
  });
});
