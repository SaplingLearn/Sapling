// @vitest-environment jsdom
/**
 * Component tests for QuizPanel's start() flow (#184).
 *
 * Bug: start() did `setQuestions(res.questions || [])` then advanced to the
 * "active" phase unconditionally. The active branch is gated on
 * `currentQuestion`, and quiz-exit lives inside it — so a response with zero
 * questions rendered a blank, control-less quiz-panel and stranded the user.
 *
 * Fix under test: when generateQuiz returns no questions, warn via toast and
 * STAY in the select phase (quiz-start/quiz-cancel remain usable).
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

// Captured toast spies — hoisted so the vi.mock factory can close over them.
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warn: vi.fn(),
}));

vi.mock("./ToastProvider", () => ({
  useToast: () => toast,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

// The select-phase pickers aren't under test; initialConceptId preselects the
// course + concept (via the real quizSelection helpers), so a passive stub is
// enough and keeps the DOM simple.
vi.mock("./CustomSelect", () => ({
  CustomSelect: ({ value }: { value?: string }) => (
    <div data-testid="custom-select">{value}</div>
  ),
}));

vi.mock("@/lib/api", () => ({
  generateQuiz: vi.fn(),
  submitQuiz: vi.fn(),
}));

import { generateQuiz } from "@/lib/api";
import { QuizPanel } from "./QuizPanel";

const mockGenerateQuiz = vi.mocked(generateQuiz);

const CONCEPTS = [
  { id: "c1", name: "Gradient Descent", course_id: "course-1", course_code: "CS101" },
];

const COURSES = [
  { course_id: "course-1", course_code: "CS101", course_name: "Intro to ML" },
];

const QUESTION = {
  id: 1,
  question: "What does gradient descent minimize?",
  options: [
    { label: "A", text: "The loss function", correct: true },
    { label: "B", text: "The learning rate", correct: false },
  ],
  explanation: "It steps against the gradient of the loss.",
  concept_tested: "Gradient Descent",
  difficulty: "easy",
};

const renderPanel = () =>
  render(
    <QuizPanel
      userId="u1"
      concepts={CONCEPTS}
      courses={COURSES}
      initialConceptId="c1"
      onExit={vi.fn()}
    />,
  );

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("QuizPanel — start() with no questions (#184)", () => {
  // The declared wire type marks `questions` required, but the component's
  // `res.questions || []` guard exists because the payload may omit it — the
  // cast lets the test cover that runtime shape.
  type QuizResponse = Awaited<ReturnType<typeof generateQuiz>>;
  it.each([
    ["an empty questions array", { quiz_id: "quiz-1", questions: [] }],
    ["a missing questions field", { quiz_id: "quiz-1" }],
  ])("stays in the select phase and warns on %s", async (_name, response) => {
    mockGenerateQuiz.mockResolvedValue(response as QuizResponse);
    renderPanel();

    fireEvent.click(screen.getByTestId("quiz-start"));
    await waitFor(() => expect(mockGenerateQuiz).toHaveBeenCalledTimes(1));

    // The user is told why nothing happened…
    await waitFor(() => expect(toast.warn).toHaveBeenCalledTimes(1));

    // …and keeps the select-phase controls instead of a blank active panel.
    expect(screen.getByTestId("quiz-start")).toBeInTheDocument();
    expect(screen.getByTestId("quiz-cancel")).toBeInTheDocument();
    expect(screen.queryByTestId("quiz-answer-options")).toBeNull();
    expect(screen.queryByTestId("quiz-exit")).toBeNull();
  });
});

describe("QuizPanel — start() happy path", () => {
  it("advances to the active phase when questions come back", async () => {
    mockGenerateQuiz.mockResolvedValue({ quiz_id: "quiz-1", questions: [QUESTION] });
    renderPanel();

    fireEvent.click(screen.getByTestId("quiz-start"));

    expect(await screen.findByTestId("quiz-answer-options")).toBeInTheDocument();
    expect(mockGenerateQuiz).toHaveBeenCalledWith("u1", "c1", 5, "medium");

    // Select phase is gone; the active phase carries its own exit control.
    expect(screen.queryByTestId("quiz-start")).toBeNull();
    expect(screen.getByTestId("quiz-exit")).toBeInTheDocument();
    expect(toast.warn).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });
});
