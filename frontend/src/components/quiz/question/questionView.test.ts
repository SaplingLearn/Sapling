import { describe, expect, it } from "vitest";
import type { QuizItem, QuizSession, WireQuestion } from "@/lib/quiz/types";
import {
  arrowStep,
  askSeedFor,
  canGoTo,
  canNavigate,
  conceptLabel,
  correctOption,
  difficultyLabel,
  everyAnswered,
  formatHint,
  generatingDetail,
  itemView,
  missLine,
  nextOptionIndex,
  optionState,
  optionStatus,
  outcomeOf,
  primaryButton,
  verdictShown,
  withFullStop,
} from "./questionView";

const OPTIONS = [
  { label: "A", text: "a" },
  { label: "B", text: "b" },
  { label: "C", text: "c" },
];

function question(over: Partial<WireQuestion> = {}): WireQuestion {
  return { id: 1, question: "Q?", options: OPTIONS, difficulty: "medium", ...over };
}

function item(over: Partial<QuizItem> = {}): QuizItem {
  return { index: 0, question: question(), selectedIndex: null, verdict: null, flagged: false, ...over };
}

function session(over: Partial<QuizSession> = {}): QuizSession {
  return {
    intent: "practice",
    scope: { kind: "concept", conceptId: "c" },
    source: { kind: "nav" },
    config: { count: 3, difficulty: "easy", feedback: "as-you-go" },
    conceptId: "c",
    courseId: null,
    attemptId: "a",
    items: [item(), item(), item()],
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

const wrong = { isCorrect: false, correctIndex: 1, explanation: "why" };
const right = { isCorrect: true, correctIndex: 1, explanation: "" };

describe("itemView", () => {
  it("reads a multiple-choice item", () => {
    expect(itemView(item({ selectedIndex: 2 }))).toMatchObject({
      options: OPTIONS,
      selectedIndex: 2,
      written: false,
      format: "multiple_choice",
      hasAnswer: true,
      verdict: null,
    });
  });

  it("treats an unknown type as multiple choice", () => {
    const view = itemView(item({ question: question({ type: "true_false" as WireQuestion["type"] }) }));
    expect(view.format).toBe("multiple_choice");
    expect(view.written).toBe(false);
  });

  it("reads a written item: an answer is any non-blank text", () => {
    const numeric = (answerText?: string) => itemView(item({ question: question({ type: "numeric", options: [] }), answerText }));
    expect(numeric("  ")).toMatchObject({ written: true, format: "numeric", hasAnswer: false });
    expect(numeric(undefined).hasAnswer).toBe(false);
    expect(numeric(" 4 ").hasAnswer).toBe(true);
  });

  it("survives no item at all", () => {
    expect(itemView(undefined)).toMatchObject({
      item: undefined,
      options: [],
      selectedIndex: null,
      written: false,
      format: "multiple_choice",
      hasAnswer: false,
      verdict: null,
    });
  });
});

describe("verdictShown", () => {
  it("needs a verdict", () => {
    expect(verdictShown(session(), item())).toBe(false);
    expect(verdictShown(session(), undefined)).toBe(false);
  });

  it("shows every verdict as you go", () => {
    expect(verdictShown(session(), item({ verdict: wrong }))).toBe(true);
  });

  it("at the end, shows only on the answered last question once all are in", () => {
    const marked = item({ verdict: wrong });
    const atEnd = { count: 3, difficulty: "easy", feedback: "at-end" as const };
    const all = [marked, marked, marked];
    expect(verdictShown(session({ config: atEnd, phase: "answered", cursor: 2, items: all }), marked)).toBe(true);
    expect(verdictShown(session({ config: atEnd, phase: "active", cursor: 2, items: all }), marked)).toBe(false);
    expect(verdictShown(session({ config: atEnd, phase: "answered", cursor: 1, items: all }), marked)).toBe(false);
    expect(verdictShown(session({ config: atEnd, phase: "answered", cursor: 2, items: [item(), marked, marked] }), marked)).toBe(false);
  });
});

describe("header and status labels", () => {
  it("prefers the question's difficulty, keeping a blank one blank", () => {
    expect(difficultyLabel(item({ question: question({ difficulty: "hard" }) }), session())).toBe("HARD");
    expect(difficultyLabel(item({ question: question({ difficulty: "" }) }), session())).toBe("");
    expect(difficultyLabel(undefined, session())).toBe("EASY");
    expect(difficultyLabel(undefined, session({ config: { count: 3, difficulty: undefined as never, feedback: "at-end" } }))).toBe("");
  });

  it("names the concept with its course code when there is one", () => {
    expect(conceptLabel({ name: "Recursion", courseCode: "CS101" })).toBe("Recursion · CS101");
    expect(conceptLabel({ name: "Recursion", courseCode: "" })).toBe("Recursion");
  });

  it("describes the quiz being written", () => {
    expect(generatingDetail(5, "Recursion", "HARD")).toBe("5 questions on Recursion · hard");
    expect(generatingDetail(5, "Recursion", "")).toBe("5 questions on Recursion");
  });
});

describe("the pager", () => {
  it("navigates only on a live question with nothing in flight", () => {
    expect(canNavigate("active", false, 3)).toBe(true);
    expect(canNavigate("answered", false, 3)).toBe(true);
    expect(canNavigate("submitting", false, 3)).toBe(false);
    expect(canNavigate("generating", false, 0)).toBe(false);
    expect(canNavigate("active", true, 3)).toBe(false);
    expect(canNavigate("active", false, 0)).toBe(false);
  });

  it("goes only to another question that exists", () => {
    expect(canGoTo(1, 0, 3, true)).toBe(true);
    expect(canGoTo(0, 0, 3, true)).toBe(false);
    expect(canGoTo(-1, 0, 3, true)).toBe(false);
    expect(canGoTo(3, 0, 3, true)).toBe(false);
    expect(canGoTo(1, 0, 3, false)).toBe(false);
  });
});

describe("primaryButton", () => {
  const base = { phase: "active" as const, showVerdict: false, allAnswered: false, busy: false, hasAnswer: true };

  it("submits a chosen answer while active", () => {
    expect(primaryButton(base)).toEqual({ label: "Submit", testid: "quiz-submit-answer", enabled: true, action: "submit" });
    expect(primaryButton({ ...base, hasAnswer: false }).enabled).toBe(false);
    expect(primaryButton({ ...base, busy: true }).enabled).toBe(false);
    expect(primaryButton({ ...base, phase: "confirm-leave" }).enabled).toBe(false);
  });

  it("moves on once answered, to the results when nothing is left", () => {
    expect(primaryButton({ ...base, phase: "answered", showVerdict: true })).toEqual({ label: "Next", testid: "quiz-next", enabled: true, action: "next" });
    expect(primaryButton({ ...base, phase: "answered", allAnswered: true }).label).toBe("See results");
    // A verdict showing while still active (as-you-go, revisited) is Next, held.
    expect(primaryButton({ ...base, showVerdict: true })).toEqual({ label: "Next", testid: "quiz-next", enabled: false, action: "next" });
  });

  it("keeps the starting press's identity while scoring", () => {
    expect(primaryButton({ ...base, phase: "submitting", showVerdict: true })).toEqual({ label: "Scoring…", testid: "quiz-next", enabled: false, action: "none" });
    expect(primaryButton({ ...base, phase: "submitting" }).testid).toBe("quiz-submit-answer");
  });

  it("counts every question answered, in any order", () => {
    expect(everyAnswered([item({ selectedIndex: 0 }), item({ verdict: right })])).toBe(true);
    expect(everyAnswered([item({ selectedIndex: 0 }), item()])).toBe(false);
    expect(everyAnswered([item({ question: question({ type: "numeric" }), answerText: "1" })])).toBe(false);
  });
});

describe("answer rows", () => {
  it("marks the selection before the verdict is shown", () => {
    expect(optionState(1, 1, null)).toBe("selected");
    expect(optionState(0, 1, null)).toBe("default");
    expect(optionStatus(1, 1, null)).toBeUndefined();
  });

  it("marks correct, chosen-wrong and muted once it is", () => {
    expect(optionState(1, 2, wrong)).toBe("correct");
    expect(optionState(2, 2, wrong)).toBe("chosen-wrong");
    expect(optionState(0, 2, wrong)).toBe("muted");
    expect(optionStatus(2, 2, wrong)).toBe("Incorrect");
    expect(optionStatus(1, 1, right)).toBe("Correct");
    expect(optionStatus(1, 2, wrong)).toBeUndefined();
  });

  it("writes the outcome only for a shown verdict", () => {
    expect(outcomeOf(null)).toBeUndefined();
    expect(outcomeOf(right)).toBe("correct");
    expect(outcomeOf(wrong)).toBe("incorrect");
  });

  it("maps the arrows to a step", () => {
    expect([arrowStep("ArrowDown"), arrowStep("ArrowRight"), arrowStep("ArrowUp"), arrowStep("ArrowLeft"), arrowStep("Home")]).toEqual([1, 1, -1, -1, 0]);
  });

  it("wraps, and starts from the edge with nothing chosen", () => {
    expect(nextOptionIndex(null, 1, 4)).toBe(0);
    expect(nextOptionIndex(null, -1, 4)).toBe(3);
    expect(nextOptionIndex(3, 1, 4)).toBe(0);
    expect(nextOptionIndex(0, -1, 4)).toBe(3);
    expect(nextOptionIndex(1, 1, 4)).toBe(2);
  });
});

describe("the verdict's words", () => {
  it("gives each written format its grading rules", () => {
    expect(formatHint("symbolic")).toMatch(/^Enter an expression using single-letter variables/);
    expect(formatHint("numeric")).toMatch(/^Enter only the number, without units/);
    expect(formatHint("short_answer")).toBe("Write a brief answer. Capitalization and extra spacing do not affect your score.");
    expect(formatHint(undefined)).toBe(formatHint("short_answer"));
  });

  it("ends the key with exactly one full stop", () => {
    expect(withFullStop("ATP")).toBe("ATP.");
    expect(withFullStop(" Why? ")).toBe("Why?");
    expect(withFullStop("respiration. ")).toBe("respiration.");
  });

  it("prefers the expected answer, then the letter, then nothing", () => {
    expect(missLine("ATP", "B")).toBe("Not quite — the expected answer is ATP.");
    expect(missLine(null, "B")).toBe("Not quite — the answer is B.");
    expect(missLine("", undefined)).toBe("Not quite.");
  });

  it("finds the correct option only for a real index", () => {
    expect(correctOption(wrong, OPTIONS)).toEqual(OPTIONS[1]);
    expect(correctOption({ ...wrong, correctIndex: -1 }, OPTIONS)).toBeUndefined();
    expect(correctOption(null, OPTIONS)).toBeUndefined();
  });
});

describe("askSeedFor", () => {
  it("seeds a choice with both letters and texts", () => {
    expect(askSeedFor(itemView(item({ selectedIndex: 2, verdict: wrong })))).toEqual({
      stem: "Q?",
      chosenLabel: "C",
      chosenText: "c",
      correctLabel: "B",
      correctText: "b",
      explanation: "why",
      written: false,
    });
  });

  it("prefers the expected answer's text over the option's", () => {
    expect(askSeedFor(itemView(item({ selectedIndex: 2, verdict: { ...wrong, correctAnswer: "key" } }))).correctText).toBe("key");
  });

  it("seeds a written answer with what was typed, keeping an empty answer empty", () => {
    const written = (answerText?: string) =>
      askSeedFor(itemView(item({ question: question({ type: "short_answer", options: [] }), answerText })));
    expect(written("loop")).toMatchObject({ chosenLabel: "—", chosenText: "loop", written: true });
    expect(written("").chosenText).toBe("");
    expect(written(undefined).chosenText).toBe("nothing");
  });

  it("seeds blanks with no item", () => {
    expect(askSeedFor(itemView(undefined))).toEqual({
      stem: "",
      chosenLabel: "—",
      chosenText: "nothing",
      correctLabel: "—",
      correctText: "",
      explanation: "",
      written: false,
    });
  });
});
