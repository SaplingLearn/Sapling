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
import { beforeEach, describe, it, expect, vi, afterEach } from "vitest";
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
  CustomSelect: ({
    value,
    options,
    ariaLabel,
  }: {
    value?: string;
    options?: { value: string; label: string }[];
    ariaLabel?: string;
  }) => (
    // Expose the option values so tests can assert what the panel would
    // actually offer (the #540 config-driven lists), not just the selection.
    <div
      data-testid="custom-select"
      aria-label={ariaLabel}
      data-options={(options ?? []).map(o => o.value).join(",")}
    >
      {value}
    </div>
  ),
}));

vi.mock("@/lib/api", () => ({
  generateQuiz: vi.fn(),
  submitQuiz: vi.fn(),
  fetchQuizConfig: vi.fn(),
}));

import { fetchQuizConfig, generateQuiz } from "@/lib/api";
import { QuizPanel } from "./QuizPanel";

const mockGenerateQuiz = vi.mocked(generateQuiz);
const mockFetchQuizConfig = vi.mocked(fetchQuizConfig);

beforeEach(() => {
  // Default: config unavailable → the panel exercises its static fallback
  // lists. The config-driven test overrides this per-test (#540 A2).
  mockFetchQuizConfig.mockRejectedValue(new Error("offline"));
});

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

describe("QuizPanel — config-driven selectors (#540 A2)", () => {
  it("builds the count and difficulty selects from the fetched config", async () => {
    // Non-default values so a fallback-list render can't accidentally pass.
    mockFetchQuizConfig.mockResolvedValue({
      num_questions: { min: 1, max: 10, options: [2, 4] },
      difficulties: ["easy", "adaptive"],
      question_types: ["multiple_choice"],
    });
    renderPanel();

    await waitFor(() => expect(mockFetchQuizConfig).toHaveBeenCalledTimes(1));
    const counts = await screen.findByLabelText("Number of questions");
    await waitFor(() => expect(counts).toHaveAttribute("data-options", "2,4"));
    expect(screen.getByLabelText("Difficulty")).toHaveAttribute(
      "data-options",
      "easy,adaptive",
    );
  });

  it("falls back to the static mirror when the config fetch fails", async () => {
    // beforeEach already rejects the fetch.
    renderPanel();
    await waitFor(() => expect(mockFetchQuizConfig).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText("Number of questions")).toHaveAttribute(
      "data-options",
      "3,5,10",
    );
    expect(screen.getByLabelText("Difficulty")).toHaveAttribute(
      "data-options",
      "easy,medium,hard,adaptive",
    );
  });
});
