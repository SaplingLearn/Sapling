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
import { AnswerOption, Badge, Button, ProgressDots } from "@/components/ui";
import { ConceptNode } from "@/components/graph/ConceptNode";
import { ConfidenceControl } from "@/components/learn/ConfidenceControl";
import { useToast } from "@/components/ToastProvider";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import type { Phase, QuestionType, QuizConfig, QuizItem, QuizSession } from "@/lib/quiz/types";
import { isUnanswered } from "@/lib/quiz/machine";
import { expressionParts, superscriptParts, type ExpressionPart } from "@/lib/quiz/answerFormats";
import { WrittenAnswer, type WrittenType } from "./WrittenAnswer";
import { AskPanel } from "./AskPanel";
import { LeaveDialog } from "./LeaveDialog";
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
  type ItemView,
  type PrimaryAction,
  type PrimaryButton,
  type Verdict,
} from "./questionView";
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

type ToastApi = ReturnType<typeof useToast>;

/** The footer button with its press bound to the session. */
type Primary = PrimaryButton & { activate: () => void };

// ── Hooks ──────────────────────────────────────────────────────────────

/**
 * Where focus goes as the screen changes. Returns the two elements it moves
 * focus onto: the screen root and the verdict line.
 */
function useQuestionFocus(phase: Phase, cursor: number, written: boolean, showVerdict: boolean) {
  const rootRef = useRef<HTMLDivElement>(null);
  const feedbackRef = useRef<HTMLDivElement>(null);

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

  return { rootRef, feedbackRef };
}

/** One toast per attempt, on arrival (§5 B2). */
function useShortQuizToast(session: QuizSession, total: number, toast: ToastApi) {
  const shortToastRef = useRef<string | null>(null);
  useEffect(() => {
    const attemptId = session.attemptId;
    if (!session.deliveredShort || !attemptId || total === 0) return;
    if (shortToastRef.current === attemptId) return;
    shortToastRef.current = attemptId;
    toast.show(`Only ${total} questions were ready for this concept.`);
  }, [session.deliveredShort, session.attemptId, total, toast]);
}

/** The single footer button: one element, three jobs. */
function usePrimary({
  actions,
  busy,
  items,
  phase,
  hasAnswer,
  showVerdict,
}: {
  actions: QuizActions;
  busy: boolean;
  items: QuizItem[];
  phase: Phase;
  hasAnswer: boolean;
  showVerdict: boolean;
}): Primary {
  const submit = useCallback(() => {
    if (phase !== "active" || busy || !hasAnswer) return;
    actions.submitAnswer();
  }, [actions, busy, phase, hasAnswer]);

  return useMemo(() => {
    const button = primaryButton({ phase, showVerdict, allAnswered: everyAnswered(items), busy, hasAnswer });
    const presses: Record<PrimaryAction, () => void> = {
      none: () => {},
      next: () => actions.next(),
      submit,
    };
    return { ...button, activate: presses[button.action] };
  }, [actions, busy, items, phase, hasAnswer, showVerdict, submit]);
}

// ── Keyboard (§5 B2) ───────────────────────────────────────────────────

interface RootKeyContext {
  askOpen: boolean;
  phase: Phase;
  primary: Primary;
  selectable: boolean;
  optionCount: number;
  actions: QuizActions;
  confidenceRef: React.RefObject<HTMLDivElement | null>;
}

/** The sheet and the dialog own the keyboard while they are open — and both
 *  are portals, whose events still bubble through the React tree to here. */
function keyboardIsElsewhere(e: React.KeyboardEvent, { askOpen, phase }: RootKeyContext): boolean {
  if (askOpen || phase === "confirm-leave") return true;
  if (e.metaKey || e.ctrlKey || e.altKey) return true;
  return isTypingTarget(e.target);
}

function leaveOnEscape(e: React.KeyboardEvent, { phase, actions }: RootKeyContext) {
  if (phase !== "active" && phase !== "answered") return;
  e.preventDefault();
  actions.requestLeave();
}

/** Enter is the footer's action everywhere on this screen, including on an
 *  answer row — `AnswerOption` is a <button>, so its own Enter-to-select is
 *  deliberately pre-empted here. Choosing is A–F / 1–6, the arrow keys,
 *  Space, or a click. */
function activateOnEnter(e: React.KeyboardEvent, { primary }: RootKeyContext) {
  if (!primary.enabled) return;
  e.preventDefault();
  primary.activate();
}

function selectByShortcut(e: React.KeyboardEvent, { optionCount, actions }: RootKeyContext) {
  const index = shortcutIndex(e.key);
  if (index === null || index >= optionCount) return;
  e.preventDefault();
  // Focus deliberately stays on the root: a shortcut is a hands-on-keyboard
  // gesture, and the very next key is usually Enter.
  actions.select(index);
}

/** The confidence group owns its keys (learning-loop spec §13 A127 (b),
 *  A132): Enter or Space on a level chooses it rather than submitting, and a
 *  letter there is not an answer shortcut. Escape still leaves. */
function confidenceOwnsKey(e: React.KeyboardEvent, { confidenceRef }: RootKeyContext): boolean {
  if (e.key === "Escape" || !(e.target instanceof Node)) return false;
  return Boolean(confidenceRef.current?.contains(e.target));
}

function handleRootKey(e: React.KeyboardEvent, ctx: RootKeyContext) {
  if (keyboardIsElsewhere(e, ctx) || confidenceOwnsKey(e, ctx)) return;
  if (e.key === "Escape") leaveOnEscape(e, ctx);
  else if (e.key === "Enter") activateOnEnter(e, ctx);
  else if (ctx.selectable) selectByShortcut(e, ctx);
}

// ── Pieces shared by the generating and the live render ────────────────

function QuestionHeader({
  concept,
  format,
  showFormat,
  difficulty,
}: {
  concept: QuizConceptSummary;
  format: QuestionType;
  showFormat: boolean;
  difficulty: string;
}) {
  const formatTag = FORMAT_TAG[format] ?? FORMAT_TAG.multiple_choice;
  // A blank accent would reach `shadeFor` as an unparseable colour and pass
  // straight through; the CSS variable degrades to the app accent instead.
  const accent = concept.color || "var(--quiz-accent, var(--accent))";
  return (
    <div className="quiz-question__header">
      <ConceptNode
        size={HEADER_DOT}
        mastery={concept.mastery}
        tier={concept.tier}
        courseColor={accent}
        nodeId={concept.id || concept.name}
      />
      <span className="quiz-question__concept">
        {conceptLabel(concept)}
      </span>
      <span className="quiz-question__header-gap" />
      {showFormat && (
        <span className="quiz-question__format" data-testid="quiz-format-tag" data-format={format}>
          <formatTag.Icon size={13} strokeWidth={2} aria-hidden="true" />
          {formatTag.label}
        </span>
      )}
      {difficulty && <Badge bg="var(--bg-soft)">{difficulty}</Badge>}
    </div>
  );
}

/**
 * Where the student is in the quiz, and the way round it: a numbered button
 * per question (green / red once marked, in as-you-go mode) between back and
 * forward arrows, beside the footer's primary button. Any question can be
 * opened — one already answered shows what was recorded (answers lock once
 * the server has them), one ahead can be answered out of order.
 */
function QuestionPager({
  session,
  actions,
  busy,
  quizLength,
}: {
  session: QuizSession;
  actions: QuizActions;
  busy: boolean;
  quizLength: number;
}) {
  const { phase, cursor, items } = session;
  const total = items.length;
  const position = Math.min(cursor + 1, quizLength);
  const navigable = canNavigate(phase, busy, total);
  const goTo = (index: number) => {
    if (canGoTo(index, cursor, total, navigable)) actions.goTo?.(index);
  };
  return (
    <nav className="quiz-question__progress" aria-label="Questions">
      <button
        type="button"
        className="quiz-question__step"
        data-testid="quiz-prev-question"
        aria-label="Previous question"
        disabled={!navigable || cursor <= 0}
        onClick={() => goTo(cursor - 1)}
      >
        <ChevronLeft size={16} aria-hidden="true" />
      </button>
      <ProgressDots
        total={quizLength}
        // Nothing is "here" yet while the quiz is still being written.
        current={total === 0 ? -1 : cursor}
        answered={total === 0 ? 0 : items.filter(i => i.verdict !== null).length}
        // Out of order once questions can be skipped: answered isn't a prefix.
        done={items.map(i => !isUnanswered(i))}
        // As-you-go shows each verdict, so the pager keeps the tally too.
        // At-end holds every verdict back, and the pager must not leak them.
        outcomes={session.config.feedback === "as-you-go"
          ? items.map(i => (i.verdict ? i.verdict.isCorrect : null))
          : undefined}
        orientation="row"
        onSelect={goTo}
        disabled={!navigable}
        ariaLabel={`Question ${position} of ${quizLength}`}
        testid="quiz-progress"
      />
      <button
        type="button"
        className="quiz-question__step"
        data-testid="quiz-next-question"
        aria-label="Next question"
        disabled={!navigable || cursor >= total - 1}
        onClick={() => goTo(cursor + 1)}
      >
        <ChevronRight size={16} aria-hidden="true" />
      </button>
    </nav>
  );
}

/** The way off the screen, per phase: Cancel while generating (#760: a
 *  generation that never answers must not be a dead end) and while scoring
 *  (#760: Leave is refused mid-score, since the attempt is live, so this is
 *  the way off "Scoring…" — back onto the final verdict, from where See
 *  results and Leave both work again); Leave everywhere else. */
function exitButtonFor(phase: Phase): { testid: string; label: string; leaves: boolean } {
  if (phase === "generating") return { testid: "quiz-cancel-generate", label: "Cancel", leaves: false };
  if (phase === "submitting") return { testid: "quiz-cancel-submit", label: "Cancel", leaves: false };
  return { testid: "quiz-leave", label: "Leave", leaves: true };
}

function QuestionFooter({
  phase,
  actions,
  pager,
  primary,
}: {
  phase: Phase;
  actions: QuizActions;
  pager: React.ReactNode;
  primary?: Primary;
}) {
  const exit = exitButtonFor(phase);
  return (
    <div className="quiz-question__footer">
      <Button data-testid={exit.testid} onClick={() => (exit.leaves ? actions.requestLeave() : actions.cancel())}>
        {exit.label}
      </Button>
      {pager}
      {primary && (
        <Button
          variant="primary"
          data-testid={primary.testid}
          aria-disabled={!primary.enabled}
          disabled={!primary.enabled}
          onClick={primary.activate}
        >
          {primary.label}
        </Button>
      )}
    </div>
  );
}

// ── generating ─────────────────────────────────────────────────────────

/** A status, not a skeleton: the questions don't exist yet, so a ghost of
 *  their layout promised a shape that the real quiz then replaced. The bar is
 *  paced to a typical generation (one model call, ~5–10 s) and never claims to
 *  be done until the quiz is — /generate answers in one piece, so there is no
 *  finer signal. */
function GeneratingStatus({ quizLength, conceptName, difficulty }: { quizLength: number; conceptName: string; difficulty: string }) {
  return (
    <div className="quiz-generating" role="status">
      <p className="quiz-generating__title h-serif">Writing your quiz</p>
      <p className="quiz-generating__detail">
        {generatingDetail(quizLength, conceptName, difficulty)}
      </p>
      <div className="quiz-generating__bar" aria-hidden="true">
        <span className="quiz-generating__fill" />
      </div>
      <p className="quiz-generating__slow">Still writing. Longer quizzes take a little more time.</p>
    </div>
  );
}

// ── The question ───────────────────────────────────────────────────────

function QuestionPrompt({ item, format }: { item: QuizItem | undefined; format: QuestionType }) {
  const stem = item?.question.question ?? "";
  const kind = item?.question.material_context;
  const context = kind ? MATERIAL_CONTEXT[kind] : null;
  return (
    <div className="quiz-question__prompt">
      <h2 className="quiz-question__stem h-serif" id="quiz-question-stem">
        {/* An algebra stem carries its maths as typed (`(x + 1)^2`); raise
            the exponents so the question reads the way it would be printed. */}
        {format === "symbolic" ? renderParts(superscriptParts(stem)) : stem}
      </h2>
      {context && (
        <p className="quiz-question__context" data-testid="quiz-material-context">
          <context.Icon size={13} strokeWidth={2} aria-hidden="true" />
          {context.text}
        </p>
      )}
    </div>
  );
}

/** What every answer format is handed. `shown` is the verdict once it may be
 *  shown (always null before then, and throughout an at-end quiz). */
interface AnswerFieldProps {
  view: ItemView;
  shown: Verdict | null;
  selectable: boolean;
  actions: QuizActions;
  primary: Primary;
}

/** Multiple choice (and any type this client doesn't know): a radiogroup of
 *  answer rows, chosen by click, A–F / 1–6 on the screen, or the arrows. */
function ChoiceAnswer({ view, shown, selectable, actions }: AnswerFieldProps) {
  const optionsRef = useRef<HTMLDivElement>(null);
  const { options, selectedIndex } = view;

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!selectable || options.length === 0) return;
    const step = arrowStep(e.key);
    if (step === 0) return;
    e.preventDefault();
    e.stopPropagation();
    const next = nextOptionIndex(selectedIndex, step, options.length);
    actions.select(next);
    optionsRef.current?.querySelectorAll<HTMLElement>('[role="radio"]')[next]?.focus();
  };

  return (
    <>
      <p className="quiz-question__hint" id="quiz-keyboard-hint">
        Keyboard: press A to F, or 1 to 6, to choose an answer. Enter submits your answer and
        moves to the next question. Escape leaves the quiz.
      </p>
      <div
        ref={optionsRef}
        className="quiz-question__options"
        role="radiogroup"
        aria-label="Answer choices"
        aria-describedby="quiz-keyboard-hint"
        data-testid="quiz-answer-options"
        onKeyDown={onKeyDown}
      >
        {options.map((option, index) => (
          <AnswerOption
            key={option.label}
            letter={option.label}
            text={option.text}
            state={optionState(index, selectedIndex, shown)}
            status={optionStatus(index, selectedIndex, shown)}
            disabled={!selectable}
            onSelect={() => actions.select(index)}
            // The group owns one tab stop: the chosen row, or the first row
            // while nothing is chosen.
            tabIndex={index === (selectedIndex ?? 0) ? 0 : -1}
            testid={`quiz-answer-option-${option.label}`}
          />
        ))}
      </div>
    </>
  );
}

/** Short answer, numeric and algebra: one input shaped to its format, with
 *  the grader's rules for it underneath. */
function WrittenField({ view, shown, selectable, actions, primary }: AnswerFieldProps) {
  const type = view.item?.question.type;
  return (
    <div
      className={`quiz-question__written quiz-question__written--${view.format}`}
      data-marked={shown ? "true" : undefined}
    >
      {/* The accessible name ("Your answer, <stem>"); on screen the format
          tag and the field's own shape already say what goes here. */}
      <label htmlFor="quiz-written-answer" className="quiz-question__sr" id="quiz-written-label">Your answer</label>
      <WrittenAnswer
        type={(type ?? "short_answer") as WrittenType}
        value={view.item?.answerText ?? ""}
        disabled={!selectable}
        verdict={outcomeOf(shown) ?? null}
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
        {formatHint(type)}
      </p>
    </div>
  );
}

/** One answer field per format. */
const ANSWER_FIELDS: Record<QuestionType, (props: AnswerFieldProps) => React.JSX.Element> = {
  multiple_choice: ChoiceAnswer,
  short_answer: WrittenField,
  numeric: WrittenField,
  symbolic: WrittenField,
};

function VerdictLine({ verdict, format, correctLabel }: { verdict: Verdict; format: QuestionType; correctLabel: string | undefined }) {
  return (
    <p className="quiz-question__verdict-line h-sans">
      {verdict.correctAnswer && format === "symbolic"
        ? <>Not quite — the expected answer is{" "}
            <span className="quiz-question__verdict-expr">{renderParts(expressionParts(verdict.correctAnswer.trim().replace(/[.]$/, "")))}</span>.</>
        : missLine(verdict.correctAnswer, correctLabel)}
    </p>
  );
}

function VerdictReading({ verdict, format, correctLabel }: { verdict: Verdict; format: QuestionType; correctLabel: string | undefined }) {
  return (
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
          {!verdict.isCorrect && <VerdictLine verdict={verdict} format={format} correctLabel={correctLabel} />}
          {verdict.explanation && (
            <p className="quiz-question__explanation body-serif">{verdict.explanation}</p>
          )}
        </div>
      )}
    </>
  );
}

function VerdictFeedback({
  feedbackRef,
  shown,
  format,
  correctLabel,
}: {
  feedbackRef: React.RefObject<HTMLDivElement | null>;
  shown: Verdict | null;
  format: QuestionType;
  correctLabel: string | undefined;
}) {
  return (
    <div
      ref={feedbackRef}
      className="quiz-question__feedback"
      data-testid="quiz-review-verdict"
      data-outcome={outcomeOf(shown)}
      aria-live="polite"
      tabIndex={-1}
    >
      {shown && <VerdictReading verdict={shown} format={format} correctLabel={correctLabel} />}
    </div>
  );
}

function QuestionAside({
  flagged,
  onFlag,
  canAsk,
  askRef,
  onAsk,
}: {
  flagged: boolean;
  onFlag: () => void;
  canAsk: boolean;
  askRef: React.RefObject<HTMLButtonElement | null>;
  onAsk: () => void;
}) {
  return (
    <div className="quiz-question__aside">
      <Button
        variant="link"
        className="quiz-question__flag"
        aria-pressed={flagged}
        data-testid="quiz-flag"
        onClick={onFlag}
      >
        This question is confusing
      </Button>
      {canAsk && (
        <Button
          ref={askRef}
          size="sm"
          data-testid="quiz-ask"
          onClick={onAsk}
        >
          Ask about this
        </Button>
      )}
    </div>
  );
}

/** Learning-loop spec §13 A132: A127's optional "How sure are you?" on every
 *  quiz question, either format. Choosing makes no request — the level rides
 *  this question's `/answer` — and Submit never waits on it. Rendered in every
 *  live phase so nothing moves when the verdict lands; it stops taking changes
 *  once the answer is sent. */
function QuestionConfidence({
  confidenceRef,
  item,
  selectable,
  actions,
}: {
  confidenceRef: React.RefObject<HTMLDivElement | null>;
  item: QuizItem | undefined;
  selectable: boolean;
  actions: QuizActions;
}) {
  return (
    <div ref={confidenceRef} className="quiz-question__confidence">
      <ConfidenceControl
        testIdPrefix="quiz-confidence"
        value={item?.confidence ?? null}
        onChange={level => actions.setConfidence?.(level)}
        disabled={!selectable || item?.verdict != null}
      />
    </div>
  );
}

/** The question the tutor sheet asks about, as its `quiz_ask` origin (spec
 *  §13 A99) — none before the attempt exists. */
function quizAskFor(attemptId: string | null | undefined, item: QuizItem | undefined) {
  return attemptId && item ? { attemptId, questionIndex: item.index } : undefined;
}

function flagItem(item: QuizItem | undefined, actions: QuizActions, toast: ToastApi) {
  const wasFlagged = item?.flagged ?? false;
  actions.flag();
  // Un-flagging is a correction, not a report — thanking for it reads as a
  // bug. Only raising the flag says anything.
  if (!wasFlagged) toast.show("Noted — thanks.");
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
  const askRef = useRef<HTMLButtonElement>(null);
  const confidenceRef = useRef<HTMLDivElement>(null);

  /**
   * The tutor sheet, remembered per QUESTION rather than as a bare boolean: a
   * new item derives it closed, because the panel is seeded from one verdict
   * and carrying it across would be answering the wrong question.
   */
  const [askForCursor, setAskForCursor] = useState<number | null>(null);

  const { phase, cursor, items } = session;
  const view = itemView(items[cursor]);
  const total = items.length;
  const showVerdict = verdictShown(session, view.item);

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
  const difficulty = difficultyLabel(view.item, session);
  const quizLength = total || session.config.count;

  const { rootRef, feedbackRef } = useQuestionFocus(phase, cursor, view.written, showVerdict);
  useShortQuizToast(session, total, toast);
  const primary = usePrimary({ actions, busy, items, phase, hasAnswer: view.hasAnswer, showVerdict });

  const header = (
    <QuestionHeader concept={concept} format={view.format} showFormat={phase !== "generating" && Boolean(view.item)} difficulty={difficulty} />
  );
  const pager = <QuestionPager session={session} actions={actions} busy={busy} quizLength={quizLength} />;

  if (phase === "generating") {
    return (
      <div className="quiz-question" data-testid="quiz-generating">
        <div className="quiz-question__col">
          {header}
          <GeneratingStatus quizLength={quizLength} conceptName={concept.name} difficulty={difficulty} />
          <div className="quiz-question__grow" />
          <QuestionFooter phase={phase} actions={actions} pager={pager} />
        </div>
      </div>
    );
  }

  // ── active | answered | confirm-leave | submitting ───────────────────

  const shown = showVerdict ? view.verdict : null;
  const AnswerField = ANSWER_FIELDS[view.format];
  const onRootKeyDown = (e: React.KeyboardEvent) =>
    handleRootKey(e, { askOpen, phase, primary, selectable, optionCount: view.options.length, actions, confidenceRef });

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
        <div className="quiz-question__body" key={view.item?.question.id ?? cursor}>
          <QuestionPrompt item={view.item} format={view.format} />
          <AnswerField view={view} shown={shown} selectable={selectable} actions={actions} primary={primary} />
          <QuestionConfidence confidenceRef={confidenceRef} item={view.item} selectable={selectable} actions={actions} />
          <VerdictFeedback
            feedbackRef={feedbackRef}
            shown={shown}
            format={view.format}
            correctLabel={correctOption(view.verdict, view.options)?.label}
          />
          <QuestionAside
            flagged={view.item?.flagged ?? false}
            onFlag={() => flagItem(view.item, actions, toast)}
            canAsk={phase === "answered"}
            askRef={askRef}
            onAsk={() => setAskForCursor(cursor)}
          />
        </div>

        <div className="quiz-question__grow" />

        <QuestionFooter phase={phase} actions={actions} pager={pager} primary={primary} />
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
        seed={askSeedFor(view)}
        quizAsk={quizAskFor(session.attemptId, view.item)}
        returnFocusTo={askRef}
      />
    </div>
  );
}
