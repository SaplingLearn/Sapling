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
 * (Check → Next → See results → Scoring…). A quiz that jumps under the cursor
 * between "choose" and "check" is how you mis-click an answer.
 *
 * W7.1 session chrome: SessionTop (leave + course/topic + Question N of M),
 * concept-pill meta row, and an action bar with Hint / Study guide / Skip
 * beside Check. W7.D1: Check / progress / pager = brand forest; `--quiz-accent`
 * is course identity on the concept pill only. No XP in the session top.
 * W7.5: Hint is a Bastani-lite H0–H2 client ladder (scaffold only — no loop
 * /hint). Skip → GO_TO; Study guide opens a leak-safe drawer. Wager/XP stakes
 * stay deferred — A132 confidence only. Meta: Bloom skill chip + tier +
 * Returning + exam-distance. Exam Twin soft timer in SessionTop.
 * W7.2 kit: Sort / Sequence / Label / Build / Compare / Dialogue / Explain /
 * Highlight / Calculate (value|unit|steps) on short_answer.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, Library, Sparkles } from "lucide-react";
import { Button } from "@/components/ui";
import { ConfidenceControl } from "@/components/learn/ConfidenceControl";
import { useToast } from "@/components/ToastProvider";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import { examTwinDurationSeconds } from "@/lib/quiz/examTimer";
import type { Phase, QuestionType, QuizConfig, QuizItem, QuizSession } from "@/lib/quiz/types";
import { expressionParts, superscriptParts, type ExpressionPart } from "@/lib/quiz/answerFormats";
import { AskPanel } from "./AskPanel";
import { StudyGuideDrawer } from "./StudyGuideDrawer";
import { LeaveDialog } from "./LeaveDialog";
import { AnswerFieldFor } from "./AnswerField";
import {
  GeneratingStatus,
  PrereqBanner,
  QuestionFooter,
  QuestionHeader,
  QuestionPager,
  SessionTop,
  useExamCountdown,
  type QuizConceptSummary,
} from "./QuestionChrome";
import {
  askSeedFor,
  correctOption,
  difficultyLabel,
  everyAnswered,
  itemView,
  kitKindOf,
  missLine,
  outcomeOf,
  primaryButton,
  hintLadder,
  scaffoldHint,
  skipSlotState,
  hintSlotState,
  verdictShown,
  type HintRung,
  type ItemView,
  type KitKind,
  type Primary,
  type PrimaryAction,
  type ScaffoldHint,
  type Verdict,
} from "./questionView";
import "./question.css";

export type { QuizConceptSummary } from "./QuestionChrome";

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
  /**
   * Learning-loop spec §13 A132's "How sure are you?" is the learning system's:
   * asked only while the loop is on for the student (`QuizScreen` reads the loop
   * status). Off — the default — the question screen is the pre-loop one, and an
   * answer states no confidence (#866 K46).
   */
  askConfidence?: boolean;
}

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

/** Whether the hint panel is open. A new item closes it, so focus/rubric from
 *  the previous stem cannot linger beside a different question: reset during
 *  render, the way React adjusts state to a changed input, never after. */
function useHintOpen(cursor: number) {
  const [hintOpen, setHintOpen] = useState(false);
  const [hintCursor, setHintCursor] = useState(cursor);
  if (hintCursor !== cursor) {
    setHintCursor(cursor);
    setHintOpen(false);
  }
  return [hintOpen, setHintOpen] as const;
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
  guideOpen: boolean;
  phase: Phase;
  primary: Primary;
  selectable: boolean;
  optionCount: number;
  actions: QuizActions;
  confidenceRef: React.RefObject<HTMLDivElement | null>;
  onOpenGuide: () => void;
  onToggleHint: () => void;
  hintEnabled: boolean;
}

/** The sheet and the dialog own the keyboard while they are open — and both
 *  are portals, whose events still bubble through the React tree to here. */
function keyboardIsElsewhere(e: React.KeyboardEvent, { askOpen, guideOpen, phase }: RootKeyContext): boolean {
  if (askOpen || guideOpen || phase === "confirm-leave") return true;
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
  else if (e.key === "g" || e.key === "G") {
    e.preventDefault();
    ctx.onOpenGuide();
  } else if ((e.key === "h" || e.key === "H") && ctx.hintEnabled) {
    e.preventDefault();
    ctx.onToggleHint();
  } else if (ctx.selectable) selectByShortcut(e, ctx);
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

/**
 * W7.5: Bastani-lite client ladder (H0→H1→H2). Scaffold only — never POSTs
 * loop /hint. Each "More help" reveals one rung; Study guide stays leak-safe.
 */
function HintPanel({ hint, onOpenGuide }: { hint: ScaffoldHint; onOpenGuide: () => void }) {
  const ladder = hintLadder(hint);
  const [visible, setVisible] = useState(1);
  const shown = ladder.slice(0, Math.min(visible, ladder.length));
  const canClimb = visible < ladder.length;
  return (
    <aside
      id="quiz-hint-panel"
      className="card quiz-question__hint-panel"
      data-testid="quiz-hint-panel"
      aria-label="Question scaffolding"
    >
      <ol className="quiz-question__hint-ladder" data-testid="quiz-hint-ladder">
        {shown.map((rung: HintRung) => (
          <li
            key={rung.id}
            className="quiz-question__hint-rung"
            data-testid={`quiz-hint-rung-${rung.id}`}
            data-rung={rung.id}
          >
            <span className="quiz-question__hint-rung-title label-micro">{rung.title}</span>
            <p className="quiz-question__hint-rung-body body-serif">{rung.body}</p>
          </li>
        ))}
      </ol>
      <div className="quiz-question__hint-actions">
        {canClimb && (
          <Button
            variant="link"
            size="sm"
            data-testid="quiz-hint-more"
            onClick={() => setVisible(n => Math.min(ladder.length, n + 1))}
          >
            More help
          </Button>
        )}
        <Button
          variant="link"
          size="sm"
          data-testid="quiz-hint-open-guide"
          onClick={onOpenGuide}
        >
          Open Study guide
        </Button>
      </div>
    </aside>
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

/**
 * Learning-loop spec §13 A132 / W7.4: optional "How sure are you?" while the
 * loop is on (`askConfidence`). Kit Certain/Unsure + mid-session XP wager stay
 * deferred on purpose — same Guessing / Fairly sure / Sure store as CheckCard;
 * no second confidence API, no XP stakes (W7.D1). Choosing makes no request —
 * the level rides `/answer` — and Check never waits on it.
 */
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
    <div ref={confidenceRef} className="quiz-question__confidence" data-wager="deferred">
      <ConfidenceControl
        testIdPrefix="quiz-confidence"
        value={item?.confidence ?? null}
        onChange={level => actions.setConfidence?.(level)}
        disabled={!selectable || item?.verdict != null}
        variant="default"
      />
    </div>
  );
}

/** Ask about this opens on an answered question. W7.8: Exam Twin is
 *  tool-light — Ask is refused server-side too. */
function canAskAbout(phase: Phase, sessionMode: string): boolean {
  return phase === "answered" && sessionMode !== "exam_twin";
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

/** The generating screen (a plain render call: the tree stays the one the
 *  inline JSX produced). */
function renderGenerating({
  sessionTop, header, prereqBanner, footer, guideDrawer, status,
}: {
  sessionTop: React.ReactNode;
  header: React.ReactNode;
  prereqBanner: React.ReactNode;
  footer: React.ReactNode;
  guideDrawer: React.ReactNode;
  status: React.ReactNode;
}) {
  return (
    <div className="quiz-question" data-testid="quiz-generating">
      {sessionTop}
      <div className="quiz-question__col">
        {header}
        {prereqBanner}
        {status}
        <div className="quiz-question__grow" />
        {footer}
      </div>
      {guideDrawer}
    </div>
  );
}

/** The kit facts the meta row and the hint read: the short_answer's
 *  interaction kind as served, and the kit it is (a usable payload) or null. */
function kitFacts(view: ItemView): { interactionKind: string | null; kitKind: KitKind | null } {
  const interaction = view.format === "short_answer" ? view.item?.question.interaction : undefined;
  return { interactionKind: interaction?.kind ?? null, kitKind: kitKindOf(interaction) };
}

export function QuizQuestion({
  session,
  actions,
  concept,
  userId,
  courseId,
  pending = false,
  askConfidence = false,
}: QuizQuestionProps) {
  const toast = useToast();
  const askRef = useRef<HTMLButtonElement>(null);
  const guideRef = useRef<HTMLButtonElement>(null);
  const hintRef = useRef<HTMLButtonElement>(null);
  const confidenceRef = useRef<HTMLDivElement>(null);

  /**
   * The tutor sheet, remembered per QUESTION rather than as a bare boolean: a
   * new item derives it closed, because the panel is seeded from one verdict
   * and carrying it across would be answering the wrong question.
   */
  const [askForCursor, setAskForCursor] = useState<number | null>(null);
  const [guideOpen, setGuideOpen] = useState(false);

  const { phase, cursor, items } = session;
  const view = itemView(items[cursor]);
  const total = items.length;
  const showVerdict = verdictShown(session, view.item);
  const quizLength = total || session.config.count;
  const sessionMode = session.config.sessionMode ?? "practice";
  // Soft Exam Twin countdown — display only; never auto-submits (W7.8).
  const examRemainingSec = useExamCountdown(
    sessionMode === "exam_twin" ? examTwinDurationSeconds(quizLength) : null,
    session.attemptId,
  );

  const [hintOpen, setHintOpen] = useHintOpen(cursor);

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
  const skip = skipSlotState({
    phase,
    busy,
    cursor,
    total,
    hasVerdict: view.verdict != null,
  });
  const hint = hintSlotState({
    phase,
    busy,
    sessionMode,
    hasItem: Boolean(view.item),
  });
  const { interactionKind, kitKind } = kitFacts(view);
  const scaffold = scaffoldHint({
    conceptName: concept.name,
    conceptTested: view.item?.question.concept_tested,
    format: view.format,
    ...(kitKind ? { [kitKind]: true } : {}),
  });
  const openGuide = useCallback(() => {
    setAskForCursor(null);
    setHintOpen(false);
    setGuideOpen(true);
  }, [setHintOpen]);
  const onToggleHint = useCallback(() => {
    if (!hint.enabled) return;
    setAskForCursor(null);
    setGuideOpen(false);
    setHintOpen(open => !open);
  }, [hint.enabled, setHintOpen]);
  const onSkip = useCallback(() => {
    if (skip.targetIndex == null) return;
    actions.goTo?.(skip.targetIndex);
  }, [actions, skip.targetIndex]);

  const { rootRef, feedbackRef } = useQuestionFocus(phase, cursor, view.written, showVerdict);
  useShortQuizToast(session, total, toast);
  const primary = usePrimary({ actions, busy, items, phase, hasAnswer: view.hasAnswer, showVerdict });
  const hintShown = hintOpen && hint.enabled;
  const courseLabel = concept.courseCode || undefined;

  const position = Math.min(cursor + 1, quizLength) || 1;
  const sessionTop = (
    <SessionTop
      phase={phase}
      actions={actions}
      concept={concept}
      position={position}
      quizLength={quizLength}
      examRemainingSec={examRemainingSec}
    />
  );
  const header = (
    <QuestionHeader
      concept={concept}
      format={view.format}
      formatTagKey={kitKind ?? view.format}
      showFormat={phase !== "generating" && Boolean(view.item)}
      difficulty={difficulty}
      interactionKind={interactionKind}
    />
  );
  const prereqBanner = session.prereq ? <PrereqBanner banner={session.prereq} /> : null;
  const pager = <QuestionPager session={session} actions={actions} busy={busy} quizLength={quizLength} />;
  const footer = (
    <QuestionFooter
      pager={pager}
      primary={phase === "generating" ? undefined : primary}
      hint={hint}
      hintOpen={hintShown}
      onToggleHint={onToggleHint}
      hintRef={hintRef}
      skip={skip}
      onSkip={onSkip}
      onOpenGuide={openGuide}
      guideRef={guideRef}
    />
  );
  const guideDrawer = (
    <StudyGuideDrawer
      open={guideOpen}
      onClose={() => setGuideOpen(false)}
      userId={userId}
      conceptName={concept.name}
      courseId={courseId}
      courseLabel={courseLabel}
      returnFocusTo={guideRef}
    />
  );

  if (phase === "generating") {
    return renderGenerating({
      sessionTop, header, prereqBanner, footer, guideDrawer,
      status: <GeneratingStatus quizLength={quizLength} conceptName={concept.name} difficulty={difficulty} />,
    });
  }

  // ── active | answered | confirm-leave | submitting ───────────────────

  const shown = showVerdict ? view.verdict : null;
  const onRootKeyDown = (e: React.KeyboardEvent) =>
    handleRootKey(e, {
      askOpen,
      guideOpen,
      phase,
      primary,
      selectable,
      optionCount: view.options.length,
      actions,
      confidenceRef,
      onOpenGuide: openGuide,
      onToggleHint,
      hintEnabled: hint.enabled,
    });

  return (
    <div
      ref={rootRef}
      className="quiz-question"
      data-testid="quiz-panel"
      data-phase={phase}
      tabIndex={-1}
      onKeyDown={onRootKeyDown}
    >
      {sessionTop}
      <div className="quiz-question__col">
        {header}
        {prereqBanner}

        {/* Keyed on the question, so each one arrives with the same short
            entrance — from the generating panel, from Next, from the pager. */}
        <div className="quiz-question__body" key={view.item?.question.id ?? cursor}>
          <QuestionPrompt item={view.item} format={view.format} />
          <AnswerFieldFor view={view} shown={shown} selectable={selectable} actions={actions} primary={primary} />
          {askConfidence && (
            <QuestionConfidence confidenceRef={confidenceRef} item={view.item} selectable={selectable} actions={actions} />
          )}
          {hintShown && (
            <HintPanel hint={scaffold} onOpenGuide={openGuide} />
          )}
          <VerdictFeedback
            feedbackRef={feedbackRef}
            shown={shown}
            format={view.format}
            correctLabel={correctOption(view.verdict, view.options)?.label}
          />
          <QuestionAside
            flagged={view.item?.flagged ?? false}
            onFlag={() => flagItem(view.item, actions, toast)}
            canAsk={canAskAbout(phase, sessionMode)}
            askRef={askRef}
            onAsk={() => {
              setGuideOpen(false);
              setHintOpen(false);
              setAskForCursor(cursor);
            }}
          />
        </div>

        <div className="quiz-question__grow" />

        {footer}
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
        courseLabel={courseLabel}
        seed={askSeedFor(view)}
        quizAsk={quizAskFor(session.attemptId, view.item)}
        returnFocusTo={askRef}
      />

      {guideDrawer}
    </div>
  );
}
