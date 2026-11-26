// @vitest-environment jsdom
/**
 * W7.5: Hint / Skip / Study guide slot enabled vs disabled states on the
 * question action bar.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import type { QuizItem, QuizSession, WireQuestion } from "@/lib/quiz/types";
import { QuizQuestion, type QuizConceptSummary } from "./QuizQuestion";

const toastApi = vi.hoisted(() => ({
  show: vi.fn(),
  dismiss: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  warn: vi.fn(),
}));
vi.mock("@/components/ToastProvider", () => ({ useToast: () => toastApi }));

vi.mock("./AskPanel", () => ({
  AskPanel: () => null,
}));

vi.mock("./StudyGuideDrawer", () => ({
  StudyGuideDrawer: (props: { open: boolean }) =>
    props.open ? <div data-testid="guide-drawer-stub" /> : null,
}));

const CONCEPT: QuizConceptSummary = {
  id: "node-recursion",
  name: "Recursion",
  courseCode: "CS101",
  color: "#7b4b99",
  tier: "struggling",
  mastery: 0.29,
};

function question(id: number): WireQuestion {
  return {
    id,
    question: `Q${id}`,
    options: [
      { label: "A", text: "a" },
      { label: "B", text: "b" },
      { label: "C", text: "c" },
      { label: "D", text: "d" },
    ],
    difficulty: "medium",
  };
}

function item(index: number, over: Partial<QuizItem> = {}): QuizItem {
  return {
    index,
    question: question(index + 1),
    selectedIndex: null,
    verdict: null,
    flagged: false,
    ...over,
  };
}

function makeSession(over: Partial<QuizSession> = {}): QuizSession {
  return {
    intent: "practice",
    scope: { kind: "concept", conceptId: CONCEPT.id },
    source: { kind: "nav" },
    config: { count: 3, difficulty: "medium", feedback: "as-you-go" },
    conceptId: CONCEPT.id,
    courseId: "course-cs101",
    attemptId: "attempt-1",
    items: [item(0), item(1), item(2)],
    cursor: 0,
    queueIndex: 0,
    phase: "active",
    error: null,
    result: null,
    xp: null,
    deliveredShort: false,
    sourceAttemptId: null,
    reserved: null,
    prereq: null,
    ...over,
  };
}

function makeActions(): QuizActions {
  return {
    configure: vi.fn(),
    setConfig: vi.fn(),
    start: vi.fn(),
    select: vi.fn(),
    write: vi.fn(),
    submitAnswer: vi.fn(),
    next: vi.fn(),
    goTo: vi.fn(),
    finish: vi.fn(),
    requestLeave: vi.fn(),
    cancelLeave: vi.fn(),
    confirmLeave: vi.fn(),
    resume: vi.fn(),
    practiseMissed: vi.fn(),
    nextInQueue: vi.fn(),
    exit: vi.fn(),
    cancel: vi.fn(),
    flag: vi.fn(),
    dismissError: vi.fn(),
    retry: vi.fn(),
  };
}

function renderScreen(session: QuizSession, actions = makeActions()) {
  return {
    actions,
    ...render(
      <QuizQuestion
        session={session}
        actions={actions}
        config={null}
        concept={CONCEPT}
        userId="user-1"
        courseId="course-cs101"
      />,
    ),
  };
}

describe("W7.5 action-bar slots", () => {
  beforeEach(() => {
    toastApi.show.mockReset();
  });
  afterEach(cleanup);

  it("opens Bastani-lite ladder without naming the answer", () => {
    renderScreen(makeSession());
    const hint = screen.getByTestId("quiz-hint-slot");
    expect(hint).not.toBeDisabled();
    expect(hint).toHaveAttribute("title", expect.stringMatching(/scaffolding/i));
    expect(screen.queryByTestId("quiz-hint-panel")).not.toBeInTheDocument();

    fireEvent.click(hint);
    const panel = screen.getByTestId("quiz-hint-panel");
    expect(screen.getByTestId("quiz-hint-rung-H0")).toHaveTextContent(/Stay with Recursion/i);
    expect(screen.queryByTestId("quiz-hint-rung-H1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("quiz-hint-rung-H2")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("quiz-hint-more"));
    expect(screen.getByTestId("quiz-hint-rung-H2")).toHaveTextContent(/never the answer/i);
    expect(panel).not.toHaveTextContent(/\b(a|b|c|d)\b.*correct/i);

    fireEvent.click(screen.getByTestId("quiz-hint-open-guide"));
    expect(screen.getByTestId("guide-drawer-stub")).toBeInTheDocument();
    expect(screen.queryByTestId("quiz-hint-panel")).not.toBeInTheDocument();
  });

  it("surfaces written format rules on the H1 rung", () => {
    renderScreen(
      makeSession({
        items: [
          item(0, {
            question: {
              id: 1,
              question: "Compute",
              options: [],
              difficulty: "medium",
              type: "numeric",
              concept_tested: "Derivatives",
            },
          }),
          item(1),
          item(2),
        ],
      }),
    );
    fireEvent.click(screen.getByTestId("quiz-hint-slot"));
    expect(screen.getByTestId("quiz-hint-rung-H0")).toHaveTextContent(/Stay with Derivatives/i);
    fireEvent.click(screen.getByTestId("quiz-hint-more"));
    expect(screen.getByTestId("quiz-hint-rung-H1")).toHaveTextContent(/Enter only the number/);
  });

  it("shows a soft Exam Twin countdown that never auto-submits", () => {
    renderScreen(
      makeSession({
        config: { count: 3, difficulty: "medium", feedback: "as-you-go", sessionMode: "exam_twin" },
      }),
    );
    const timer = screen.getByTestId("quiz-exam-timer");
    expect(timer).toHaveTextContent(/^\d+:\d{2}$/);
    expect(timer).toHaveAttribute("title", expect.stringMatching(/does not auto-submit/i));
  });

  it("disables Hint in Exam Twin", () => {
    renderScreen(
      makeSession({
        config: { count: 3, difficulty: "medium", feedback: "as-you-go", sessionMode: "exam_twin" },
      }),
    );
    const hint = screen.getByTestId("quiz-hint-slot");
    expect(hint).toBeDisabled();
    expect(hint).toHaveAttribute("title", expect.stringMatching(/Exam Twin/i));
    fireEvent.click(hint);
    expect(screen.queryByTestId("quiz-hint-panel")).not.toBeInTheDocument();
  });

  it("enables Skip and advances without answering (no mastery path)", () => {
    const { actions } = renderScreen(makeSession({ cursor: 0 }));
    const skip = screen.getByTestId("quiz-skip-slot");
    expect(skip).not.toBeDisabled();
    expect(skip).toHaveAttribute("title", expect.stringMatching(/no mastery/i));
    fireEvent.click(skip);
    expect(actions.goTo).toHaveBeenCalledWith(1);
  });

  it("disables Skip on the last question with an honest reason", () => {
    const { actions } = renderScreen(makeSession({ cursor: 2 }));
    const skip = screen.getByTestId("quiz-skip-slot");
    expect(skip).toBeDisabled();
    expect(skip).toHaveAttribute("title", expect.stringMatching(/last question/i));
    fireEvent.click(skip);
    expect(actions.goTo).not.toHaveBeenCalled();
  });

  it("disables Skip after a verdict", () => {
    renderScreen(
      makeSession({
        phase: "answered",
        items: [
          item(0, { selectedIndex: 1, verdict: { isCorrect: true, correctIndex: 1, explanation: "" } }),
          item(1),
          item(2),
        ],
      }),
    );
    const skip = screen.getByTestId("quiz-skip-slot");
    expect(skip).toBeDisabled();
    expect(skip).toHaveAttribute("title", expect.stringMatching(/Already answered/i));
  });

  it("opens the study-guide drawer from the Study guide slot", () => {
    renderScreen(makeSession());
    expect(screen.queryByTestId("guide-drawer-stub")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("quiz-guide-slot"));
    expect(screen.getByTestId("guide-drawer-stub")).toBeInTheDocument();
  });
});
