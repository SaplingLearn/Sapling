// @vitest-environment jsdom
/**
 * The states QuizQuestion.test.tsx doesn't walk through one by one: the
 * grounding line, every verdict-line wording, at-end's reveal rules, the
 * footer button while scoring, the pager, the keyboard edges and the seed
 * the tutor sheet is opened with. AskPanel is stubbed here (its own flow is
 * covered in QuizQuestion.test.tsx) so its props can be read directly.
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

const askProps = vi.hoisted(() => ({ last: null as null | Record<string, unknown> }));
vi.mock("./AskPanel", () => ({
  AskPanel: (props: Record<string, unknown>) => {
    askProps.last = props;
    return props.open ? <div data-testid="ask-stub" /> : null;
  },
}));

const CONCEPT: QuizConceptSummary = {
  id: "node-recursion",
  name: "Recursion",
  courseCode: "CS101",
  color: "#7b4b99",
  tier: "struggling",
  mastery: 0.29,
};

function question(id: number, over: Partial<WireQuestion> = {}): WireQuestion {
  return {
    id,
    question: `What is a base case? (${id})`,
    options: [
      { label: "A", text: "Caching" },
      { label: "B", text: "The exit" },
      { label: "C", text: "More depth" },
      { label: "D", text: "A loop" },
    ],
    difficulty: "medium",
    ...over,
  };
}

function item(index: number, over: Partial<QuizItem> = {}): QuizItem {
  return { index, question: question(index + 1), selectedIndex: null, verdict: null, flagged: false, ...over };
}

function written(type: "short_answer" | "numeric" | "symbolic", over: Partial<QuizItem> = {}): QuizItem {
  return item(0, { question: question(1, { type, options: [] }), ...over });
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
    goTo: vi.fn(),
  };
}

function renderScreen(
  session: QuizSession,
  { actions = makeActions(), pending, concept = CONCEPT }: { actions?: QuizActions; pending?: boolean; concept?: QuizConceptSummary } = {},
) {
  const view = render(
    <QuizQuestion
      session={session}
      actions={actions}
      config={null}
      concept={concept}
      userId="user-1"
      courseId="course-cs101"
      pending={pending}
    />,
  );
  return { ...view, actions };
}

const root = () => screen.getByTestId("quiz-panel");
const feedback = () => screen.getByTestId("quiz-review-verdict");
const atEnd = { count: 3, difficulty: "medium", feedback: "at-end" as const };
const wrongB = { isCorrect: false, correctIndex: 1, explanation: "The base case ends it." };
const rightB = { isCorrect: true, correctIndex: 1, explanation: "" };

beforeEach(() => {
  vi.clearAllMocks();
  askProps.last = null;
});

afterEach(cleanup);

describe("QuizQuestion — header and grounding", () => {
  it.each([
    ["course_material", "Course material provided for this question"],
    ["catalog", "Course catalog context provided"],
    ["general", "General practice: no matching course material was found"],
  ] as const)("says where a %s question came from", (kind, text) => {
    renderScreen(makeSession({ items: [item(0, { question: question(1, { material_context: kind }) })] }));
    expect(screen.getByTestId("quiz-material-context")).toHaveTextContent(text);
  });

  it("says nothing about grounding when the question carries none", () => {
    renderScreen(makeSession());
    expect(screen.queryByTestId("quiz-material-context")).toBeNull();
  });

  it("names the concept alone when there is no course code, and drops a blank difficulty", () => {
    renderScreen(
      makeSession({
        config: { count: 3, difficulty: "", feedback: "as-you-go" },
        items: [item(0, { question: question(1, { difficulty: "" }) })],
      }),
      { concept: { ...CONCEPT, courseCode: "", color: "" } },
    );
    expect(screen.getByText("Recursion")).toHaveClass("quiz-question__concept");
    expect(document.querySelector(".quiz-question__header .badge")).toBeNull();
    expect(screen.queryByText("MEDIUM")).toBeNull();
  });

  it("shows the question's own difficulty over the quiz's", () => {
    renderScreen(makeSession({ items: [item(0, { question: question(1, { difficulty: "hard" }) })] }));
    expect(screen.getByText("HARD")).toBeInTheDocument();
  });

  it("answers a type it doesn't know by choosing, tagged as multiple choice", () => {
    const type = "true_false" as WireQuestion["type"];
    renderScreen(makeSession({ items: [item(0, { question: question(1, { type }) })] }));
    const tag = screen.getByTestId("quiz-format-tag");
    expect(tag).toHaveAttribute("data-format", "multiple_choice");
    expect(tag).toHaveTextContent("Multiple choice");
    expect(screen.getByTestId("quiz-answer-options")).toBeInTheDocument();
    expect(screen.getByText(/Keyboard: press A to F/)).toBeInTheDocument();
  });
});

describe("QuizQuestion — generating", () => {
  it("states the length, concept and difficulty, with no format tag yet", () => {
    renderScreen(makeSession({ phase: "generating", items: [], attemptId: null }));
    expect(screen.getByText("3 questions on Recursion · medium")).toBeInTheDocument();
    expect(screen.getByText("Still writing. Longer quizzes take a little more time.")).toBeInTheDocument();
    expect(screen.queryByTestId("quiz-format-tag")).toBeNull();
    expect(screen.queryByTestId("quiz-panel")).toBeNull();
    expect(screen.getByTestId("quiz-progress")).toHaveAttribute("aria-label", "Question 1 of 3");
    expect(screen.getByTestId("quiz-prev-question")).toBeDisabled();
    expect(screen.getByTestId("quiz-next-question")).toBeDisabled();
  });

  it("leaves the difficulty out of the status when there is none", () => {
    renderScreen(
      makeSession({ phase: "generating", items: [], attemptId: null, config: { count: 5, difficulty: "", feedback: "as-you-go" } }),
    );
    expect(screen.getByText("5 questions on Recursion")).toBeInTheDocument();
  });
});

describe("QuizQuestion — every verdict line", () => {
  it("says only 'Not quite.' when there is neither a key nor a correct option", () => {
    renderScreen(
      makeSession({
        phase: "answered",
        items: [item(0, { selectedIndex: 2, verdict: { isCorrect: false, correctIndex: -1, explanation: "" } }), item(1), item(2)],
      }),
    );
    expect(feedback().querySelector(".quiz-question__verdict-line")).toHaveTextContent(/^Not quite\.$/);
    expect(feedback().querySelector(".quiz-question__explanation")).toBeNull();
    expect(screen.getByTestId("quiz-answer-option-C").className).toContain("answer-option--chosen-wrong");
  });

  it("prefers the expected answer over the letter on a multiple-choice miss", () => {
    renderScreen(
      makeSession({
        phase: "answered",
        items: [item(0, { selectedIndex: 2, verdict: { ...wrongB, correctAnswer: "The exit" } }), item(1), item(2)],
      }),
    );
    expect(feedback()).toHaveTextContent("Not quite — the expected answer is The exit.");
  });

  it("shows a correct answer's explanation alone in the card", () => {
    renderScreen(
      makeSession({
        phase: "answered",
        items: [item(0, { selectedIndex: 1, verdict: { ...rightB, explanation: "Yes." } }), item(1), item(2)],
      }),
    );
    expect(screen.getByTestId("quiz-verdict-outcome")).toHaveTextContent("Correct.");
    expect(feedback().querySelector(".quiz-question__verdict-line")).toBeNull();
    expect(feedback().querySelector(".quiz-question__verdict-card")).toHaveTextContent("Yes.");
    expect(screen.getByTestId("quiz-answer-option-B").className).toContain("answer-option--correct");
  });

  it("has no card at all for a correct answer with nothing to explain", () => {
    renderScreen(makeSession({ phase: "answered", items: [item(0, { selectedIndex: 1, verdict: rightB }), item(1), item(2)] }));
    expect(feedback()).toHaveAttribute("data-outcome", "correct");
    expect(feedback().querySelector(".card")).toBeNull();
    expect(screen.getByTestId("quiz-answer-option-B").querySelector(".answer-option__status")).toHaveTextContent("Correct");
  });

  it("typesets an algebra key and drops one trailing full stop from it", () => {
    renderScreen(
      makeSession({
        phase: "answered",
        config: { count: 1, difficulty: "easy", feedback: "as-you-go" },
        items: [written("symbolic", { answerText: "x", verdict: { isCorrect: false, correctIndex: -1, explanation: "", correctAnswer: " x^2 + 1. " } })],
      }),
    );
    const line = feedback().querySelector(".quiz-question__verdict-line")!;
    expect(line).toHaveTextContent("Not quite — the expected answer is x2 + 1.");
    expect(line.querySelector(".quiz-question__verdict-expr sup")).toHaveTextContent("2");
    expect(document.querySelector(".quiz-question__written")).toHaveClass("quiz-question__written--symbolic");
    expect(document.querySelector(".quiz-written")).toHaveAttribute("data-verdict", "incorrect");
  });
});

describe("QuizQuestion — at-end reveal rules", () => {
  it("reveals on the last question once every one is answered", () => {
    renderScreen(
      makeSession({
        config: atEnd,
        phase: "answered",
        cursor: 2,
        items: [
          item(0, { selectedIndex: 1, verdict: rightB }),
          item(1, { selectedIndex: 1, verdict: rightB }),
          item(2, { selectedIndex: 2, verdict: wrongB }),
        ],
      }),
    );
    expect(feedback()).toHaveAttribute("data-outcome", "incorrect");
    expect(feedback()).toHaveTextContent("Not quite — the answer is B.");
    expect(screen.getByTestId("quiz-next")).toHaveTextContent("See results");
    expect(document.activeElement).toBe(feedback());
  });

  it("holds the verdict back on the last question while another is unanswered", () => {
    renderScreen(
      makeSession({
        config: atEnd,
        phase: "answered",
        cursor: 2,
        items: [item(0), item(1, { selectedIndex: 1, verdict: wrongB }), item(2, { selectedIndex: 2, verdict: wrongB })],
      }),
    );
    expect(feedback()).not.toHaveAttribute("data-outcome");
    expect(feedback()).toHaveTextContent("");
    expect(screen.getByTestId("quiz-next")).toHaveTextContent("Next");
  });

  it("lets a revisited, recorded question move on with Next, revealing nothing", () => {
    const { actions } = renderScreen(
      makeSession({ config: atEnd, phase: "answered", items: [item(0, { selectedIndex: 2, verdict: wrongB }), item(1), item(2)] }),
    );
    const next = screen.getByTestId("quiz-next");
    expect(next).toBeEnabled();
    expect(next).toHaveTextContent("Next");
    expect(screen.getByTestId("quiz-answer-option-C").className).toContain("answer-option--selected");
    expect(screen.getByTestId("quiz-answer-option-C").querySelector(".answer-option__status")).toBeNull();
    fireEvent.click(next);
    expect(actions.next).toHaveBeenCalledOnce();
  });

  it("keeps a written answer unmarked until the reveal", () => {
    renderScreen(
      makeSession({
        config: atEnd,
        phase: "answered",
        items: [written("numeric", { answerText: "2", verdict: { isCorrect: false, correctIndex: -1, explanation: "x" } }), item(1), item(2)],
      }),
    );
    expect(document.querySelector(".quiz-question__written")).not.toHaveAttribute("data-marked");
    expect(document.querySelector(".quiz-written")).not.toHaveAttribute("data-verdict");
  });
});

describe("QuizQuestion — the footer while scoring", () => {
  it("keeps Next's identity when the press that started scoring was Next", () => {
    renderScreen(
      makeSession({
        phase: "submitting",
        cursor: 2,
        items: [
          item(0, { selectedIndex: 1, verdict: rightB }),
          item(1, { selectedIndex: 1, verdict: rightB }),
          item(2, { selectedIndex: 2, verdict: wrongB }),
        ],
      }),
    );
    const button = screen.getByTestId("quiz-next");
    expect(button).toHaveTextContent("Scoring…");
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByTestId("quiz-submit-answer")).toBeNull();
  });

  it("keeps Submit's identity on the last at-end question", () => {
    renderScreen(makeSession({ phase: "submitting", config: atEnd, cursor: 2, items: [item(0), item(1), item(2, { selectedIndex: 2 })] }));
    expect(screen.getByTestId("quiz-submit-answer")).toHaveTextContent("Scoring…");
  });

  it("ignores Escape and the pager while scoring", () => {
    const { actions } = renderScreen(makeSession({ phase: "submitting", cursor: 1 }));
    fireEvent.keyDown(root(), { key: "Escape" });
    fireEvent.click(screen.getByTestId("quiz-prev-question"));
    expect(actions.requestLeave).not.toHaveBeenCalled();
    expect(actions.goTo).not.toHaveBeenCalled();
    expect(screen.getByTestId("quiz-prev-question")).toBeDisabled();
  });
});

describe("QuizQuestion — the pager", () => {
  it("steps back and forward through goTo, and stops at the ends", () => {
    const { actions, rerender } = renderScreen(makeSession({ cursor: 1 }));
    fireEvent.click(screen.getByTestId("quiz-prev-question"));
    expect(actions.goTo).toHaveBeenLastCalledWith(0);
    fireEvent.click(screen.getByTestId("quiz-next-question"));
    expect(actions.goTo).toHaveBeenLastCalledWith(2);

    rerender(<QuizQuestion session={makeSession({ cursor: 0 })} actions={actions} config={null} concept={CONCEPT} userId="user-1" courseId="course-cs101" />);
    expect(screen.getByTestId("quiz-prev-question")).toBeDisabled();
    expect(screen.getByTestId("quiz-next-question")).toBeEnabled();

    rerender(<QuizQuestion session={makeSession({ cursor: 2 })} actions={actions} config={null} concept={CONCEPT} userId="user-1" courseId="course-cs101" />);
    expect(screen.getByTestId("quiz-next-question")).toBeDisabled();
  });

  it("jumps from a dot, but not to the question already open", () => {
    const { actions } = renderScreen(makeSession({ cursor: 1 }));
    const dots = document.querySelectorAll(".progress-dots__dot");
    fireEvent.click(dots[1]);
    expect(actions.goTo).not.toHaveBeenCalled();
    fireEvent.click(dots[2]);
    expect(actions.goTo).toHaveBeenCalledWith(2);
  });

  it("is frozen while a call is in flight", () => {
    const { actions } = renderScreen(makeSession({ cursor: 1 }), { pending: true });
    expect(screen.getByTestId("quiz-prev-question")).toBeDisabled();
    expect(screen.getByTestId("quiz-next-question")).toBeDisabled();
    fireEvent.click(document.querySelectorAll(".progress-dots__dot")[2]);
    expect(actions.goTo).not.toHaveBeenCalled();
  });
});

describe("QuizQuestion — keyboard edges", () => {
  it("focuses the screen root on a multiple-choice question", () => {
    renderScreen(makeSession());
    expect(document.activeElement).toBe(root());
  });

  it("ignores a shortcut held with a modifier", () => {
    const { actions } = renderScreen(makeSession({ items: [item(0, { selectedIndex: 1 }), item(1), item(2)] }));
    fireEvent.keyDown(root(), { key: "a", metaKey: true });
    fireEvent.keyDown(root(), { key: "Enter", ctrlKey: true });
    fireEvent.keyDown(root(), { key: "Escape", altKey: true });
    expect(actions.select).not.toHaveBeenCalled();
    expect(actions.submitAnswer).not.toHaveBeenCalled();
    expect(actions.requestLeave).not.toHaveBeenCalled();
  });

  it("starts the arrows from the edge when nothing is chosen, and moves focus with them", () => {
    const { actions } = renderScreen(makeSession());
    const options = screen.getByTestId("quiz-answer-options");
    fireEvent.keyDown(options, { key: "ArrowUp" });
    expect(actions.select).toHaveBeenLastCalledWith(3);
    expect(document.activeElement).toBe(screen.getByTestId("quiz-answer-option-D"));
    fireEvent.keyDown(options, { key: "ArrowRight" });
    expect(actions.select).toHaveBeenLastCalledWith(0);
    expect(document.activeElement).toBe(screen.getByTestId("quiz-answer-option-A"));
    // Any other key on the group is not a move.
    actions.select = vi.fn();
    expect(fireEvent.keyDown(options, { key: "Home" })).toBe(true);
  });

  it("does not move the selection once the answer is recorded", () => {
    const { actions } = renderScreen(
      makeSession({ phase: "answered", items: [item(0, { selectedIndex: 2, verdict: wrongB }), item(1), item(2)] }),
    );
    fireEvent.keyDown(screen.getByTestId("quiz-answer-options"), { key: "ArrowDown" });
    fireEvent.keyDown(root(), { key: "a" });
    expect(actions.select).not.toHaveBeenCalled();
    fireEvent.keyDown(root(), { key: "Escape" });
    expect(actions.requestLeave).toHaveBeenCalledOnce();
  });

  it("leaves Escape and letters to a focused written answer", () => {
    const { actions } = renderScreen(makeSession({ items: [written("short_answer", { answerText: "x" })] }));
    const input = screen.getByTestId("quiz-written-answer");
    fireEvent.keyDown(input, { key: "Escape" });
    fireEvent.keyDown(input, { key: "b" });
    expect(actions.requestLeave).not.toHaveBeenCalled();
    expect(actions.select).not.toHaveBeenCalled();
  });

  it("moves on with Enter in a marked written answer", () => {
    const { actions } = renderScreen(
      makeSession({
        phase: "answered",
        items: [written("numeric", { answerText: "2", verdict: { isCorrect: true, correctIndex: -1, explanation: "" } }), item(1), item(2)],
      }),
    );
    expect(screen.getByTestId("quiz-written-answer")).toBeDisabled();
    fireEvent.keyDown(screen.getByTestId("quiz-written-answer"), { key: "Enter" });
    expect(actions.next).toHaveBeenCalledOnce();
  });

  it("doesn't submit a written answer that is only spaces", () => {
    const { actions } = renderScreen(makeSession({ items: [written("short_answer", { answerText: "   " })] }));
    expect(screen.getByTestId("quiz-submit-answer")).toBeDisabled();
    fireEvent.keyDown(screen.getByTestId("quiz-written-answer"), { key: "Enter" });
    expect(actions.submitAnswer).not.toHaveBeenCalled();
  });
});

describe("QuizQuestion — flag and toast edges", () => {
  it("un-flags silently", () => {
    const { actions } = renderScreen(makeSession({ items: [item(0, { flagged: true }), item(1), item(2)] }));
    fireEvent.click(screen.getByTestId("quiz-flag"));
    expect(actions.flag).toHaveBeenCalledOnce();
    expect(toastApi.show).not.toHaveBeenCalled();
  });

  it("says nothing about a short quiz before it has an attempt", () => {
    renderScreen(makeSession({ deliveredShort: true, attemptId: null, items: [item(0), item(1)] }));
    expect(toastApi.show).not.toHaveBeenCalled();
  });
});

describe("QuizQuestion — the seed handed to the tutor", () => {
  it("seeds a multiple-choice miss with both letters and texts", () => {
    renderScreen(makeSession({ phase: "answered", items: [item(0, { selectedIndex: 2, verdict: wrongB }), item(1), item(2)] }));
    expect(askProps.last).toMatchObject({
      open: false,
      userId: "user-1",
      conceptName: "Recursion",
      courseId: "course-cs101",
      courseLabel: "CS101",
      seed: {
        stem: "What is a base case? (1)",
        chosenLabel: "C",
        chosenText: "More depth",
        correctLabel: "B",
        correctText: "The exit",
        explanation: "The base case ends it.",
        written: false,
      },
    });
    fireEvent.click(screen.getByTestId("quiz-ask"));
    expect(askProps.last).toMatchObject({ open: true });
    expect(screen.getByTestId("ask-stub")).toBeInTheDocument();
  });

  it("seeds a written miss with what was typed and the expected answer", () => {
    renderScreen(
      makeSession({
        phase: "answered",
        items: [written("short_answer", { answerText: "loop", verdict: { isCorrect: false, correctIndex: -1, explanation: "", correctAnswer: "base case" } }), item(1), item(2)],
      }),
      { concept: { ...CONCEPT, courseCode: "" } },
    );
    expect(askProps.last).toMatchObject({
      courseLabel: undefined,
      seed: { chosenLabel: "—", chosenText: "loop", correctLabel: "—", correctText: "base case", explanation: "", written: true },
    });
  });

  it("seeds 'nothing' and blanks before an answer exists", () => {
    renderScreen(makeSession());
    expect(askProps.last).toMatchObject({
      seed: { chosenLabel: "—", chosenText: "nothing", correctLabel: "—", correctText: "", explanation: "", written: false },
    });
  });

  it("closes the sheet when a different question opens", () => {
    const actions = makeActions();
    const answered = makeSession({ phase: "answered", items: [item(0, { selectedIndex: 2, verdict: wrongB }), item(1), item(2)] });
    const { rerender } = renderScreen(answered, { actions });
    fireEvent.click(screen.getByTestId("quiz-ask"));
    expect(askProps.last).toMatchObject({ open: true });
    rerender(<QuizQuestion session={{ ...answered, phase: "active", cursor: 1 }} actions={actions} config={null} concept={CONCEPT} userId="user-1" courseId="course-cs101" />);
    expect(askProps.last).toMatchObject({ open: false });
  });
});
