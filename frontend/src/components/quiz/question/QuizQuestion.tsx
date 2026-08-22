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
import { AnswerOption, Badge, Button, ProgressDots, type AnswerState } from "@/components/ui";
import { ConceptNode } from "@/components/graph/ConceptNode";
import { Skeleton } from "@/components/Skeleton";
import { useToast } from "@/components/ToastProvider";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import type { QuizConfig, QuizSession } from "@/lib/quiz/types";
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
}

/** The header mark, at the size §3 pins for a `dot`. */
const HEADER_DOT = 15;
/** Placeholder row widths while the quiz is written — four is the modal count. */
const SKELETON_ROWS = [72, 86, 64, 79];
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

export function QuizQuestion({ session, actions, concept, userId, courseId }: QuizQuestionProps) {
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
  /**
   * The item whose `/answer` call is in flight, as a key that changes whenever
   * the machine moves.
   *
   * `useQuizSession` exposes exactly this as `pending`, but `QuizQuestionProps`
   * (the A2 seam) doesn't carry it and `QuizScreen` doesn't pass it, so the
   * screen keeps its own latch rather than widening the seam unilaterally.
   * The phase can't stand in: it stays `active` for the whole round trip, so
   * without this the Submit button is live again the instant it is pressed.
   *
   * Stored as the key rather than a boolean cleared in an effect, so "the call
   * landed" is DERIVED from the session that came back — no reset render, and
   * no way for the latch to get stuck if a transition is missed.
   */
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const { phase, cursor, items } = session;
  const item = items[cursor];
  const total = items.length;
  const options = item?.question.options ?? [];
  const selectedIndex = item?.selectedIndex ?? null;
  const answeredCount = items.filter(i => i.verdict !== null).length;
  const isLast = cursor >= total - 1;
  // R-2: every answer is recorded server-side either way; the feedback mode
  // only decides whether the verdict is ever shown.
  const showVerdict = session.config.feedback === "as-you-go" && item?.verdict != null;

  // Both derived, so a session that moved is the only thing that clears them.
  const answerKey = `${session.attemptId}:${cursor}:${phase}:${item?.verdict ? "scored" : "open"}`;
  const busy = busyKey === answerKey;
  const askOpen = askForCursor === cursor;
  const selectable = phase === "active" && !busy;

  // A blank accent would reach `shadeFor` as an unparseable colour and pass
  // straight through; the CSS variable degrades to the app accent instead.
  const accent = concept.color || "var(--quiz-accent, var(--accent))";
  const difficulty = (item?.question.difficulty ?? session.config.difficulty ?? "").toUpperCase();
  const railTotal = total || session.config.count;

  // ── Effects ──────────────────────────────────────────────────────────

  // The keyboard map is attached to the screen root, so the root has to hold
  // focus for it to hear anything before the student clicks. Moving focus onto
  // each new question is also the right announcement.
  useEffect(() => {
    if (phase !== "active") return;
    rootRef.current?.focus();
  }, [phase, cursor]);

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
    if (phase !== "active" || busy || selectedIndex === null) return;
    setBusyKey(answerKey);
    actions.submitAnswer();
  }, [actions, answerKey, busy, phase, selectedIndex]);

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
    if (showVerdict) {
      return {
        label: isLast ? "See results" : "Next",
        testid: "quiz-next",
        enabled: phase === "answered",
        activate: () => actions.next(),
      };
    }
    return {
      label: "Submit",
      testid: "quiz-submit-answer",
      enabled: phase === "active" && !busy && selectedIndex !== null,
      activate: submit,
    };
  }, [actions, busy, isLast, phase, selectedIndex, showVerdict, submit]);

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
      {difficulty && <Badge bg="var(--bg-soft)">{difficulty}</Badge>}
    </div>
  );

  const rail = (
    <div className="quiz-question__rail">
      <ProgressDots
        total={railTotal}
        // Nothing is "here" yet while the quiz is still being written.
        current={total === 0 ? -1 : cursor}
        answered={total === 0 ? 0 : answeredCount}
        orientation="column"
        ariaLabel={`Question ${Math.min(cursor + 1, railTotal)} of ${railTotal}`}
        testid="quiz-progress"
      />
    </div>
  );

  // ── generating ───────────────────────────────────────────────────────

  if (phase === "generating") {
    return (
      <div className="quiz-question" data-testid="quiz-generating">
        {rail}
        <div className="quiz-question__col">
          {header}
          <p className="label-micro quiz-question__generating-copy" role="status">
            Writing your quiz…
          </p>
          <div className="quiz-question__stem quiz-question__stem--skeleton">
            <Skeleton height="var(--quiz-q-skeleton-stem)" width="92%" />
            <Skeleton height="var(--quiz-q-skeleton-stem)" width="64%" />
          </div>
          <div className="quiz-question__skeleton-options" aria-hidden="true">
            {SKELETON_ROWS.map((width, i) => (
              <div key={i} className="quiz-question__skeleton-row">
                <Skeleton height="var(--quiz-q-skeleton-line)" width={`${width}%`} />
              </div>
            ))}
          </div>
          <div className="quiz-question__grow" />
        </div>
        <div className="quiz-question__spacer" />
      </div>
    );
  }

  // ── active | answered | confirm-leave | submitting ───────────────────

  const verdict = item?.verdict ?? null;
  // `correct_index` is -1 for a malformed item with no correct option, so the
  // letter is optional and the copy has to survive without it.
  const correctLabel =
    verdict && verdict.correctIndex >= 0 ? options[verdict.correctIndex]?.label : undefined;

  const optionState = (index: number): AnswerState => {
    if (!showVerdict || !verdict) return selectedIndex === index ? "selected" : "default";
    if (index === verdict.correctIndex) return "correct";
    if (index === selectedIndex) return "chosen-wrong";
    return "muted";
  };

  const askSeed: AskSeed = {
    stem: item?.question.question ?? "",
    chosenLabel: (selectedIndex !== null ? options[selectedIndex]?.label : undefined) ?? "—",
    chosenText: (selectedIndex !== null ? options[selectedIndex]?.text : undefined) ?? "nothing",
    correctLabel: correctLabel ?? "—",
    correctText:
      (verdict && verdict.correctIndex >= 0 ? options[verdict.correctIndex]?.text : undefined) ?? "",
    explanation: verdict?.explanation ?? "",
  };

  return (
    <div
      ref={rootRef}
      className="quiz-question"
      data-testid="quiz-panel"
      tabIndex={-1}
      onKeyDown={onRootKeyDown}
    >
      {rail}

      <div className="quiz-question__col">
        {header}

        <h2 className="quiz-question__stem h-serif">{item?.question.question ?? ""}</h2>

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
          onKeyDown={onOptionsKeyDown}
        >
          {options.map((option, index) => (
            <AnswerOption
              key={option.label}
              letter={option.label}
              text={option.text}
              state={optionState(index)}
              disabled={!selectable}
              onSelect={() => actions.select(index)}
              // The group owns one tab stop: the chosen row, or the first row
              // while nothing is chosen.
              tabIndex={index === (selectedIndex ?? 0) ? 0 : -1}
              testid={`quiz-answer-option-${option.label}`}
            />
          ))}
        </div>

        <div
          ref={feedbackRef}
          className="quiz-question__feedback"
          data-testid="quiz-review-verdict"
          aria-live="polite"
          tabIndex={-1}
        >
          {showVerdict && verdict && (
            <>
              <span>
                {verdict.isCorrect
                  ? "Correct."
                  : correctLabel
                    ? `Not quite — the answer is ${correctLabel}.`
                    : "Not quite."}
              </span>
              {verdict.explanation && (
                <p className="quiz-question__explanation body-serif">{verdict.explanation}</p>
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
            // A raw <button> rather than <Button>: the panel needs a focus
            // target to hand focus back to, and `Button` is a plain function
            // component with no `ref` in its prop type. Same classes it renders.
            <button
              ref={askRef}
              type="button"
              className="btn btn--sm"
              data-testid="quiz-ask"
              onClick={() => setAskForCursor(cursor)}
            >
              Ask about this
            </button>
          )}
        </div>

        <div className="quiz-question__grow" />

        <div className="quiz-question__footer">
          <Button data-testid="quiz-leave" onClick={() => actions.requestLeave()}>
            Leave
          </Button>
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

      <div className="quiz-question__spacer" />

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
