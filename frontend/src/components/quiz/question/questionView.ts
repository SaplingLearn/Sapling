/**
 * The pure half of the question screen: everything `QuizQuestion` derives
 * from the session before it renders — which format the item is, whether its
 * verdict may be shown, what the footer button says, how each answer row is
 * marked and what the tutor sheet is seeded with. No React, no I/O, so each
 * rule is testable on its own.
 */

import type { AnswerState } from "@/components/ui";
import { isUnanswered } from "@/lib/quiz/machine";
import type { Phase, QuestionType, QuizItem, QuizSession, WireOption } from "@/lib/quiz/types";
import { isWrittenType } from "@/lib/quiz/types";
import type { AskSeed } from "./AskPanel";

export type Verdict = NonNullable<QuizItem["verdict"]>;
export type Outcome = "correct" | "incorrect";

/** The facts about the open item that every part of the screen reads. */
export interface ItemView {
  item: QuizItem | undefined;
  options: WireOption[];
  selectedIndex: number | null;
  written: boolean;
  /** A type this client doesn't know is answered by choosing, exactly as the
   *  backend treats it, so it wears the multiple-choice format too. */
  format: QuestionType;
  hasAnswer: boolean;
  verdict: Verdict | null;
}

export function itemView(item: QuizItem | undefined): ItemView {
  const written = isWrittenType(item?.question.type);
  const selectedIndex = item?.selectedIndex ?? null;
  return {
    item,
    options: item?.question.options ?? [],
    selectedIndex,
    written,
    format: written ? (item?.question.type as QuestionType) : "multiple_choice",
    hasAnswer: written ? Boolean(item?.answerText?.trim()) : selectedIndex !== null,
    verdict: item?.verdict ?? null,
  };
}

/** R-2: every answer is recorded server-side either way; the feedback mode
 *  only decides whether the verdict is ever shown. At-end holds them all back
 *  until the last question is answered and every verdict is in. */
export function verdictShown(session: QuizSession, item: QuizItem | undefined): boolean {
  if (item?.verdict == null) return false;
  if (session.config.feedback === "as-you-go") return true;
  const isLast = session.cursor >= session.items.length - 1;
  return session.phase === "answered" && isLast && session.items.every(i => i.verdict !== null);
}

/** The question's own difficulty, else the quiz's, as the header shows it. */
export function difficultyLabel(item: QuizItem | undefined, session: QuizSession): string {
  return (item?.question.difficulty ?? session.config.difficulty ?? "").toUpperCase();
}

/** "Recursion · CS101", or just the concept when there is no course code. */
export function conceptLabel(concept: { name: string; courseCode: string }): string {
  return concept.courseCode ? `${concept.name} · ${concept.courseCode}` : concept.name;
}

/** The generating status' detail line ("3 questions on Recursion · medium"). */
export function generatingDetail(quizLength: number, conceptName: string, difficulty: string): string {
  return `${quizLength} questions on ${conceptName}${difficulty ? ` · ${difficulty.toLowerCase()}` : ""}`;
}

/** The pager works only on a live question, with nothing in flight. */
export function canNavigate(phase: Phase, busy: boolean, total: number): boolean {
  return (phase === "active" || phase === "answered") && !busy && total > 0;
}

/** A pager press goes somewhere: a real question other than the open one. */
export function canGoTo(index: number, cursor: number, total: number, navigable: boolean): boolean {
  return navigable && index !== cursor && index >= 0 && index < total;
}

export type PrimaryAction = "none" | "next" | "submit";

export interface PrimaryButton {
  label: string;
  testid: "quiz-next" | "quiz-submit-answer";
  enabled: boolean;
  action: PrimaryAction;
}

/** The single footer button: one element, three jobs. */
export function primaryButton({
  phase,
  showVerdict,
  allAnswered,
  busy,
  hasAnswer,
}: {
  phase: Phase;
  showVerdict: boolean;
  allAnswered: boolean;
  busy: boolean;
  hasAnswer: boolean;
}): PrimaryButton {
  if (phase === "submitting") {
    // The element keeps the identity of the press that started the scoring:
    // Next/See results in as-you-go, Submit on the last at-end item.
    return { label: "Scoring…", testid: showVerdict ? "quiz-next" : "quiz-submit-answer", enabled: false, action: "none" };
  }
  // `answered` without a shown verdict is an at-end question the student
  // came back to: its answer is recorded and locked, so the way on is Next.
  // "See results" once nothing is left to answer — not merely on the last
  // question, since questions can now be answered out of order.
  if (showVerdict || phase === "answered") {
    return { label: allAnswered ? "See results" : "Next", testid: "quiz-next", enabled: phase === "answered", action: "next" };
  }
  return { label: "Submit", testid: "quiz-submit-answer", enabled: phase === "active" && !busy && hasAnswer, action: "submit" };
}

/** Nothing is left to answer, in any order. */
export function everyAnswered(items: QuizItem[]): boolean {
  return items.every(i => !isUnanswered(i));
}

/** How the outcome is written on the answer and the feedback line. */
export function outcomeOf(verdict: Verdict | null): Outcome | undefined {
  if (!verdict) return undefined;
  return verdict.isCorrect ? "correct" : "incorrect";
}

/** How answer row `index` is painted, given the verdict once it is shown. */
export function optionState(index: number, selectedIndex: number | null, shown: Verdict | null): AnswerState {
  if (!shown) return selectedIndex === index ? "selected" : "default";
  if (index === shown.correctIndex) return "correct";
  if (index === selectedIndex) return "chosen-wrong";
  return "muted";
}

/** The outcome written on the chosen row (only), once the verdict is shown. */
export function optionStatus(index: number, selectedIndex: number | null, shown: Verdict | null): "Correct" | "Incorrect" | undefined {
  if (!shown || index !== selectedIndex) return undefined;
  return shown.isCorrect ? "Correct" : "Incorrect";
}

/** Arrow keys move the selection: down/right forward, up/left back. */
export function arrowStep(key: string): 1 | -1 | 0 {
  if (key === "ArrowDown" || key === "ArrowRight") return 1;
  if (key === "ArrowUp" || key === "ArrowLeft") return -1;
  return 0;
}

/** Where an arrow lands, wrapping; with nothing chosen it starts from the edge. */
export function nextOptionIndex(selectedIndex: number | null, step: 1 | -1, count: number): number {
  const from = selectedIndex ?? (step > 0 ? -1 : 0);
  return (from + step + count) % count;
}

/** The grading rules shown under a written answer, per format. */
export function formatHint(type: QuestionType | undefined): string {
  if (type === "symbolic") {
    return "Enter an expression using single-letter variables, + − * / ^ and parentheses, with whole-number powers from −8 to 8. For example, 2(x + 1) and 2x + 2 are equivalent wherever both are defined. Functions and equations are not supported.";
  }
  if (type === "numeric") {
    return "Enter only the number, without units. Equivalent fractions, decimals, percentages, and scientific notation are accepted. Follow the rounding requested in the question.";
  }
  return "Write a brief answer. Capitalization and extra spacing do not affect your score.";
}

/** The key as the end of a sentence: one full stop, unless it already ends in
 *  terminal punctuation ("Why?" stays "Why?", never "Why?." or "respiration. ."). */
export function withFullStop(answer: string): string {
  const key = answer.trim();
  return /[.!?]$/.test(key) ? key : `${key}.`;
}

/** The miss line in plain text (the algebra key is typeset separately). */
export function missLine(correctAnswer: string | null | undefined, correctLabel: string | undefined): string {
  if (correctAnswer) return `Not quite — the expected answer is ${withFullStop(correctAnswer)}`;
  if (correctLabel) return `Not quite — the answer is ${correctLabel}.`;
  return "Not quite.";
}

/** The option the verdict names as correct. `correct_index` is -1 for a
 *  malformed item with no correct option, so there may be none. */
export function correctOption(verdict: Verdict | null, options: WireOption[]): WireOption | undefined {
  return verdict && verdict.correctIndex >= 0 ? options[verdict.correctIndex] : undefined;
}

function chosenOption(view: ItemView): WireOption | undefined {
  return view.selectedIndex !== null ? view.options[view.selectedIndex] : undefined;
}

function chosenText(view: ItemView): string {
  if (view.written) return view.item?.answerText ?? "nothing";
  return chosenOption(view)?.text ?? "nothing";
}

/** What the tutor sheet is told about the question it is opened on. */
export function askSeedFor(view: ItemView): AskSeed {
  const { verdict } = view;
  const correct = correctOption(verdict, view.options);
  return {
    stem: view.item?.question.question ?? "",
    chosenLabel: chosenOption(view)?.label ?? "—",
    chosenText: chosenText(view),
    correctLabel: correct?.label ?? "—",
    correctText: verdict?.correctAnswer ?? correct?.text ?? "",
    explanation: verdict?.explanation ?? "",
    written: view.written,
  };
}
