import { describe, expect, it } from "vitest";
import type { QuizItem, QuizSession, WireQuestion } from "@/lib/quiz/types";
import {
  arrowStep,
  askSeedFor,
  canGoTo,
  canNavigate,
  hintSlotState,
  scaffoldHint,
  skipSlotState,
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
    prereq: null,
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

  it("W7.2 Sort: hasAnswer only when every item is placed", () => {
    const interaction = {
      kind: "sort" as const,
      buckets: ["A", "B"],
      items: [
        { id: "one", label: "One" },
        { id: "two", label: "Two" },
      ],
    };
    const sortQ = question({ type: "short_answer", options: [], interaction });
    expect(itemView(item({ question: sortQ, answerText: "A=one;B=" })).hasAnswer).toBe(false);
    expect(itemView(item({ question: sortQ, answerText: "A=one;B=two" })).hasAnswer).toBe(true);
  });

  it("W7.2 Label: hasAnswer only when every label is placed", () => {
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
    const labelQ = question({ type: "short_answer", options: [], interaction });
    expect(itemView(item({ question: labelQ, answerText: "1=aorta;2=" })).hasAnswer).toBe(false);
    expect(itemView(item({ question: labelQ, answerText: "1=aorta;2=pa" })).hasAnswer).toBe(true);
  });

  it("W7.2 Build: hasAnswer only when every slot is filled", () => {
    const interaction = {
      kind: "build" as const,
      slots: [
        { id: "head", label: "Head" },
        { id: "base", label: "Base" },
      ],
      parts: [
        { id: "phosphate", label: "Phosphate" },
        { id: "adenine", label: "Adenine" },
        { id: "amino", label: "Amino acid" },
      ],
    };
    const buildQ = question({ type: "short_answer", options: [], interaction });
    expect(itemView(item({ question: buildQ, answerText: "head=phosphate;base=" })).hasAnswer).toBe(false);
    expect(itemView(item({ question: buildQ, answerText: "head=phosphate;base=adenine" })).hasAnswer).toBe(true);
  });

  it("W7.2 Compare: hasAnswer only when a relation option is chosen", () => {
    const interaction = {
      kind: "compare" as const,
      left: { id: "mitosis", label: "Mitosis" },
      right: { id: "meiosis", label: "Meiosis" },
      options: [
        { id: "left_only", label: "Only the left" },
        { id: "both", label: "Both" },
      ],
    };
    const compareQ = question({ type: "short_answer", options: [], interaction });
    expect(itemView(item({ question: compareQ, answerText: "" })).hasAnswer).toBe(false);
    expect(itemView(item({ question: compareQ, answerText: "both" })).hasAnswer).toBe(true);
  });

  it("W7.2 Dialogue: hasAnswer only after minReplies", () => {
    const interaction = {
      kind: "dialogue" as const,
      role: "Confused Classmate",
      open: "Heavier objects fall faster?",
      follow: "Doesn't a bigger force mean faster?",
      minReplies: 2,
    };
    const dialogueQ = question({ type: "short_answer", options: [], interaction });
    expect(itemView(item({ question: dialogueQ, answerText: "Only one" })).hasAnswer).toBe(false);
    expect(
      itemView(item({ question: dialogueQ, answerText: "First\u001eSecond" })).hasAnswer,
    ).toBe(true);
  });

  it("W7.2 Explain: hasAnswer when prose is non-empty", () => {
    const interaction = { kind: "explain" as const, placeholder: "Type your explanation" };
    const explainQ = question({ type: "short_answer", options: [], interaction });
    expect(itemView(item({ question: explainQ, answerText: "" })).hasAnswer).toBe(false);
    expect(itemView(item({ question: explainQ, answerText: "  Because free fall.  " })).hasAnswer).toBe(true);
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

describe("W7.5 hint / skip slots", () => {
  it("builds scaffolding from concept + rubric already on the question", () => {
    const mc = scaffoldHint({ conceptName: "Recursion", conceptTested: "Base cases", format: "multiple_choice" });
    expect(mc.focus).toBe("Base cases");
    expect(mc.rubric).toBeNull();
    expect(mc.note).toMatch(/never the answer/i);

    const written = scaffoldHint({ conceptName: "Recursion", format: "numeric" });
    expect(written.focus).toBe("Recursion");
    expect(written.rubric).toMatch(/^Enter only the number/);

    const sort = scaffoldHint({ conceptName: "Recursion", format: "short_answer", sort: true });
    expect(sort.rubric).toMatch(/^Select an item/);

    const sequence = scaffoldHint({ conceptName: "Mitosis", format: "short_answer", sequence: true });
    expect(sequence.rubric).toMatch(/^Select a step/);

    const label = scaffoldHint({ conceptName: "Anatomy", format: "short_answer", label: true });
    expect(label.rubric).toMatch(/^Select a label/);

    const build = scaffoldHint({ conceptName: "Nucleotides", format: "short_answer", build: true });
    expect(build.rubric).toMatch(/^Select a part/);
    const compare = scaffoldHint({ conceptName: "Cell division", format: "short_answer", compare: true });
    expect(compare.rubric).toMatch(/^Read both sides/);
    const dialogue = scaffoldHint({ conceptName: "Free fall", format: "short_answer", dialogue: true });
    expect(dialogue.rubric).toMatch(/^Reply to your partner/);
    const explain = scaffoldHint({ conceptName: "Orbits", format: "short_answer", explain: true });
    expect(explain.rubric).toMatch(/^Write a short explanation/);
  });

  it("enables Hint in Practice and refuses it in Exam Twin", () => {
    expect(hintSlotState({ phase: "active", busy: false, sessionMode: "practice", hasItem: true }).enabled).toBe(true);
    expect(hintSlotState({ phase: "active", busy: false, sessionMode: "exam_twin", hasItem: true })).toEqual({
      enabled: false,
      title: expect.stringMatching(/Exam Twin/i),
    });
    expect(hintSlotState({ phase: "generating", busy: false, sessionMode: "practice", hasItem: true }).enabled).toBe(false);
    expect(hintSlotState({ phase: "active", busy: true, sessionMode: "practice", hasItem: true }).enabled).toBe(false);
    expect(hintSlotState({ phase: "active", busy: false, sessionMode: "practice", hasItem: false }).enabled).toBe(false);
  });

  it("enables Skip to the next unanswered index without mastery", () => {
    expect(skipSlotState({ phase: "active", busy: false, cursor: 0, total: 3, hasVerdict: false })).toEqual({
      enabled: true,
      title: expect.stringMatching(/no mastery/i),
      targetIndex: 1,
    });
  });

  it("disables Skip on the last question, after a verdict, or when locked", () => {
    expect(skipSlotState({ phase: "active", busy: false, cursor: 2, total: 3, hasVerdict: false }).enabled).toBe(false);
    expect(skipSlotState({ phase: "active", busy: false, cursor: 2, total: 3, hasVerdict: false }).title).toMatch(/last question/i);
    expect(skipSlotState({ phase: "active", busy: false, cursor: 0, total: 3, hasVerdict: true }).enabled).toBe(false);
    expect(skipSlotState({ phase: "active", busy: false, cursor: 0, total: 3, hasVerdict: true }).title).toMatch(/Already answered/i);
    expect(skipSlotState({ phase: "active", busy: true, cursor: 0, total: 3, hasVerdict: false }).enabled).toBe(false);
    expect(skipSlotState({ phase: "submitting", busy: false, cursor: 0, total: 3, hasVerdict: false }).enabled).toBe(false);
  });
});

describe("primaryButton", () => {
  const base = { phase: "active" as const, showVerdict: false, allAnswered: false, busy: false, hasAnswer: true };

  it("submits a chosen answer while active", () => {
    expect(primaryButton(base)).toEqual({ label: "Check", testid: "quiz-submit-answer", enabled: true, action: "submit" });
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
    expect(formatHint("short_answer", { sort: true })).toMatch(/^Select an item/);
    expect(formatHint("short_answer", { sequence: true })).toMatch(/^Select a step/);
    expect(formatHint("short_answer", { label: true })).toMatch(/^Select a label/);
    expect(formatHint("short_answer", { build: true })).toMatch(/^Select a part/);
    expect(formatHint("short_answer", { compare: true })).toMatch(/^Read both sides/);
    expect(formatHint("short_answer", { dialogue: true })).toMatch(/^Reply to your partner/);
    expect(formatHint("short_answer", { explain: true })).toMatch(/^Write a short explanation/);
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
