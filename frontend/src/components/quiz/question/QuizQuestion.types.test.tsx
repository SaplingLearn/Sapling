// @vitest-environment jsdom
/**
 * W7.2: core question types (MC / short / numeric / algebra) under the focus
 * SessionTop shell, plus Sort (7.1) / Label (7.4) kit stubs on short_answer+interaction.
 * Later interactive types (label / dialogue…) stay phased.
 */

import React from "react";
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import type { QuizItem, QuizSession, QuestionType, WireQuestion } from "@/lib/quiz/types";
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
vi.mock("./AskPanel", () => ({ AskPanel: () => null }));
vi.mock("./StudyGuideDrawer", () => ({ StudyGuideDrawer: () => null }));

const CONCEPT: QuizConceptSummary = {
  id: "node-recursion",
  name: "Recursion",
  courseCode: "CS101",
  color: "#7b4b99",
  tier: "struggling",
  mastery: 0.29,
};

const FORMAT_LABEL: Record<QuestionType, string> = {
  multiple_choice: "Multiple choice",
  short_answer: "Short answer",
  numeric: "Numeric",
  symbolic: "Algebra",
};

function mcQuestion(id: number): WireQuestion {
  return {
    id,
    question: `What is a base case? (${id})`,
    type: "multiple_choice",
    options: [
      { label: "A", text: "Caching" },
      { label: "B", text: "The exit" },
      { label: "C", text: "More depth" },
      { label: "D", text: "A loop" },
    ],
    difficulty: "medium",
  };
}

function writtenQuestion(type: Exclude<QuestionType, "multiple_choice">, stem: string): WireQuestion {
  return {
    id: 1,
    question: stem,
    type,
    options: [],
    difficulty: "medium",
  };
}

function item(index: number, over: Partial<QuizItem> = {}): QuizItem {
  return {
    index,
    question: mcQuestion(index + 1),
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

/** SessionTop + format tag + action bar — the focus-shell chrome every type shares. */
function expectFocusChrome(format: QuestionType) {
  expect(screen.getByTestId("quiz-session-top")).toBeInTheDocument();
  expect(screen.getByTestId("quiz-session-progress")).toHaveTextContent("Question 1 of 3");
  expect(screen.getByRole("progressbar", { name: "Question 1 of 3" })).toBeInTheDocument();
  expect(screen.getByTestId("quiz-leave")).toBeInTheDocument();
  expect(screen.getByTestId("quiz-action-bar")).toBeInTheDocument();
  const tag = screen.getByTestId("quiz-format-tag");
  expect(tag).toHaveAttribute("data-format", format);
  expect(tag).toHaveTextContent(FORMAT_LABEL[format]);
  // W7.D1: XP stays off SessionTop for every type.
  expect(screen.getByTestId("quiz-session-top").textContent ?? "").not.toMatch(/XP|streak/i);
}

beforeEach(() => {
  toastApi.show.mockReset();
});
afterEach(cleanup);

describe("W7.2 core types under SessionTop", () => {
  it("multiple choice: radiogroup, keyboard hint, and options under SessionTop", () => {
    const { actions } = renderScreen(makeSession());
    expectFocusChrome("multiple_choice");

    expect(screen.getByTestId("quiz-keyboard-hint")).toHaveTextContent(/Keyboard: press A to F/);
    const group = screen.getByTestId("quiz-answer-options");
    expect(group).toHaveAttribute("role", "radiogroup");
    expect(group).toHaveAccessibleName("Answer choices");
    expect(group).toHaveAccessibleDescription(/Keyboard: press A to F/);
    for (const label of ["A", "B", "C", "D"]) {
      expect(screen.getByTestId(`quiz-answer-option-${label}`)).toHaveAttribute("role", "radio");
    }
    expect(screen.queryByTestId("quiz-written")).toBeNull();
    expect(screen.queryByTestId("quiz-format-hint")).toBeNull();

    fireEvent.click(screen.getByTestId("quiz-answer-option-B"));
    expect(actions.select).toHaveBeenCalledWith(1);
    expect(document.activeElement).toBe(screen.getByTestId("quiz-panel"));
  });

  it.each([
    ["short_answer", "Name the exit condition.", "Write a brief answer", [] as string[]],
    ["numeric", "What is 3/4 as a decimal?", "Enter only the number, without units", ["minus", "fraction", "percent", "exponent", "space"]],
    ["symbolic", "Expand (x + 1)^2.", "single-letter variables", ["squared", "power", "brackets", "plus", "minus", "times", "divide"]],
  ] as const)(
    "%s: written field, format hint, and keys under SessionTop",
    (type, stem, hint, keyIds) => {
      const { actions } = renderScreen(
        makeSession({
          items: [
            item(0, { question: writtenQuestion(type, stem), answerText: "" }),
            item(1),
            item(2),
          ],
        }),
      );
      expectFocusChrome(type);

      const field = screen.getByTestId("quiz-written");
      expect(field).toHaveAttribute("data-format", type);
      const input = screen.getByTestId("quiz-written-answer");
      expect(input).toHaveFocus();
      expect(input).toHaveAccessibleName(/^Your answer/);
      expect(screen.getByTestId("quiz-format-hint")).toHaveTextContent(hint);
      expect(input).toHaveAccessibleDescription(new RegExp(hint.slice(0, 12), "i"));

      expect(screen.queryByTestId("quiz-answer-options")).toBeNull();
      expect(screen.queryByTestId("quiz-keyboard-hint")).toBeNull();

      for (const id of keyIds) {
        expect(screen.getByTestId(`quiz-key-${id}`)).toBeInTheDocument();
      }
      if (type === "short_answer") {
        expect(screen.queryByRole("group", { name: "Insert a symbol" })).toBeNull();
      } else {
        expect(screen.getByRole("group", { name: "Insert a symbol" })).toBeInTheDocument();
      }
      if (type === "symbolic") {
        expect(screen.getByTestId("quiz-key-more")).toBeInTheDocument();
        // Algebra stem raises exponents under SessionTop.
        expect(document.getElementById("quiz-question-stem")!.querySelector("sup")).toHaveTextContent("2");
      }

      fireEvent.change(input, { target: { value: type === "numeric" ? "0.75" : "x" } });
      expect(actions.write).toHaveBeenCalled();
    },
  );

  it("numeric: live read-back stays on the field under SessionTop", () => {
    renderScreen(
      makeSession({
        items: [
          item(0, {
            question: writtenQuestion("numeric", "Simplify 3/4."),
            answerText: "3/4",
          }),
          item(1),
          item(2),
        ],
      }),
    );
    expectFocusChrome("numeric");
    const readBack = screen.getByTestId("quiz-written-readback");
    expect(readBack).toHaveAttribute("data-ok", "true");
    expect(readBack).toHaveTextContent("Reads as 0.75");
    expect(readBack.closest("[data-testid='quiz-written']")).not.toBeNull();
  });

  it("algebra: grammar warning is announced before submit", () => {
    renderScreen(
      makeSession({
        items: [
          item(0, {
            question: writtenQuestion("symbolic", "Simplify sin(x)."),
            answerText: "sin(x)",
          }),
          item(1),
          item(2),
        ],
      }),
    );
    expectFocusChrome("symbolic");
    const readBack = screen.getByTestId("quiz-written-readback");
    expect(readBack).toHaveAttribute("data-ok", "false");
    expect(readBack).toHaveTextContent(/Functions like sin/);
    expect(screen.getByTestId("quiz-written-answer")).toHaveAttribute("aria-invalid", "true");
  });

  it("CSS keeps answer surfaces from collapsing under SessionTop + footer pin", () => {
    const css = fs.readFileSync(path.resolve(__dirname, "question.css"), "utf8");
    for (const sel of [".quiz-question__options", ".quiz-question__written"]) {
      const rule = css.match(new RegExp(`${sel.replace(".", "\\.")}\\s*\\{([^}]*)\\}`));
      expect(rule, sel).not.toBeNull();
      expect(rule![1]).toMatch(/flex-shrink:\s*0/);
    }
  });

  it("Sort (7.1): tray/buckets under SessionTop; Check waits for a full placement", () => {
    const interaction = {
      kind: "sort" as const,
      buckets: ["Prokaryote", "Eukaryote"],
      items: [
        { id: "e-coli", label: "E. coli" },
        { id: "yeast", label: "Yeast" },
      ],
    };
    const { actions } = renderScreen(
      makeSession({
        items: [
          item(0, {
            question: {
              id: 1,
              question: "Sort these into Prokaryote or Eukaryote.",
              type: "short_answer",
              options: [],
              difficulty: "medium",
              interaction,
            },
          }),
          item(1),
          item(2),
        ],
      }),
    );

    expect(screen.getByTestId("quiz-session-top")).toBeInTheDocument();
    const tag = screen.getByTestId("quiz-format-tag");
    expect(tag).toHaveAttribute("data-format", "sort");
    expect(tag).toHaveTextContent("Sort");
    expect(screen.getByTestId("quiz-sort")).toBeInTheDocument();
    expect(screen.getByTestId("quiz-format-hint")).toHaveTextContent(/Select an item/);
    expect(screen.getByTestId("quiz-submit-answer")).toBeDisabled();

    fireEvent.click(screen.getByTestId("quiz-sort-item-e-coli"));
    fireEvent.click(screen.getByRole("button", { name: "Place in Prokaryote" }));
    expect(actions.write).toHaveBeenCalledWith("Prokaryote=e-coli;Eukaryote=");
  });

  it("Label (7.4): spots/tray under SessionTop; Check waits for a full placement", () => {
    const interaction = {
      kind: "label" as const,
      spots: [
        { id: "1", label: "1" },
        { id: "2", label: "2" },
      ],
      labels: [
        { id: "aorta", label: "Aorta" },
        { id: "pa", label: "Pulmonary artery" },
      ],
    };
    const { actions } = renderScreen(
      makeSession({
        items: [
          item(0, {
            question: {
              id: 1,
              question: "Label the parts of the heart.",
              type: "short_answer",
              options: [],
              difficulty: "medium",
              interaction,
            },
          }),
          item(1),
          item(2),
        ],
      }),
    );

    expect(screen.getByTestId("quiz-session-top")).toBeInTheDocument();
    const tag = screen.getByTestId("quiz-format-tag");
    expect(tag).toHaveAttribute("data-format", "label");
    expect(tag).toHaveTextContent("Label");
    expect(screen.getByTestId("quiz-label")).toBeInTheDocument();
    expect(screen.getByTestId("quiz-format-hint")).toHaveTextContent(/Select a label/);
    expect(screen.getByTestId("quiz-submit-answer")).toBeDisabled();

    fireEvent.click(screen.getByTestId("quiz-label-item-aorta"));
    fireEvent.click(screen.getByRole("button", { name: "Place on 1" }));
    expect(actions.write).toHaveBeenCalledWith("1=aorta;2=");
  });
});
