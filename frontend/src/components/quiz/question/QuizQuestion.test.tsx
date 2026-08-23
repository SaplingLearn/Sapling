// @vitest-environment jsdom
/**
 * What this screen has to get right, in the order it matters (§5 B2):
 *
 *  1. the attempt is never orphaned — "Ask about this" opens OVER the question
 *     and closing it leaves the question DOM byte-identical,
 *  2. the keyboard map works without a mouse,
 *  3. the verdict is announced, not just painted,
 *  4. nothing moves between states.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, act } from "@testing-library/react";
import { __resetScrollLocksForTests } from "@/lib/useScrollLock";
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

const api = vi.hoisted(() => ({
  startSessionStream: vi.fn(),
  startSession: vi.fn(),
  streamChat: vi.fn(),
  sendChat: vi.fn(),
  shouldFallBackToJson: vi.fn(() => true),
}));
vi.mock("@/lib/api", () => api);

// MarkdownChat is lazy-loaded (mermaid + katex + highlight.js); render its
// text so assertions see the reply synchronously.
vi.mock("next/dynamic", () => ({
  default: () =>
    function MarkdownStub({ children }: { children: React.ReactNode }) {
      return <div>{children}</div>;
    },
}));

// ── fixtures ──────────────────────────────────────────────────────────────

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
    question: `What is the purpose of a base case in a recursive function? (${id})`,
    options: [
      { label: "A", text: "It makes the function run faster by caching results" },
      { label: "B", text: "It stops the recursion by returning without another call" },
      { label: "C", text: "It increases the recursion depth available" },
      { label: "D", text: "It converts the recursion into a loop at compile time" },
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
    ...over,
  };
}

function makeActions(): QuizActions {
  return {
    configure: vi.fn(),
    setConfig: vi.fn(),
    start: vi.fn(),
    select: vi.fn(),
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
    flag: vi.fn(),
    dismissError: vi.fn(),
    retry: vi.fn(),
  };
}

function renderScreen(session: QuizSession, actions: QuizActions = makeActions()) {
  const view = render(
    <QuizQuestion
      session={session}
      actions={actions}
      config={null}
      concept={CONCEPT}
      userId="user-1"
      courseId="course-cs101"
    />,
  );
  return { ...view, actions };
}

const root = () => screen.getByTestId("quiz-panel");

beforeEach(() => {
  vi.clearAllMocks();
  api.shouldFallBackToJson.mockReturnValue(true);
  api.startSessionStream.mockResolvedValue({ session_id: "tutor-1", reply: "Hello." });
  api.streamChat.mockResolvedValue({ reply: "Because the base case is the exit." });
});

afterEach(() => {
  cleanup();
  __resetScrollLocksForTests();
});

// ── the screen ────────────────────────────────────────────────────────────

describe("QuizQuestion — the question", () => {
  it("renders the stem, the options and the progress rail", () => {
    renderScreen(makeSession({ cursor: 1, items: [item(0, { verdict: { isCorrect: true, correctIndex: 1, explanation: "" }, selectedIndex: 1 }), item(1), item(2)] }));

    expect(screen.getByText(/purpose of a base case/)).toBeInTheDocument();
    expect(screen.getByTestId("quiz-answer-options")).toHaveAttribute("role", "radiogroup");
    for (const label of ["A", "B", "C", "D"]) {
      expect(screen.getByTestId(`quiz-answer-option-${label}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("quiz-progress")).toHaveAttribute("aria-label", "Question 2 of 3");
    expect(screen.getByText("Recursion · CS101")).toBeInTheDocument();
    expect(screen.getByText("MEDIUM")).toBeInTheDocument();
  });

  it("gives the radiogroup exactly one tab stop — the selection, else the first row", () => {
    const { rerender } = renderScreen(makeSession());
    expect(screen.getByTestId("quiz-answer-option-A")).toHaveAttribute("tabindex", "0");
    expect(screen.getByTestId("quiz-answer-option-C")).toHaveAttribute("tabindex", "-1");

    rerender(
      <QuizQuestion
        session={makeSession({ items: [item(0, { selectedIndex: 2 }), item(1), item(2)] })}
        actions={makeActions()}
        config={null}
        concept={CONCEPT}
        userId="user-1"
        courseId="course-cs101"
      />,
    );
    expect(screen.getByTestId("quiz-answer-option-A")).toHaveAttribute("tabindex", "-1");
    expect(screen.getByTestId("quiz-answer-option-C")).toHaveAttribute("tabindex", "0");
  });

  it("reserves the mark slot in every state, so revealing a verdict reflows nothing", () => {
    const { container, rerender } = renderScreen(makeSession());
    const marks = () => container.querySelectorAll(".answer-option__mark");

    expect(marks()).toHaveLength(4);
    marks().forEach(mark => {
      expect(mark).toHaveAttribute("aria-hidden", "true");
      expect(mark.textContent).toBe("");
    });

    rerender(
      <QuizQuestion
        session={makeSession({
          phase: "answered",
          items: [
            item(0, {
              selectedIndex: 2,
              verdict: { isCorrect: false, correctIndex: 1, explanation: "The base case ends it." },
            }),
            item(1),
            item(2),
          ],
        })}
        actions={makeActions()}
        config={null}
        concept={CONCEPT}
        userId="user-1"
        courseId="course-cs101"
      />,
    );
    // Same four slots, still every one of them present.
    expect(marks()).toHaveLength(4);
    marks().forEach(mark => expect(mark).toHaveAttribute("aria-hidden", "true"));
  });
});

describe("QuizQuestion — keyboard", () => {
  it("selects with the letter keys and the number keys", () => {
    const { actions } = renderScreen(makeSession());

    fireEvent.keyDown(root(), { key: "c" });
    expect(actions.select).toHaveBeenCalledWith(2);

    fireEvent.keyDown(root(), { key: "2" });
    expect(actions.select).toHaveBeenCalledWith(1);

    // Past the end of the option list is not a selection.
    actions.select = vi.fn();
    fireEvent.keyDown(root(), { key: "f" });
    expect(actions.select).not.toHaveBeenCalled();
  });

  it("moves the selection with the arrow keys, wrapping", () => {
    const { actions } = renderScreen(makeSession({ items: [item(0, { selectedIndex: 3 }), item(1), item(2)] }));

    fireEvent.keyDown(screen.getByTestId("quiz-answer-options"), { key: "ArrowDown" });
    expect(actions.select).toHaveBeenCalledWith(0);

    fireEvent.keyDown(screen.getByTestId("quiz-answer-options"), { key: "ArrowUp" });
    expect(actions.select).toHaveBeenCalledWith(2);
  });

  it("Enter submits while active and advances once the verdict is showing", () => {
    const { actions, rerender } = renderScreen(
      makeSession({ items: [item(0, { selectedIndex: 1 }), item(1), item(2)] }),
    );

    fireEvent.keyDown(root(), { key: "Enter" });
    expect(actions.submitAnswer).toHaveBeenCalledTimes(1);

    const answered = makeActions();
    rerender(
      <QuizQuestion
        session={makeSession({
          phase: "answered",
          items: [
            item(0, {
              selectedIndex: 1,
              verdict: { isCorrect: true, correctIndex: 1, explanation: "Right." },
            }),
            item(1),
            item(2),
          ],
        })}
        actions={answered}
        config={null}
        concept={CONCEPT}
        userId="user-1"
        courseId="course-cs101"
      />,
    );
    fireEvent.keyDown(root(), { key: "Enter" });
    expect(answered.next).toHaveBeenCalledTimes(1);
  });

  it("listens on the screen root, not on window", () => {
    const { actions } = renderScreen(makeSession());
    // The same keypress that selects when it reaches the root must do nothing
    // when the quiz doesn't own the focus.
    fireEvent.keyDown(document.body, { key: "c" });
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(actions.select).not.toHaveBeenCalled();
    expect(actions.requestLeave).not.toHaveBeenCalled();
  });

  it("leaves Space to the answer row's own activation", () => {
    const { actions } = renderScreen(
      makeSession({ items: [item(0, { selectedIndex: 1 }), item(1), item(2)] }),
    );
    const row = screen.getByTestId("quiz-answer-option-C");

    // `fireEvent` returns false when the handler called preventDefault. Enter
    // is the footer's action and IS pre-empted; Space must not be, or the
    // row's native button activation never runs.
    expect(fireEvent.keyDown(row, { key: " " })).toBe(true);
    expect(fireEvent.keyDown(row, { key: "Enter" })).toBe(false);
    expect(actions.submitAnswer).toHaveBeenCalledTimes(1);

    // ...and what the browser does on Space is a click.
    fireEvent.click(row);
    expect(actions.select).toHaveBeenCalledWith(2);
  });

  it("Enter does nothing while no answer is chosen", () => {
    const { actions } = renderScreen(makeSession());
    fireEvent.keyDown(root(), { key: "Enter" });
    expect(actions.submitAnswer).not.toHaveBeenCalled();
  });

  it("Escape asks to leave, and the dialog's Leave confirms it", () => {
    const { actions, rerender } = renderScreen(makeSession());

    fireEvent.keyDown(root(), { key: "Escape" });
    expect(actions.requestLeave).toHaveBeenCalledTimes(1);

    const leaving = makeActions();
    rerender(
      <QuizQuestion
        session={makeSession({ phase: "confirm-leave" })}
        actions={leaving}
        config={null}
        concept={CONCEPT}
        userId="user-1"
        courseId="course-cs101"
      />,
    );
    expect(screen.getByTestId("quiz-leave-dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("quiz-leave-confirm"));
    expect(leaving.confirmLeave).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("quiz-leave-cancel"));
    expect(leaving.cancelLeave).toHaveBeenCalledTimes(1);
  });
});

describe("QuizQuestion — the verdict", () => {
  const answeredSession = () =>
    makeSession({
      phase: "answered",
      items: [
        item(0, {
          selectedIndex: 2,
          verdict: { isCorrect: false, correctIndex: 1, explanation: "The base case ends it." },
        }),
        item(1),
        item(2),
      ],
    });

  it("marks correct / chosen-wrong / muted and moves focus to the feedback line", () => {
    renderScreen(answeredSession());

    expect(screen.getByTestId("quiz-answer-option-B").className).toContain("answer-option--correct");
    expect(screen.getByTestId("quiz-answer-option-C").className).toContain(
      "answer-option--chosen-wrong",
    );
    expect(screen.getByTestId("quiz-answer-option-A").className).toContain("answer-option--muted");
    expect(screen.getByTestId("quiz-answer-option-D").className).toContain("answer-option--muted");

    const feedback = screen.getByTestId("quiz-review-verdict");
    expect(feedback).toHaveTextContent("Not quite — the answer is B.");
    expect(feedback).toHaveTextContent("The base case ends it.");
    expect(document.activeElement).toBe(feedback);
  });

  it("never reveals anything in at-end mode", () => {
    renderScreen(
      makeSession({
        config: { count: 3, difficulty: "medium", feedback: "at-end" },
        items: [
          item(0, {
            selectedIndex: 2,
            verdict: { isCorrect: false, correctIndex: 1, explanation: "The base case ends it." },
          }),
          item(1),
          item(2),
        ],
      }),
    );
    expect(screen.getByTestId("quiz-review-verdict")).toHaveTextContent("");
    expect(screen.getByTestId("quiz-answer-option-B").className).not.toContain(
      "answer-option--correct",
    );
  });

  it("switches the one footer button's label and testid in place", () => {
    const { rerender } = renderScreen(makeSession());
    expect(screen.getByTestId("quiz-submit-answer")).toHaveTextContent("Submit");
    expect(screen.getByTestId("quiz-submit-answer")).toBeDisabled();
    expect(screen.queryByTestId("quiz-next")).toBeNull();

    const props = (session: QuizSession) => (
      <QuizQuestion
        session={session}
        actions={makeActions()}
        config={null}
        concept={CONCEPT}
        userId="user-1"
        courseId="course-cs101"
      />
    );

    rerender(props(makeSession({ items: [item(0, { selectedIndex: 1 }), item(1), item(2)] })));
    expect(screen.getByTestId("quiz-submit-answer")).toBeEnabled();

    rerender(props(answeredSession()));
    expect(screen.queryByTestId("quiz-submit-answer")).toBeNull();
    expect(screen.getByTestId("quiz-next")).toHaveTextContent("Next");

    rerender(
      props(
        makeSession({
          phase: "answered",
          cursor: 2,
          items: [
            item(0),
            item(1),
            item(2, {
              selectedIndex: 0,
              verdict: { isCorrect: true, correctIndex: 0, explanation: "" },
            }),
          ],
        }),
      ),
    );
    expect(screen.getByTestId("quiz-next")).toHaveTextContent("See results");

    rerender(props(makeSession({ phase: "submitting" })));
    expect(screen.getByTestId("quiz-submit-answer")).toHaveTextContent("Scoring…");
    expect(screen.getByTestId("quiz-submit-answer")).toBeDisabled();
  });

  it("holds Submit while the hook says a call is in flight", () => {
    const actions = makeActions();
    const session = makeSession({ items: [item(0, { selectedIndex: 1 }), item(1), item(2)] });
    const { rerender } = render(
      <QuizQuestion
        session={session}
        actions={actions}
        config={null}
        concept={CONCEPT}
        userId="user-1"
        courseId="course-cs101"
        pending={false}
      />,
    );
    expect(screen.getByTestId("quiz-submit-answer")).toBeEnabled();

    rerender(
      <QuizQuestion
        session={session}
        actions={actions}
        config={null}
        concept={CONCEPT}
        userId="user-1"
        courseId="course-cs101"
        pending
      />,
    );
    // Same phase, same selection — only `pending` moved, and it is enough.
    expect(screen.getByTestId("quiz-submit-answer")).toBeDisabled();
    expect(screen.getByTestId("quiz-answer-option-A")).toHaveAttribute("aria-disabled", "true");

    fireEvent.keyDown(root(), { key: "Enter" });
    fireEvent.keyDown(root(), { key: "d" });
    expect(actions.submitAnswer).not.toHaveBeenCalled();
    expect(actions.select).not.toHaveBeenCalled();
  });
});

describe("QuizQuestion — flag and generating", () => {
  it("flags with a toast and reflects the flag in aria-pressed", () => {
    const { actions, rerender } = renderScreen(makeSession());
    const flag = screen.getByTestId("quiz-flag");
    expect(flag).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(flag);
    expect(actions.flag).toHaveBeenCalledTimes(1);
    expect(toastApi.show).toHaveBeenCalledWith("Noted — thanks.");

    rerender(
      <QuizQuestion
        session={makeSession({ items: [item(0, { flagged: true }), item(1), item(2)] })}
        actions={actions}
        config={null}
        concept={CONCEPT}
        userId="user-1"
        courseId="course-cs101"
      />,
    );
    expect(screen.getByTestId("quiz-flag")).toHaveAttribute("aria-pressed", "true");
  });

  it("shows the skeleton while the quiz is being written, and says so", () => {
    const { container } = renderScreen(
      makeSession({ phase: "generating", items: [], attemptId: null }),
    );
    expect(screen.getByTestId("quiz-generating")).toBeInTheDocument();
    expect(screen.getByText("Writing your quiz…")).toBeInTheDocument();
    expect(container.querySelectorAll(".quiz-question__skeleton-row")).toHaveLength(4);
    expect(screen.queryByTestId("quiz-answer-options")).toBeNull();
  });

  it("says so exactly once when fewer questions arrived than were asked for", () => {
    const short = makeSession({ deliveredShort: true, items: [item(0), item(1)] });
    const { rerender } = renderScreen(short);
    expect(toastApi.show).toHaveBeenCalledWith("Only 2 questions were ready for this concept.");
    expect(toastApi.show).toHaveBeenCalledTimes(1);

    // Every re-render of the same attempt — a selection, a verdict, a flag —
    // must not re-announce it.
    rerender(
      <QuizQuestion
        session={short}
        actions={makeActions()}
        config={null}
        concept={CONCEPT}
        userId="user-1"
        courseId="course-cs101"
      />,
    );
    rerender(
      <QuizQuestion
        session={{ ...short, items: [item(0, { selectedIndex: 1 }), item(1)] }}
        actions={makeActions()}
        config={null}
        concept={CONCEPT}
        userId="user-1"
        courseId="course-cs101"
      />,
    );
    expect(toastApi.show).toHaveBeenCalledTimes(1);
  });
});

// ── the whole point ───────────────────────────────────────────────────────

describe("QuizQuestion — Ask about this never orphans the attempt", () => {
  const answeredSession = () =>
    makeSession({
      phase: "answered",
      items: [
        item(0, {
          selectedIndex: 2,
          verdict: { isCorrect: false, correctIndex: 1, explanation: "The base case ends it." },
        }),
        item(1),
        item(2),
      ],
    });

  it("is offered only once there is a verdict", () => {
    const { rerender } = renderScreen(makeSession());
    expect(screen.queryByTestId("quiz-ask")).toBeNull();

    rerender(
      <QuizQuestion
        session={answeredSession()}
        actions={makeActions()}
        config={null}
        concept={CONCEPT}
        userId="user-1"
        courseId="course-cs101"
      />,
    );
    expect(screen.getByTestId("quiz-ask")).toBeInTheDocument();
  });

  it("opens the tutor over the question, seeds it, and leaves the question untouched", async () => {
    const { container, actions } = renderScreen(answeredSession());
    const optionsBefore = screen.getByTestId("quiz-answer-options").innerHTML;
    const stemBefore = container.querySelector(".quiz-question__stem")!.innerHTML;

    await act(async () => {
      fireEvent.click(screen.getByTestId("quiz-ask"));
    });

    const panel = await screen.findByTestId("quiz-ask-panel");
    expect(panel).toHaveAttribute("aria-modal", "true");

    // Two-call seeding (R1 §F): the session is opened on the concept name with
    // the course id, then the context arrives as the first message.
    await waitFor(() => expect(api.startSessionStream).toHaveBeenCalledTimes(1));
    expect(api.startSessionStream.mock.calls[0].slice(0, 5)).toEqual([
      "user-1",
      "Recursion",
      "socratic",
      true,
      "course-cs101",
    ]);

    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(1));
    const seedMessage = api.streamChat.mock.calls[0][2] as string;
    expect(seedMessage).toContain("I got this quiz question wrong and want to understand why.");
    expect(seedMessage).toContain("Question: What is the purpose of a base case");
    expect(seedMessage).toContain("I chose C: It increases the recursion depth available");
    expect(seedMessage).toContain(
      "The correct answer is B: It stops the recursion by returning without another call",
    );
    expect(seedMessage).toContain("Explanation given: The base case ends it.");
    expect(seedMessage).toContain("Help me understand why.");

    // The seeded context is on screen, and so is the reply.
    expect(screen.getByTestId("quiz-ask-seed")).toBeInTheDocument();
    await waitFor(() =>
      expect(panel).toHaveTextContent("Because the base case is the exit."),
    );

    // Nothing about the attempt moved — not one machine event, of any kind.
    Object.values(actions).forEach(fn => expect(fn).not.toHaveBeenCalled());
    expect(screen.getByTestId("quiz-answer-options").innerHTML).toBe(optionsBefore);

    // Closing puts the student back exactly where they were.
    await act(async () => {
      fireEvent.click(screen.getByTestId("quiz-ask-panel-close"));
    });
    expect(screen.queryByTestId("quiz-ask-panel")).toBeNull();
    expect(screen.getByTestId("quiz-answer-options").innerHTML).toBe(optionsBefore);
    expect(container.querySelector(".quiz-question__stem")!.innerHTML).toBe(stemBefore);
    expect(document.activeElement).toBe(screen.getByTestId("quiz-ask"));
  });

  it("ignores the answer shortcuts while the panel has the keyboard", async () => {
    const { actions } = renderScreen(answeredSession());
    await act(async () => {
      fireEvent.click(screen.getByTestId("quiz-ask"));
    });
    await screen.findByTestId("quiz-ask-panel");

    fireEvent.keyDown(screen.getByTestId("quiz-ask-input"), { key: "a" });
    fireEvent.keyDown(screen.getByTestId("quiz-ask-input"), { key: "Escape" });
    expect(actions.select).not.toHaveBeenCalled();
    expect(actions.requestLeave).not.toHaveBeenCalled();
  });
});
