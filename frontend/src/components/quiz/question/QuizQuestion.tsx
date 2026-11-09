"use client";

/**
 * The question screen (§5 B2) — everything between "we have a quiz" and "we
 * have a score": `generating`, `active`, `answered`, `confirm-leave`,
 * `submitting`.
 *
 * Two things it is built around.
 *
 * NOTHING ORPHANS THE ATTEMPT. There is exactly one exit — the leave dialog —
 * and it goes through `CONFIRM_LEAVE`, which persists the session before it
 * navigates. "Ask about this" opens the tutor in a `Sheet` ON TOP of the
 * question rather than navigating to `/learn`, which is what the old screen
 * did and what silently threw away every answer given so far. Closing the
 * sheet leaves the question exactly as it was, down to the focus ring.
 *
 * NOTHING MOVES WHEN A STATE CHANGES. The stem reserves its height, the
 * verdict line reserves its height, every answer row reserves the ✓/✕ slot and
 * the 2px selection bar, the flag link is always rendered (R-11), and the
 * footer's primary button is ONE element whose label and testid swap in place
 * (Submit → Next → See results → Scoring…). A quiz that jumps under the cursor
 * between "choose" and "submit" is how you mis-click an answer.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, ChevronLeft, ChevronRight, Hash, Library, ListChecks, PenLine, Sigma, Sparkles } from "lucide-react";
import { AnswerOption, Badge, Button, ProgressDots, type AnswerState } from "@/components/ui";
import { ConceptNode } from "@/components/graph/ConceptNode";
import { useToast } from "@/components/ToastProvider";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import type { QuizConfig, QuizSession } from "@/lib/quiz/types";
import { isWrittenType } from "@/lib/quiz/types";
import { isUnanswered } from "@/lib/quiz/machine";
import { expressionParts, superscriptParts, type ExpressionPart } from "@/lib/quiz/answerFormats";
import { WrittenAnswer, type WrittenType } from "./WrittenAnswer";
import { AskPanel, type AskSeed } from "./AskPanel";
import { LeaveDialog } from "./LeaveDialog";
import "./question.css";

export interface QuizConceptSummary {
  id: string;
  name: string;
  courseCode: string;
  color: string;
  tier: string;
  mastery: number;
}

export interface QuizQuestionProps {
  session: QuizSession;
  actions: QuizActions;
  config: QuizConfig | null;
  concept: QuizConceptSummary;
  userId: string;
  courseId: string | null;
  /**
   * A quiz call is in flight (`useQuizSession`'s `pending`).
   *
   * The phase cannot say this: it stays `active` for the whole `/answer` round
   * trip, so `phase !== "active"` is false exactly when the request IS running.
   * Submit needs this to show its in-flight state honestly. It is not a
   * correctness guard — the hook already refuses a second `/answer` for the same
   * item, and the reducer drops a duplicate response (#537 A2 fix round 2).
   * Optional so the current render keeps compiling until it reads this.
   */
  pending?: boolean;
}

/** The header mark, at the size §3 pins for a `dot`. */
const HEADER_DOT = 15;
/** `A`…`F` — the answer shortcuts. Six covers every count `/config` offers and
 *  degrades harmlessly on a question with fewer options. */
const SHORTCUT_LETTERS = "abcdef";
const SHORTCUT_DIGITS = "123456";

/** Which option a keypress means, or null if the key isn't a shortcut. */
export function shortcutIndex(key: string): number | null {
  if (key.length !== 1) return null;
  const letter = SHORTCUT_LETTERS.indexOf(key.toLowerCase());
  if (letter >= 0) return letter;
  const digit = SHORTCUT_DIGITS.indexOf(key);
  return digit >= 0 ? digit : null;
}

/** Keystrokes belong to a field, not to the quiz, when one is focused. React
 *  portals bubble events through the React TREE, so the AskPanel's composer
 *  sits "inside" this screen as far as the handler is concerned. */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

/** What each format is called on screen — the same names the Format setting
 *  uses, so "Algebra" in the settings is "Algebra" on the question. */
const FORMAT_TAG: Record<string, { label: string; Icon: typeof ListChecks }> = {
  multiple_choice: { label: "Multiple choice", Icon: ListChecks },
  short_answer: { label: "Short answer", Icon: PenLine },
  numeric: { label: "Numeric", Icon: Hash },
  symbolic: { label: "Algebra", Icon: Sigma },
};

/** Where the question's grounding came from, said plainly. */
const MATERIAL_CONTEXT = {
  course_material: { text: "Course material provided for this question", Icon: BookOpen },
  catalog: { text: "Course catalog context provided", Icon: Library },
  general: { text: "General practice: no matching course material was found", Icon: Sparkles },
} as const;

/** Parts with `<sup>` for the raised ones. */
function renderParts(parts: ExpressionPart[]): React.ReactNode {
  return parts.map((part, i) =>
    part.sup ? <sup key={i}>{part.text}</sup> : <React.Fragment key={i}>{part.text}</React.Fragment>,
  );
}

/** The key as the end of a sentence: one full stop, unless it already ends in
 *  terminal punctuation ("Why?" stays "Why?", never "Why?." or "respiration. ."). */
function withFullStop(answer: string): string {
  const key = answer.trim();
  return /[.!?]$/.test(key) ? key : `${key}.`;
}

export function QuizQuestion({
  session,
  actions,
  concept,
  userId,
  courseId,
  pending = false,
}: QuizQuestionProps) {
  const toast = useToast();

  const rootRef = useRef<HTMLDivElement>(null);
  const optionsRef = useRef<HTMLDivElement>(null);
  const feedbackRef = useRef<HTMLDivElement>(null);
  const askRef = useRef<HTMLButtonElement>(null);
  const shortToastRef = useRef<string | null>(null);

  /**
   * The tutor sheet, remembered per QUESTION rather than as a bare boolean: a
   * new item derives it closed, because the panel is seeded from one verdict
   * and carrying it across would be answering the wrong question.
   */
  const [askForCursor, setAskForCursor] = useState<number | null>(null);

  const { phase, cursor, items } = session;
  const item = items[cursor];
  const total = items.length;
  const options = item?.question.options ?? [];
  const selectedIndex = item?.selectedIndex ?? null;
  const written = isWrittenType(item?.question.type);
  // A type this client doesn't know is answered by choosing, exactly as the
  // backend treats it, so it wears the multiple-choice tag too.
  const format = written ? (item?.question.type as string) : "multiple_choice";
  const formatTag = FORMAT_TAG[format] ?? FORMAT_TAG.multiple_choice;
  const hasAnswer = written ? Boolean(item?.answerText?.trim()) : selectedIndex !== null;
  const answeredCount = items.filter(i => i.verdict !== null).length;
  const isLast = cursor >= total - 1;
  // R-2: every answer is recorded server-side either way; the feedback mode
  // only decides whether the verdict is ever shown.
  const showVerdict = item?.verdict != null && (session.config.feedback === "as-you-go"
    || (phase === "answered" && isLast && items.every(i => i.verdict !== null)));

  /**
   * A quiz call is in flight. Straight off the hook (`useQuizSession`'s
   * `pending`, on the props since A2's fix round 4): the phase can't say it,
   * because it stays `active` for the whole `/answer` round trip — and the
   * hook is the only thing that knows about the calls it refuses (a missing
   * `attemptId`, a duplicate press), so a screen-local latch would stay stuck
   * on exactly those.
   */
  const busy = pending;
  // Derived, so a new question is the only thing that closes the sheet.
  const askOpen = askForCursor === cursor;
  const selectable = phase === "active" && !busy;

  // A blank accent would reach `shadeFor` as an unparseable colour and pass
  // straight through; the CSS variable degrades to the app accent instead.
  const accent = concept.color || "var(--quiz-accent, var(--accent))";
  const difficulty = (item?.question.difficulty ?? session.config.difficulty ?? "").toUpperCase();
  const quizLength = total || session.config.count;

  // ── Effects ──────────────────────────────────────────────────────────

  // The keyboard map is attached to the screen root, so the root has to hold
  // focus for it to hear anything before the student clicks. Moving focus onto
  // each new question is also the right announcement. A written question
  // focuses its answer input instead, so the student can start typing: the
  // input is labelled by the stem, so the question is still what is read out.
  useEffect(() => {
    if (phase !== "active") return;
    const input = written ? document.getElementById("quiz-written-answer") : null;
    (input ?? rootRef.current)?.focus();
  }, [phase, cursor, written]);

  // ...and when the verdict lands, focus moves to the line that carries it, so
  // a screen reader hears the result. Nothing else on the screen moves.
  useEffect(() => {
    if (!showVerdict) return;
    feedbackRef.current?.focus();
  }, [showVerdict, cursor]);

  // One toast per attempt, on arrival (§5 B2).
  useEffect(() => {
    const attemptId = session.attemptId;
    if (!session.deliveredShort || !attemptId || total === 0) return;
    if (shortToastRef.current === attemptId) return;
    shortToastRef.current = attemptId;
    toast.show(`Only ${total} questions were ready for this concept.`);
  }, [session.deliveredShort, session.attemptId, total, toast]);

  // ── Actions ──────────────────────────────────────────────────────────

  const submit = useCallback(() => {
    if (phase !== "active" || busy || !hasAnswer) return;
    actions.submitAnswer();
  }, [actions, busy, phase, hasAnswer]);

  const flag = () => {
    const wasFlagged = item?.flagged ?? false;
    actions.flag();
    // Un-flagging is a correction, not a report — thanking for it reads as a
    // bug. Only raising the flag says anything.
    if (!wasFlagged) toast.show("Noted — thanks.");
  };

  const focusOption = (index: number) => {
    optionsRef.current?.querySelectorAll<HTMLElement>('[role="radio"]')[index]?.focus();
  };

  /** The single footer button: one element, three jobs. */
  const primary = useMemo(() => {
    if (phase === "submitting") {
      return {
        label: "Scoring…",
        // The element keeps the identity of the press that started the
        // scoring: Next/See results in as-you-go, Submit on the last at-end item.
        testid: showVerdict ? "quiz-next" : "quiz-submit-answer",
        enabled: false,
        activate: () => {},
      };
    }
    // "See results" once nothing is left to answer — not merely on the last
    // question, since questions can now be answered out of order.
    const allAnswered = items.every(i => !isUnanswered(i));
    if (showVerdict || phase === "answered") {
      // `answered` without a shown verdict is an at-end question the student
      // came back to: its answer is recorded and locked, so the way on is Next.
      return {
        label: allAnswered ? "See results" : "Next",
        testid: "quiz-next",
        enabled: phase === "answered",
        activate: () => actions.next(),
      };
    }
    return {
      label: "Submit",
      testid: "quiz-submit-answer",
      enabled: phase === "active" && !busy && hasAnswer,
      activate: submit,
    };
  }, [actions, busy, items, phase, hasAnswer, showVerdict, submit]);

  // ── Keyboard (§5 B2) ─────────────────────────────────────────────────

  const onRootKeyDown = (e: React.KeyboardEvent) => {
    // The sheet and the dialog own the keyboard while they are open — and both
    // are portals, whose events still bubble through the React tree to here.
    if (askOpen || phase === "confirm-leave") return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (isTypingTarget(e.target)) return;

    if (e.key === "Escape") {
      if (phase !== "active" && phase !== "answered") return;
      e.preventDefault();
      actions.requestLeave();
      return;
    }

    if (e.key === "Enter") {
      // Enter is the footer's action everywhere on this screen, including on
      // an answer row — `AnswerOption` is a <button>, so its own Enter-to-select
      // is deliberately pre-empted here. Choosing is A–F / 1–6, the arrow keys,
      // Space, or a click.
      if (!primary.enabled) return;
      e.preventDefault();
      primary.activate();
      return;
    }

    if (!selectable) return;
    const index = shortcutIndex(e.key);
    if (index === null || index >= options.length) return;
    e.preventDefault();
    // Focus deliberately stays on the root: a shortcut is a hands-on-keyboard
    // gesture, and the very next key is usually Enter.
    actions.select(index);
  };

  const onOptionsKeyDown = (e: React.KeyboardEvent) => {
    if (!selectable || options.length === 0) return;
    const step =
      e.key === "ArrowDown" || e.key === "ArrowRight"
        ? 1
        : e.key === "ArrowUp" || e.key === "ArrowLeft"
          ? -1
          : 0;
    if (step === 0) return;
    e.preventDefault();
    e.stopPropagation();
    const from = selectedIndex ?? (step > 0 ? -1 : 0);
    const next = (from + step + options.length) % options.length;
    actions.select(next);
    focusOption(next);
  };

  // ── Pieces shared by the generating and the live render ──────────────

  // Where the student is in the quiz, and the way round it: a numbered button
  // per question (green / red once marked, in as-you-go mode) between back and
  // forward arrows, beside the footer's primary button. Any question can be
  // opened — one already answered shows what was recorded (answers lock once
  // the server has them), one ahead can be answered out of order.
  const position = Math.min(cursor + 1, quizLength);
  const canNavigate = (phase === "active" || phase === "answered") && !busy && total > 0;
  const goTo = (index: number) => {
    if (canNavigate && index !== cursor && index >= 0 && index < total) actions.goTo?.(index);
  };
  const progress = (
    <nav className="quiz-question__progress" aria-label="Questions">
      <button
        type="button"
        className="quiz-question__step"
        data-testid="quiz-prev-question"
        aria-label="Previous question"
        disabled={!canNavigate || cursor <= 0}
        onClick={() => goTo(cursor - 1)}
      >
        <ChevronLeft size={16} aria-hidden="true" />
      </button>
      <ProgressDots
        total={quizLength}
        // Nothing is "here" yet while the quiz is still being written.
        current={total === 0 ? -1 : cursor}
        answered={total === 0 ? 0 : answeredCount}
        // Out of order once questions can be skipped: answered isn't a prefix.
        done={items.map(i => !isUnanswered(i))}
        // As-you-go shows each verdict, so the pager keeps the tally too.
        // At-end holds every verdict back, and the pager must not leak them.
        outcomes={session.config.feedback === "as-you-go"
          ? items.map(i => (i.verdict ? i.verdict.isCorrect : null))
          : undefined}
        orientation="row"
        onSelect={goTo}
        disabled={!canNavigate}
        ariaLabel={`Question ${position} of ${quizLength}`}
        testid="quiz-progress"
      />
      <button
        type="button"
        className="quiz-question__step"
        data-testid="quiz-next-question"
        aria-label="Next question"
        disabled={!canNavigate || cursor >= total - 1}
        onClick={() => goTo(cursor + 1)}
      >
        <ChevronRight size={16} aria-hidden="true" />
      </button>
    </nav>
  );

  const header = (
    <div className="quiz-question__header">
      <ConceptNode
        size={HEADER_DOT}
        mastery={concept.mastery}
        tier={concept.tier}
        courseColor={accent}
        nodeId={concept.id || concept.name}
      />
      <span className="quiz-question__concept">
        {concept.courseCode ? `${concept.name} · ${concept.courseCode}` : concept.name}
      </span>
      <span className="quiz-question__header-gap" />
      {phase !== "generating" && item && (
        <span className="quiz-question__format" data-testid="quiz-format-tag" data-format={format}>
          <formatTag.Icon size={13} strokeWidth={2} aria-hidden="true" />
          {formatTag.label}
        </span>
      )}
      {difficulty && <Badge bg="var(--bg-soft)">{difficulty}</Badge>}
    </div>
  );

  // ── generating ───────────────────────────────────────────────────────

  if (phase === "generating") {
    return (
      <div className="quiz-question" data-testid="quiz-generating">
        <div className="quiz-question__col">
          {header}
          {/* A status, not a skeleton: the questions don't exist yet, so a
              ghost of their layout promised a shape that the real quiz then
              replaced. The bar is paced to a typical generation (one model
              call, ~5–10 s) and never claims to be done until the quiz is —
              /generate answers in one piece, so there is no finer signal. */}
          <div className="quiz-generating" role="status">
            <p className="quiz-generating__title h-serif">Writing your quiz</p>
            <p className="quiz-generating__detail">
              {`${quizLength} questions on ${concept.name}${difficulty ? ` · ${difficulty.toLowerCase()}` : ""}`}
            </p>
            <div className="quiz-generating__bar" aria-hidden="true">
              <span className="quiz-generating__fill" />
            </div>
            <p className="quiz-generating__slow">Still writing. Longer quizzes take a little more time.</p>
          </div>
          <div className="quiz-question__grow" />
          {/* #760: a generation that never answers must not be a dead end. */}
          <div className="quiz-question__footer">
            <Button data-testid="quiz-cancel-generate" onClick={() => actions.cancel()}>
              Cancel
            </Button>
            {progress}
          </div>
        </div>
      </div>
    );
  }

  // ── active | answered | confirm-leave | submitting ───────────────────

  const verdict = item?.verdict ?? null;
  // `correct_index` is -1 for a malformed item with no correct option, so the
  // letter is optional and the copy has to survive without it.
  const correctLabel =
    verdict && verdict.correctIndex >= 0 ? options[verdict.correctIndex]?.label : undefined;

  const context = item?.question.material_context ? MATERIAL_CONTEXT[item.question.material_context] : null;

  const optionState = (index: number): AnswerState => {
    if (!showVerdict || !verdict) return selectedIndex === index ? "selected" : "default";
    if (index === verdict.correctIndex) return "correct";
    if (index === selectedIndex) return "chosen-wrong";
    return "muted";
  };

  const askSeed: AskSeed = {
    stem: item?.question.question ?? "",
    chosenLabel: (selectedIndex !== null ? options[selectedIndex]?.label : undefined) ?? "—",
    chosenText: written ? item?.answerText ?? "nothing" : (selectedIndex !== null ? options[selectedIndex]?.text : undefined) ?? "nothing",
    correctLabel: correctLabel ?? "—",
    correctText:
      verdict?.correctAnswer ?? (verdict && verdict.correctIndex >= 0 ? options[verdict.correctIndex]?.text : undefined) ?? "",
    explanation: verdict?.explanation ?? "",
  };

  return (
    <div
      ref={rootRef}
      className="quiz-question"
      data-testid="quiz-panel"
      data-phase={phase}
      tabIndex={-1}
      onKeyDown={onRootKeyDown}
    >
      <div className="quiz-question__col">
        {header}

        {/* Keyed on the question, so each one arrives with the same short
            entrance — from the generating panel, from Next, from the pager. */}
        <div className="quiz-question__body" key={item?.question.id ?? cursor}>
        <div className="quiz-question__prompt">
        <h2 className="quiz-question__stem h-serif" id="quiz-question-stem">
          {/* An algebra stem carries its maths as typed (`(x + 1)^2`); raise
              the exponents so the question reads the way it would be printed. */}
          {format === "symbolic"
            ? renderParts(superscriptParts(item?.question.question ?? ""))
            : item?.question.question ?? ""}
        </h2>
        {context && (
          <p className="quiz-question__context" data-testid="quiz-material-context">
            <context.Icon size={13} strokeWidth={2} aria-hidden="true" />
            {context.text}
          </p>
        )}
        </div>

        {!written && (
          <p className="quiz-question__hint" id="quiz-keyboard-hint">
            Keyboard: press A to F, or 1 to 6, to choose an answer. Enter submits your answer and
            moves to the next question. Escape leaves the quiz.
          </p>
        )}

        {written ? (
          <div
            className={`quiz-question__written quiz-question__written--${format}`}
            data-marked={showVerdict && verdict ? "true" : undefined}
          >
            {/* The accessible name ("Your answer, <stem>"); on screen the format
                tag and the field's own shape already say what goes here. */}
            <label htmlFor="quiz-written-answer" className="quiz-question__sr" id="quiz-written-label">Your answer</label>
            <WrittenAnswer
              type={(item?.question.type ?? "short_answer") as WrittenType}
              value={item?.answerText ?? ""}
              disabled={!selectable}
              verdict={showVerdict && verdict ? (verdict.isCorrect ? "correct" : "incorrect") : null}
              onChange={text => actions.write?.(text)}
              onSubmit={() => {
                if (primary.enabled) primary.activate();
              }}
              describedBy="quiz-format-hint"
              labelledBy="quiz-written-label quiz-question-stem"
            />
            {/* Visible, unlike the keyboard hint: these are the rules the
                grader applies, so a sighted student needs them as much as a
                screen-reader user does. */}
            <p className="quiz-question__format-hint" id="quiz-format-hint" data-testid="quiz-format-hint">
              {item?.question.type === "symbolic"
                ? "Enter an expression using single-letter variables, + − * / ^ and parentheses, with whole-number powers from −8 to 8. For example, 2(x + 1) and 2x + 2 are equivalent wherever both are defined. Functions and equations are not supported."
                : item?.question.type === "numeric"
                  ? "Enter only the number, without units. Equivalent fractions, decimals, percentages, and scientific notation are accepted. Follow the rounding requested in the question."
                  : "Write a brief answer. Capitalization and extra spacing do not affect your score."}
            </p>
          </div>
        ) : <div
          ref={optionsRef}
          className="quiz-question__options"
          role="radiogroup"
          aria-label="Answer choices"
          aria-describedby="quiz-keyboard-hint"
          data-testid="quiz-answer-options"
          onKeyDown={onOptionsKeyDown}
        >
          {options.map((option, index) => (
            <AnswerOption
              key={option.label}
              letter={option.label}
              text={option.text}
              state={optionState(index)}
              status={showVerdict && verdict && index === selectedIndex
                ? (verdict.isCorrect ? "Correct" : "Incorrect")
                : undefined}
              disabled={!selectable}
              onSelect={() => actions.select(index)}
              // The group owns one tab stop: the chosen row, or the first row
              // while nothing is chosen.
              tabIndex={index === (selectedIndex ?? 0) ? 0 : -1}
              testid={`quiz-answer-option-${option.label}`}
            />
          ))}
        </div>}

        <div
          ref={feedbackRef}
          className="quiz-question__feedback"
          data-testid="quiz-review-verdict"
          data-outcome={showVerdict && verdict ? (verdict.isCorrect ? "correct" : "incorrect") : undefined}
          aria-live="polite"
          tabIndex={-1}
        >
          {showVerdict && verdict && (
            <>
              {/* On screen the outcome sits on the answer itself (the chosen
                  tile, or the written field); this is the line the live
                  region announces. */}
              <p className="quiz-question__sr" data-testid="quiz-verdict-outcome">
                {verdict.isCorrect ? "Correct." : "Incorrect."}
              </p>
              {/* The card is the reading: what the answer was, and why. */}
              {(!verdict.isCorrect || verdict.explanation) && (
              <div className="card quiz-question__verdict-card">
              {!verdict.isCorrect && (
                <p className="quiz-question__verdict-line h-sans">
                  {verdict.correctAnswer && format === "symbolic"
                      ? <>Not quite — the expected answer is{" "}
                          <span className="quiz-question__verdict-expr">{renderParts(expressionParts(verdict.correctAnswer.trim().replace(/[.]$/, "")))}</span>.</>
                    : verdict.correctAnswer
                      ? `Not quite — the expected answer is ${withFullStop(verdict.correctAnswer)}`
                    : correctLabel
                      ? `Not quite — the answer is ${correctLabel}.`
                      : "Not quite."}
                </p>
              )}
              {verdict.explanation && (
                <p className="quiz-question__explanation body-serif">{verdict.explanation}</p>
              )}
              </div>
              )}
            </>
          )}
        </div>

        <div className="quiz-question__aside">
          <Button
            variant="link"
            className="quiz-question__flag"
            aria-pressed={item?.flagged ?? false}
            data-testid="quiz-flag"
            onClick={flag}
          >
            This question is confusing
          </Button>
          {phase === "answered" && (
            <Button
              ref={askRef}
              size="sm"
              data-testid="quiz-ask"
              onClick={() => setAskForCursor(cursor)}
            >
              Ask about this
            </Button>
          )}
        </div>

        </div>

        <div className="quiz-question__grow" />

        <div className="quiz-question__footer">
          {phase === "submitting" ? (
            // #760: Leave is refused mid-score (the attempt is live), so this is
            // the way off "Scoring…" — back onto the final verdict, from where
            // See results and Leave both work again.
            <Button data-testid="quiz-cancel-submit" onClick={() => actions.cancel()}>
              Cancel
            </Button>
          ) : (
            <Button data-testid="quiz-leave" onClick={() => actions.requestLeave()}>
              Leave
            </Button>
          )}
          {progress}
          <Button
            variant="primary"
            data-testid={primary.testid}
            aria-disabled={!primary.enabled}
            disabled={!primary.enabled}
            onClick={primary.activate}
          >
            {primary.label}
          </Button>
        </div>
      </div>

      <LeaveDialog
        open={phase === "confirm-leave"}
        onCancel={() => actions.cancelLeave()}
        onConfirm={() => actions.confirmLeave()}
      />

      <AskPanel
        open={askOpen}
        onClose={() => setAskForCursor(null)}
        userId={userId}
        conceptName={concept.name}
        courseId={courseId}
        courseLabel={concept.courseCode || undefined}
        seed={askSeed}
        returnFocusTo={askRef}
      />
    </div>
  );
}
