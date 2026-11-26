"use client";
// "Due today" — the learning loop's daily review queue on Study (PKG-12; spec §3.2,
// §11.3). Driven by /api/learn/loop/review/next → /review/answer → next. Rendered only
// when the loop is on for the student (Study.tsx probes getLoopStatus first). Launch
// polish (PKG-13): the budget pause banner (a 429 "ai budget reached", or novice
// concepts paused at the tutor hard level per /review/summary — spec §3.5, re-read
// with every load), a real "All caught up" state, and a testid on every control.
// The empty state claims nothing about "later": /review/summary's `due` counts what
// is due TODAY as of its read, so a count from an earlier read was stale and wrong.
//
// A check item's reference answer never reaches the client until the server returns it
// in the corrective `hint` after a wrong answer; an mc_reason item's options are shown
// in their stored order and the UI never infers which one is correct (A22).
//
// "Report this question" (spec §13 A113; #695), while the `item_reports` flag is on:
// a check item — answered or not — can be reported with a reason from a short list;
// the server stops serving it to this student and the panel moves to the next item.
//
// An item that is gone (a 404 on answer or report: withdrawn, held or deleted since
// it was served, or no longer this session's) is skipped with a short note, never
// left on screen to fail every resend. A queue that failed to load says why and
// offers Retry; it never shows the "review keeps working" pause banner, because
// review is exactly what did not load.
//
// "How sure are you?" (spec §13 A127): an optional Guessing / Fairly sure / Sure
// on a check (never a flashcard — its forgot / hard / easy rating already says how
// it went). Sent with the answer only when chosen; it never holds up "Check".
//
// Keyboard and screen reader (spec §13 A135): every action whose button goes
// away moves focus to what it produced — Check / a rating to the result line,
// "Show answer" to the card's back, Next (or a report) to the next item's first
// control or the line saying none is due — so a screen reader reads it and the
// keyboard continues from there. The panel's first load moves nothing: Study
// owns focus when the page opens. The answer box is described by the question,
// the options are a radio group named by it.
import React from "react";
import { motion } from "framer-motion";
import {
  answerReview,
  budgetPauseOf,
  getReviewNext,
  getReviewSummary,
  reportCheckItem,
  type LoopBudgetPause,
  type LoopReportReason,
  type ReviewAnswerResponse,
  type ReviewItemPayload,
  type ReviewNextResponse,
  type ReviewSummaryResponse,
  type StudentConfidence,
} from "@/lib/api";
import { useFlag } from "@/context/FlagsContext";
import { extractErrorDetail } from "@/lib/errorMessage";
import { useFeedbackHold } from "@/lib/feedbackPacing";
import { HYPERCORRECTION_DWELL_COPY, useHypercorrectionDwell } from "@/lib/hypercorrectionDwell";
import { BudgetPausedBanner, formatResetAt } from "./BudgetPausedBanner";
import { ConfidenceControl } from "./ConfidenceControl";
import { OptionList } from "./OptionList";
import { AnswerField, CHECKING, QuestionActions, QuestionCard, REASON_LABEL, SUBMIT_ANSWER } from "./question/QuestionCard";
import { ReportQuestion } from "./ReportQuestion";
import { ReviewHead, reviewProgress, type ReviewScope } from "./review/ReviewHead";
import { answerPauseMessage, gradingPausedMessage, pausedConceptsMessage } from "./reviewPauseCopy";
import { useCrisisSupport } from "../safety/CrisisSupportCard";
import { type MotionPresets, useMotionPresets } from "@/lib/motion";
import styles from "./DueQueue.module.css";

// #866 Z29: Tailwind's preflight strips a textarea's border, padding and fill, so
// each answer box takes the loop's field style and a visible label (as the
// loop's check card does); the label sits close to its box in the card's gap.
const START_BUTTON = `btn btn--sm ${styles.start} ${styles.press}`;

// Review 409s (routes/learn_loop.py): "loop state changed, retry" — a concurrent write
// won; it can come BEFORE the grade (nothing recorded) or AFTER it (the record lost its
// compare-and-set), so the copy stays neutral and a resend is offered. "already graded"
// — this answer is recorded (e.g. that resend after a post-write retry): show it as
// done, never as an error. Any other 409 (not served, a new day) means the queue moved
// on, so the panel re-polls.
const RETRY_DETAIL = /retry/i;
const GRADED_DETAIL = /already graded/i;
// #866 K17: the student's review day ended between the serve and the answer (the
// session is one per local day): today's queue serves the check again.
const EXPIRED_DETAIL = /session expired/i;

const RATINGS: { n: number; label: string }[] = [
  { n: 1, label: "forgot" },
  { n: 2, label: "hard" },
  { n: 3, label: "easy" },
];

/** `scope` (`review_v2`, Study's ReviewsSlot): the rebuilt head, with the course chips and "3 of 9". */
export function DueQueue({ userId, courseId, scope }: { userId: string; courseId?: string; scope?: ReviewScope }) {
  const reportsOn = useFlag("item_reports") === "on";
  // docs/safety/crisis-support.md: an answer the crisis screen answered
  const crisis = useCrisisSupport();
  // Why the panel moved past the last item, said above the next one: it was
  // reported, or it is gone (a 404: withdrawn, held or deleted since served).
  const [notice, setNotice] = React.useState<Notice | null>(null);
  const [next, setNext] = React.useState<ReviewNextResponse | null>(null);
  const [answer, setAnswer] = React.useState("");
  const [choice, setChoice] = React.useState("");
  const [reason, setReason] = React.useState("");
  // spec §13 A127: null until chosen; a skip sends none
  const [confidence, setConfidence] = React.useState<StudentConfidence | null>(null);
  const [flipped, setFlipped] = React.useState(false);
  const [result, setResult] = React.useState<ReviewAnswerResponse | null>(null);
  const [alreadyGraded, setAlreadyGraded] = React.useState(false);
  // W2.5: high-confidence wrong → Next waits for corrective feedback
  const hypercorrectionHold = useHypercorrectionDwell(result?.feedback_dwell_ms);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  // The queue itself failed to load: `error` says why and Retry loads again.
  const [loadFailed, setLoadFailed] = React.useState(false);
  // The budget pause from a review call's 429; cleared by the next graded answer.
  const [pause, setPause] = React.useState<LoopBudgetPause | null>(null);
  const [summary, setSummary] = React.useState<ReviewSummaryResponse | null>(null);
  // review_v2's "3 of 9": answers recorded this visit
  const [done, setDone] = React.useState(0);
  // Every load bumps the sequence; a response for an older sequence (a slow poll, or
  // an answer to an item the panel has since moved past) is dropped, never attached
  // to the newer item.
  const seq = React.useRef(0);
  // spec §13 A135: where focus goes once the action in flight settles (see header).
  const focusNext = React.useRef<"result" | "back" | "item" | null>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);
  const resultRef = React.useRef<HTMLDivElement>(null);
  const backRef = React.useRef<HTMLDivElement>(null);
  const flipRef = React.useRef<HTMLButtonElement>(null);
  const statusRef = React.useRef<HTMLDivElement>(null);
  const errorRef = React.useRef<HTMLDivElement>(null);
  // #866 K16: what was typed for each check the queue moved past unanswered (a
  // grade the grader could not make, a pause), so it comes back with the check.
  const drafts = React.useRef(new Map<string, Draft>());

  // The summary only feeds the banner: re-read with EVERY load (a mount-time
  // read went stale as the student reviewed), a failure keeps the last one.
  const refreshSummary = React.useCallback(async (mine: number) => {
    try {
      const r = await getReviewSummary(userId, courseId);
      if (mine === seq.current) setSummary(r);
    } catch {
      /* optional */
    }
  }, [userId, courseId]);

  /** Read the next item. `moved` says why the panel moved on, shown once the
   *  next item is in (a function picks it from what was served). */
  const load = React.useCallback(async (moved: Moved = null): Promise<ReviewNextResponse | null> => {
    if (!userId) return null;
    const mine = ++seq.current;
    setBusy(true);
    setError(null);
    setLoadFailed(false);
    setNotice(null);
    void refreshSummary(mine);
    try {
      const r = await getReviewNext(userId, courseId);
      if (mine !== seq.current) return null;
      setNext(r);
      const kept = r.item ? drafts.current.get(r.item.id) : undefined;
      setAnswer(kept?.answer ?? "");
      setChoice(kept?.choice ?? "");
      setReason(kept?.reason ?? "");
      setConfidence(kept?.confidence ?? null);
      setFlipped(false);
      setResult(null);
      setAlreadyGraded(false);
      setNotice(typeof moved === "function" ? moved(r) : moved);
      return r;
    } catch (err) {
      if (mine !== seq.current) return null;
      if (!budgetPauseOf(err)) console.error("review next failed", err);
      setNext(null); // never leave a stale item on screen
      setError(loadFailureMessage(err));
      setLoadFailed(true);
      setNotice(typeof moved === "function" ? null : moved); // a report that went through still did
      return null;
    } finally {
      if (mine === seq.current) setBusy(false);
    }
  }, [userId, courseId, refreshSummary]);

  React.useEffect(() => {
    load();
  }, [load]);

  const item = next?.item ?? null;
  // No feedback survey over a review item, answered or not, until the queue
  // moves past it (lib/feedbackPacing.ts).
  useFeedbackHold(item !== null);
  // After a refusal or an outage nothing was recorded: the item stays answerable.
  const retryable = result !== null && result.unavailable;
  const answered = alreadyGraded || (result !== null && !result.unavailable);
  React.useEffect(() => {
    if (item?.kind !== "check") return;
    if (answered) drafts.current.delete(item.id);
    else drafts.current.set(item.id, { answer, choice, reason, confidence });
  }, [item, answered, answer, choice, reason, confidence]);

  // spec §13 A135: apply `focusNext` once nothing is in flight and its target is
  // on screen. A dialog (the crisis-support card) keeps focus.
  React.useLayoutEffect(() => {
    const want = focusNext.current;
    if (!want || busy) return;
    if (document.querySelector('[aria-modal="true"]')) {
      focusNext.current = null;
      return;
    }
    // A failed call shows its error instead: that line takes focus.
    const target =
      errorRef.current ?? (
        want === "result" ? resultRef.current
          : want === "back" ? backRef.current
            : panelRef.current?.querySelector<HTMLElement>("[data-answer-start]") ?? flipRef.current ?? statusRef.current);
    if (!target) return;
    focusNext.current = null;
    target.focus();
  });

  const submit = async (extra: { rating?: number } = {}) => {
    if (!next || !item || busy) return;
    focusNext.current = "result";
    const mine = seq.current;
    setBusy(true);
    setError(null);
    try {
      const stated = confidence ? { confidence } : {}; // A127: only when chosen
      const body =
        item.kind === "flashcard"
          ? { rating: extra.rating }
          : item.format === "mc_reason"
            ? { selected_option: choice, reason: reason || undefined, ...stated }
            : { answer, ...stated };
      const r = await answerReview({
        user_id: userId,
        session_id: next.session_id,
        course_id: courseId,
        kind: item.kind,
        item_id: item.id,
        ...body,
      });
      if (mine !== seq.current) return; // the panel moved on: never attach it
      if (crisis.intercept(r)) {
        // the card, not a grade: nothing was recorded and the item stays due
        setAnswer("");
        setReason("");
        setBusy(false);
        return;
      }
      setResult(r);
      if (!r.unavailable) { setPause(null); setDone((d) => d + 1); } // a graded answer got through
      setNext({ ...next, remaining_budget_s: r.remaining_budget_s });
    } catch (err) {
      if (mine !== seq.current) return;
      const failed = answerFailure(err);
      if (failed.kind === "reload") {
        if (failed.notice) focusNext.current = "item";
        await load(failed.notice === "newDay" ? (r) => newDayNotice(item, r) : failed.notice);
        return;
      }
      // a pause, not an error: the typed answer stays; flashcards keep working
      if (failed.kind === "pause") setPause(failed.pause);
      else if (failed.kind === "retry") setError("Something changed — try again."); // keep the text
      else if (failed.kind === "graded") setAlreadyGraded(true);
      else {
        console.error("review answer failed", err);
        setError("Couldn't send that answer.");
      }
    }
    if (mine === seq.current) setBusy(false);
  };

  /** spec §13 A113: report the served check item; the queue then moves on (the
   *  server never serves it to this student again). */
  const report = async (reason: LoopReportReason, sessionId = next?.session_id, again = false): Promise<boolean> => {
    if (!sessionId || !item || item.kind !== "check") return false;
    const mine = seq.current;
    try {
      await reportCheckItem({
        surface: "review",
        user_id: userId,
        session_id: sessionId,
        item_id: item.id,
        course_id: courseId,
        reason,
      });
    } catch (err) {
      if (mine !== seq.current) return false;
      const { status, detail } = extractErrorDetail(err);
      if (status === 409 && detail && EXPIRED_DETAIL.test(detail) && !again) {
        // #866 K17: the student's new day began. A report binds to today's
        // session's served item (A113): today's queue serves the question again
        // (it was never answered), so the report goes there; else say so.
        focusNext.current = "item";
        const today = await load();
        if (today?.item?.id === item.id) return report(reason, today.session_id, true);
        if (today) setNotice("unreported");
        return true;
      }
      if (status === 409 || status === 404) {
        // 409: a new day began, or the item was withdrawn meanwhile — the queue
        // moved on. 404: it is no longer one this session served — skip it.
        focusNext.current = "item";
        await load(status === 404 ? "gone" : null);
        return true;
      }
      console.error("review report failed", err);
      setError("Couldn't report that question.");
      return false;
    }
    if (mine !== seq.current) return true;
    focusNext.current = "item";
    await load("reported");
    return true;
  };

  const canSubmit = !busy && !answered && checkHasAnswer(item, choice, reason, answer);
  const m = useMotionPresets();

  return (
    <div
      ref={panelRef}
      data-testid="review-due-panel"
      className={`card ${styles.panel}`}
    >
      {crisis.dialog}
      {scope ? <ReviewHead scope={scope} progress={reviewProgress(done - (answered ? 1 : 0), next?.in_budget, !!item)} /> : (
        <div className={styles.head}>
          <h2 className={`h-serif ${styles.title}`}>Due today</h2>
          <div className={styles.spacer} />
          {next && (
            <span data-testid="review-budget" className="chip chip--accent">
              {Math.max(0, Math.round(next.remaining_budget_s / 60))} min left
            </span>
          )}
        </div>
      )}

      {/* Its "review keeps working" would contradict a queue that did not load. */}
      {!loadFailed && renderPauseBanner(pause, summary)}

      {error && <div ref={errorRef} tabIndex={-1} role="alert" data-testid={loadFailed ? "review-load-error" : undefined} className={styles.note}>{error}</div>}
      {loadFailed && (
        <button
          data-testid="review-load-retry"
          className={START_BUTTON}
          disabled={busy}
          onClick={() => {
            focusNext.current = "item";
            void load();
          }}
        >
          Try again
        </button>
      )}
      {/* Always in the DOM, so the note is announced when it appears. */}
      <div aria-live="polite">{renderNotice(notice, m)}</div>

      {renderNothingServed(next, item, statusRef, held(summary))}

      {/* Keyed on the item: the next one due rises in as a new card. */}
      {item && (
        <motion.div key={item.id} {...m.fadeUp} data-testid="review-item" className={styles.item}>
          {item.kind === "check"
            ? renderCheckItem({
                item, choice, setChoice, reason, setReason, answer, setAnswer,
                answered, confidence, setConfidence, busy, canSubmit, retryable, reportsOn,
                onSubmit: () => submit(), onReport: report,
              })
            : renderFlashcardItem({
                item, flipped, backRef, flipRef, answered, busy, m,
                onRate: (rating) => submit({ rating }),
                onFlip: () => {
                  focusNext.current = "back";
                  setFlipped(true);
                },
              })}

          {result && (
            <motion.div {...resultMotion(result, m)} ref={resultRef} tabIndex={-1} data-testid="review-hint" className={styles.result}>
              {resultText(result)}
            </motion.div>
          )}

          {alreadyGraded && !result && (
            <motion.div {...m.fade} ref={resultRef} tabIndex={-1} data-testid="review-graded" className={styles.status}>
              Your answer is already recorded.
            </motion.div>
          )}

          {/* #866 K16: after a grade the grader could not make, Next goes on and
              the question comes back after the rest (a refusal stays: own words) */}
          {showsNext(answered, pause, result) && (
            <>
              <button
                data-testid="review-next"
                className={START_BUTTON}
                disabled={busy || hypercorrectionHold}
                onClick={() => {
                  focusNext.current = "item";
                  void load();
                }}
              >
                Next
              </button>
              {hypercorrectionHold && (
                <span role="status" data-testid="loop-feedback-dwell" className={styles.note}>
                  {HYPERCORRECTION_DWELL_COPY}
                </span>
              )}
            </>
          )}
        </motion.div>
      )}
    </div>
  );
}

// ── The panel's parts: plain render calls, not components, so React sees the
// same element tree the inline JSX produced (nothing remounts). ──────────────

/** Whether Next is on screen: the item is answered, a pause holds it, or the
 *  grader could not make a grade (#866 K16; a refusal stays: own words). */
function showsNext(answered: boolean, pause: LoopBudgetPause | null, result: ReviewAnswerResponse | null): boolean {
  const retryable = result !== null && result.unavailable;
  return answered || pause !== null || (retryable && !result.refused);
}

/** Why the panel moved past the last item (see the header). */
type Notice = "reported" | "gone" | "newDay" | "newDayLater" | "newDayPlain" | "unreported";

/** `load`'s `moved`: a notice, or one chosen from the item the reload served. */
type Moved = Notice | null | ((r: ReviewNextResponse) => Notice | null);

/** #866 K17: what a new review day's reload says. The typed answer is on screen
 *  only when today's queue served that same check first; any other item keeps
 *  the draft for when the check comes back (`drafts`). A flashcard had nothing
 *  typed. */
function newDayNotice(was: ReviewItemPayload, r: ReviewNextResponse): Notice {
  if (was.kind !== "check") return "newDayPlain";
  return r.item?.id === was.id ? "newDay" : "newDayLater";
}

/** What was typed for a check, kept while the queue is on other items (#866 K16). */
type Draft = { answer: string; choice: string; reason: string; confidence: StudentConfidence | null };

const NOTICE_TEXT: Record<Notice, string> = {
  reported: "Thanks — that question is reported and won't be shown to you again.",
  gone: "That question is no longer available, so it was skipped.",
  // #866 K17: the review day is the student's local day
  newDay: "A new review day began, so the queue reloaded. Anything you had typed is still here.",
  newDayLater: "A new review day began, so the queue reloaded. If that question comes back today, what you typed comes back with it.",
  newDayPlain: "A new review day began, so the queue reloaded.",
  unreported: "A new review day began before your report was sent, and that question isn't in today's review, so the report wasn't sent.",
};

const NOTICE_TESTID: Record<Notice, string> = {
  reported: "review-reported", gone: "review-skipped", newDay: "review-new-day",
  newDayLater: "review-new-day", newDayPlain: "review-new-day", unreported: "review-not-reported",
};

function renderNotice(notice: Notice | null, m: MotionPresets) {
  if (!notice) return null;
  return (
    <motion.div {...m.fade} data-testid={NOTICE_TESTID[notice]} role="status" className={styles.note}>
      {NOTICE_TEXT[notice]}
    </motion.div>
  );
}

/** What a failed /review/answer means for the panel (see RETRY_DETAIL above). */
type AnswerFailure =
  | { kind: "pause"; pause: LoopBudgetPause }
  | { kind: "retry" | "graded" | "error" }
  | { kind: "reload"; notice: Notice | null };

function answerFailure(err: unknown): AnswerFailure {
  const paused = budgetPauseOf(err);
  if (paused) return { kind: "pause", pause: paused };
  const { status, detail } = extractErrorDetail(err);
  if (status === 409 && detail && RETRY_DETAIL.test(detail)) return { kind: "retry" };
  if (status === 409 && detail && GRADED_DETAIL.test(detail)) return { kind: "graded" };
  // #866 K17: the student's new day began — today's queue serves the check
  // again, with what was typed (`drafts`)
  if (status === 409 && detail && EXPIRED_DETAIL.test(detail)) return { kind: "reload", notice: "newDay" };
  if (status === 409) return { kind: "reload", notice: null }; // not served: the queue moved on
  // gone since it was served (withdrawn, held or deleted): every resend would
  // 404 too, so skip it and say so
  if (status === 404) return { kind: "reload", notice: "gone" };
  return { kind: "error" };
}

/** Why the queue did not load, in words that match what still works: a budget
 *  pause on this read means review did NOT keep working, so the pause banner's
 *  "review keeps working" is never shown for it. */
function loadFailureMessage(err: unknown): string {
  const paused = budgetPauseOf(err);
  if (paused) {
    return paused.resetAt
      ? `Couldn't load your review queue: your AI budget is paused until ${formatResetAt(paused.resetAt)}. Try again then.`
      : "Couldn't load your review queue: your AI budget is paused for now. Try again later.";
  }
  if (extractErrorDetail(err).status === 429) {
    return "Couldn't load your review queue: too many requests just now. Wait a moment, then try again.";
  }
  return "Couldn't load your review queue. Check your connection, then try again.";
}

type ReviewItem = NonNullable<ReviewNextResponse["item"]>;

/** A check has an answer to send: a chosen option with its reason (K02: the
 *  grader judges the reason, so an option alone is never credited), or a
 *  non-blank answer. */
function checkHasAnswer(item: ReviewItem | null, choice: string, reason: string, answer: string): boolean {
  if (item?.kind !== "check") return false;
  return item.format === "mc_reason" ? choice !== "" && reason.trim() !== "" : answer.trim() !== "";
}

/** Concepts the queue holds back today (novice at the tutor hard level, or all
 *  at the grader cap): not "all caught up" while they wait. */
const held = (summary: ReviewSummaryResponse | null) => (summary?.paused ?? 0) + (summary?.grading_paused ?? 0);

function renderPauseBanner(pause: LoopBudgetPause | null, summary: ReviewSummaryResponse | null) {
  if (pause) {
    return (
      <BudgetPausedBanner
        testId="review-budget-paused"
        resetAt={pause.resetAt}
        sessionCapped={pause.sessionCapped}
        message={answerPauseMessage(pause)}
      />
    );
  }
  const grading = summary?.grading_paused ?? 0;
  if (grading > 0) { // #866 K16: the grader cap holds every due concept's check
    const until = summary?.grading_paused_until ?? null;
    return <BudgetPausedBanner testId="review-budget-paused" resetAt={until} message={gradingPausedMessage(grading, until)} />;
  }
  const paused = summary?.paused ?? 0;
  if (paused > 0) {
    const until = summary?.paused_until ?? null;
    return <BudgetPausedBanner testId="review-budget-paused" resetAt={until} message={pausedConceptsMessage(paused, summary?.paused_scope, until)} />;
  }
  return null;
}

/** No item served: the day's review time is spent, or nothing is due. */
function renderNothingServed(
  next: ReviewNextResponse | null,
  item: ReviewItem | null,
  statusRef: React.RefObject<HTMLDivElement | null>,
  heldBack: number,
) {
  if (!next || item) return null;
  return next.due_total > 0 ? (
    <div ref={statusRef} tabIndex={-1} data-testid="review-budget-spent" className={styles.status}>
      That&apos;s today&apos;s review time. {stillWaiting(next)}
    </div>
  ) : (
    <div ref={statusRef} tabIndex={-1} data-testid="review-empty" className={styles.status}>
      {heldBack > 0 ? "Nothing else is due right now." : "All caught up — nothing is due right now."}
    </div>
  );
}

/** What waits for tomorrow once the day's review time is spent. #866 K14: the
 *  never-rated cards in it (A74's pool) are new cards, not due reviews, so the
 *  "due" count matches what the Flashcards page calls due. */
function stillWaiting(next: ReviewNextResponse): string {
  const fresh = Math.min(next.new_total ?? 0, next.due_total);
  const due = next.due_total - fresh;
  const cards = `${fresh} new ${fresh === 1 ? "card" : "cards"}`;
  if (!fresh) return `${due} more due — they'll wait for tomorrow.`;
  if (!due) return `${cards} will wait for tomorrow.`;
  return `${due} more due and ${cards} — they'll wait for tomorrow.`;
}

/** How the result line arrives: a graded answer lands with the verdict's pulse
 *  (right) or shake (wrong); a refusal or an outage, which graded nothing, fades in. */
function resultMotion(result: ReviewAnswerResponse, m: MotionPresets) {
  if (result.refused || result.unavailable) return m.fade;
  return m.pulse(result.correct ? "correct" : "wrong");
}

function resultText(result: ReviewAnswerResponse): React.ReactNode {
  if (result.refused) return "Answer in your own words — that read as instructions to the grader.";
  // #866 K16: the queue moves on, and this question comes back after the rest
  if (result.unavailable) return "The grader couldn't grade that just now. Nothing was recorded: try again, or press Next — this question comes back after the rest of today's review.";
  return (
    <>
      <strong>{result.correct ? "Correct." : "Not yet."}</strong>
      {result.hint ? ` ${result.hint}` : ""}
    </>
  );
}

interface CheckItemView {
  item: ReviewItem;
  choice: string;
  setChoice: (v: string) => void;
  reason: string;
  setReason: (v: string) => void;
  answer: string;
  setAnswer: (v: string) => void;
  answered: boolean;
  confidence: StudentConfidence | null;
  setConfidence: (v: StudentConfidence | null) => void;
  busy: boolean;
  canSubmit: boolean;
  retryable: boolean;
  reportsOn: boolean;
  onSubmit: () => void;
  onReport: (reason: LoopReportReason) => Promise<boolean>;
}

/** A due check: the shared question card (learn/question), bare inside the
 *  review panel. Its concept is the one meta line; the answer is one field
 *  (or the options and their one-sentence why), then the one verb. */
function renderCheckItem(view: CheckItemView) {
  const { item, choice, setChoice, reason, setReason, answer, setAnswer, answered, confidence, setConfidence, busy, canSubmit, retryable, reportsOn, onSubmit, onReport } = view;
  const submitIfReady = () => { if (canSubmit) onSubmit(); };
  return (
    <QuestionCard bare graded animateIn={false} meta={item.concept_name || "Question"} prompt={item.prompt}>
      {({ promptId }) => (
        <>
          {item.format === "mc_reason" ? (
            <>
              <OptionList
                options={item.options ?? []}
                selected={choice}
                onSelect={setChoice}
                testIdPrefix="review-option"
                labelledBy={promptId}
                disabled={answered}
              />
              <AnswerField label={REASON_LABEL} name="reason" testId="review-reason-input" describedByPrompt={false}
                placeholder="Because…" value={reason} disabled={answered} onChange={setReason} onSubmit={submitIfReady} />
            </>
          ) : (
            <AnswerField label="Your answer" name="answer" testId="review-answer-input" start rows={3}
              value={answer} disabled={answered} onChange={setAnswer} onSubmit={submitIfReady} />
          )}
          {!answered && (
            <ConfidenceControl
              testIdPrefix="review-confidence"
              value={confidence}
              onChange={setConfidence}
              disabled={busy}
            />
          )}
          {!answered && (
            <QuestionActions
              submit={{ label: retryable ? "Try again" : SUBMIT_ANSWER, busyLabel: CHECKING, busy, disabled: !canSubmit, onClick: onSubmit, testId: "review-submit" }}
            />
          )}
          {reportsOn && (
            <ReportQuestion key={item.id} testIdPrefix="review-report" disabled={busy} onReport={onReport} />
          )}
        </>
      )}
    </QuestionCard>
  );
}

function renderFlashcardItem({ item, flipped, backRef, flipRef, answered, busy, m, onRate, onFlip }: {
  item: ReviewItem;
  flipped: boolean;
  backRef: React.RefObject<HTMLDivElement | null>;
  flipRef: React.RefObject<HTMLButtonElement | null>;
  answered: boolean;
  busy: boolean;
  m: MotionPresets;
  onRate: (rating: number) => void;
  onFlip: () => void;
}) {
  return (
    <>
      {(item.new || item.topic) && (
        <div className={styles.tags}>
          {/* #866 K14: a never-rated card is a new card, not a review that is due */}
          {item.new && <span data-testid="review-new-card" className="chip chip--accent">New card</span>}
          {item.topic && <span className="chip">{item.topic}</span>}
        </div>
      )}
      <div className={styles.face}>{item.front}</div>
      {flipped ? (
        <>
          {/* The back rises in under the front as the card turns. */}
          <motion.div {...m.fadeUp} ref={backRef} tabIndex={-1} className={`${styles.face} ${styles.back}`}>{item.back}</motion.div>
          {!answered && (
            <div className={styles.ratings}>
              {RATINGS.map((r) => (
                <button
                  key={r.n}
                  data-testid={`review-rate-${r.n}`}
                  className={`btn btn--sm ${styles.press}`}
                  disabled={busy}
                  onClick={() => onRate(r.n)}
                >
                  {r.label}
                </button>
              ))}
            </div>
          )}
        </>
      ) : (
        <button
          ref={flipRef}
          data-testid="review-flip"
          className={START_BUTTON}
          onClick={onFlip}
        >
          Show answer
        </button>
      )}
    </>
  );
}
