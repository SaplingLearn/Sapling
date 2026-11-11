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
import {
  answerReview,
  budgetPauseOf,
  getReviewNext,
  getReviewSummary,
  reportCheckItem,
  type LoopBudgetPause,
  type LoopReportReason,
  type ReviewAnswerResponse,
  type ReviewNextResponse,
  type ReviewSummaryResponse,
  type StudentConfidence,
} from "@/lib/api";
import { useFlag } from "@/context/FlagsContext";
import { extractErrorDetail } from "@/lib/errorMessage";
import { useFeedbackHold } from "@/lib/feedbackPacing";
import { BudgetPausedBanner, formatResetAt } from "./BudgetPausedBanner";
import { ConfidenceControl } from "./ConfidenceControl";
import { ReportQuestion } from "./ReportQuestion";
import { useCrisisSupport } from "../safety/CrisisSupportCard";

// Review 409s (routes/learn_loop.py): "loop state changed, retry" — a concurrent write
// won; it can come BEFORE the grade (nothing recorded) or AFTER it (the record lost its
// compare-and-set), so the copy stays neutral and a resend is offered. "already graded"
// — this answer is recorded (e.g. that resend after a post-write retry): show it as
// done, never as an error. Any other 409 (not served, a new day) means the queue moved
// on, so the panel re-polls.
const RETRY_DETAIL = /retry/i;
const GRADED_DETAIL = /already graded/i;

/** A 429 "ai budget reached" on a review call (spec §3.5 / A20). */
function answerPauseMessage(pause: LoopBudgetPause): string {
  return pause.resetAt
    ? `AI tutor paused until ${formatResetAt(pause.resetAt)}. Flashcards and review keep working.`
    : "AI tutor paused for now. Flashcards and review keep working.";
}

/** Novice concepts paused at the tutor hard level (`/review/summary` `paused`). */
function pausedConceptsMessage(n: number): string {
  return `${n} ${n === 1 ? "concept" : "concepts"} paused until your daily AI budget resets. Flashcards and other reviews keep working.`;
}

const RATINGS: { n: number; label: string }[] = [
  { n: 1, label: "forgot" },
  { n: 2, label: "hard" },
  { n: 3, label: "easy" },
];

export function DueQueue({ userId, courseId }: { userId: string; courseId?: string }) {
  const reportsOn = useFlag("item_reports") === "on";
  // docs/safety/crisis-support.md: an answer the crisis screen answered
  const crisis = useCrisisSupport();
  // the last item was reported: say so above the next one
  const [reported, setReported] = React.useState(false);
  const [next, setNext] = React.useState<ReviewNextResponse | null>(null);
  const [answer, setAnswer] = React.useState("");
  const [choice, setChoice] = React.useState("");
  const [reason, setReason] = React.useState("");
  // spec §13 A127: null until chosen; a skip sends none
  const [confidence, setConfidence] = React.useState<StudentConfidence | null>(null);
  const [flipped, setFlipped] = React.useState(false);
  const [result, setResult] = React.useState<ReviewAnswerResponse | null>(null);
  const [alreadyGraded, setAlreadyGraded] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  // The budget pause from a review call's 429; cleared by the next graded answer.
  const [pause, setPause] = React.useState<LoopBudgetPause | null>(null);
  const [summary, setSummary] = React.useState<ReviewSummaryResponse | null>(null);
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
  const promptId = React.useId();

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

  const load = React.useCallback(async () => {
    if (!userId) return;
    const mine = ++seq.current;
    setBusy(true);
    setError(null);
    setReported(false);
    void refreshSummary(mine);
    try {
      const r = await getReviewNext(userId, courseId);
      if (mine !== seq.current) return;
      setNext(r);
      setAnswer("");
      setChoice("");
      setReason("");
      setConfidence(null);
      setFlipped(false);
      setResult(null);
      setAlreadyGraded(false);
    } catch (err) {
      if (mine !== seq.current) return;
      const paused = budgetPauseOf(err);
      if (paused) setPause(paused);
      else console.error("review next failed", err);
      setNext(null); // never leave a stale item on screen
      setError("Couldn't load your review queue.");
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
      if (!r.unavailable) setPause(null); // a graded answer got through
      setNext({ ...next, remaining_budget_s: r.remaining_budget_s });
    } catch (err) {
      if (mine !== seq.current) return;
      const { status, detail } = extractErrorDetail(err);
      const paused = budgetPauseOf(err);
      if (paused) {
        // the pause, not an error: the typed answer stays; flashcards keep working
        setPause(paused);
      } else if (status === 409 && detail && RETRY_DETAIL.test(detail)) {
        // keep what the student typed and let them resend
        setError("Something changed — try again.");
      } else if (status === 409 && detail && GRADED_DETAIL.test(detail)) {
        setAlreadyGraded(true);
      } else if (status === 409) {
        // not served or a new day began — the queue moved on
        await load();
        return;
      } else {
        console.error("review answer failed", err);
        setError("Couldn't send that answer.");
      }
    }
    if (mine === seq.current) setBusy(false);
  };

  /** spec §13 A113: report the served check item; the queue then moves on (the
   *  server never serves it to this student again). */
  const report = async (reason: LoopReportReason): Promise<boolean> => {
    if (!next || !item || item.kind !== "check") return false;
    const mine = seq.current;
    try {
      await reportCheckItem({
        surface: "review",
        user_id: userId,
        session_id: next.session_id,
        item_id: item.id,
        course_id: courseId,
        reason,
      });
    } catch (err) {
      if (mine !== seq.current) return false;
      if (extractErrorDetail(err).status === 409) {
        // a new day began, or the item was withdrawn meanwhile: the queue moved on
        await load();
        return true;
      }
      console.error("review report failed", err);
      setError("Couldn't report that question.");
      return false;
    }
    if (mine !== seq.current) return true;
    focusNext.current = "item";
    await load();
    setReported(true);
    return true;
  };

  // After a refusal or an outage nothing was recorded: the item stays answerable.
  const retryable = result !== null && result.unavailable;
  const answered = alreadyGraded || (result !== null && !result.unavailable);
  const pausedConcepts = summary?.paused ?? 0;
  const canSubmit = !busy && !answered && checkHasAnswer(item, choice, answer);

  return (
    <div
      ref={panelRef}
      data-testid="review-due-panel"
      className="card"
      style={{ margin: "14px 32px 0", padding: 16, display: "flex", flexDirection: "column", gap: 12 }}
    >
      {crisis.dialog}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div className="h-serif" style={{ fontSize: 17 }}>Due today</div>
        <div style={{ flex: 1 }} />
        {next && (
          <span data-testid="review-budget" className="chip chip--accent">
            {Math.max(0, Math.round(next.remaining_budget_s / 60))} min left
          </span>
        )}
      </div>

      {renderPauseBanner(pause, pausedConcepts)}

      {error && <div ref={errorRef} tabIndex={-1} role="alert" style={{ fontSize: 13, color: "var(--text-muted)" }}>{error}</div>}
      {/* Always in the DOM, so the confirmation is announced when it appears. */}
      <div aria-live="polite">
        {reported && (
          <div data-testid="review-reported" role="status" style={{ fontSize: 13, color: "var(--text-muted)" }}>
            Thanks — that question is reported and won&apos;t be shown to you again.
          </div>
        )}
      </div>

      {renderNothingServed(next, item, statusRef)}

      {item && (
        <div data-testid="review-item" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {item.kind === "check"
            ? renderCheckItem({
                item, promptId, choice, setChoice, reason, setReason, answer, setAnswer,
                answered, confidence, setConfidence, busy, canSubmit, retryable, reportsOn,
                onSubmit: () => submit(), onReport: report,
              })
            : renderFlashcardItem({
                item, flipped, backRef, flipRef, answered, busy,
                onRate: (rating) => submit({ rating }),
                onFlip: () => {
                  focusNext.current = "back";
                  setFlipped(true);
                },
              })}

          {result && (
            <div ref={resultRef} tabIndex={-1} data-testid="review-hint" style={{ fontSize: 14, whiteSpace: "pre-wrap" }}>
              {resultText(result)}
            </div>
          )}

          {alreadyGraded && !result && (
            <div ref={resultRef} tabIndex={-1} data-testid="review-graded" style={{ fontSize: 14, color: "var(--text-muted)" }}>
              Your answer is already recorded.
            </div>
          )}

          {(answered || pause !== null) && (
            <button
              data-testid="review-next"
              className="btn btn--sm"
              style={{ alignSelf: "flex-start" }}
              disabled={busy}
              onClick={() => {
                focusNext.current = "item";
                void load();
              }}
            >
              Next
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── The panel's parts: plain render calls, not components, so React sees the
// same element tree the inline JSX produced (nothing remounts). ──────────────

type ReviewItem = NonNullable<ReviewNextResponse["item"]>;

/** A check has an answer to send: a chosen option, or a non-blank answer. */
function checkHasAnswer(item: ReviewItem | null, choice: string, answer: string): boolean {
  if (item?.kind !== "check") return false;
  return item.format === "mc_reason" ? choice !== "" : answer.trim() !== "";
}

function renderPauseBanner(pause: LoopBudgetPause | null, pausedConcepts: number) {
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
  if (pausedConcepts > 0) {
    return <BudgetPausedBanner testId="review-budget-paused" resetAt={null} message={pausedConceptsMessage(pausedConcepts)} />;
  }
  return null;
}

/** No item served: the day's review time is spent, or nothing is due. */
function renderNothingServed(
  next: ReviewNextResponse | null,
  item: ReviewItem | null,
  statusRef: React.RefObject<HTMLDivElement | null>,
) {
  if (!next || item) return null;
  return next.due_total > 0 ? (
    <div ref={statusRef} tabIndex={-1} data-testid="review-budget-spent" style={{ fontSize: 14, color: "var(--text-muted)" }}>
      That&apos;s today&apos;s review time. {next.due_total} more due — they&apos;ll wait for tomorrow.
    </div>
  ) : (
    <div ref={statusRef} tabIndex={-1} data-testid="review-empty" style={{ fontSize: 14, color: "var(--text-muted)" }}>
      All caught up — nothing is due right now.
    </div>
  );
}

function resultText(result: ReviewAnswerResponse): React.ReactNode {
  if (result.refused) return "Answer in your own words — that read as instructions to the grader.";
  if (result.unavailable) return "Grader unavailable — try again later.";
  return (
    <>
      <strong>{result.correct ? "Correct." : "Not yet."}</strong>
      {result.hint ? ` ${result.hint}` : ""}
    </>
  );
}

interface CheckItemView {
  item: ReviewItem;
  promptId: string;
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

function renderCheckAnswer({ item, promptId, choice, setChoice, reason, setReason, answer, setAnswer, answered }: CheckItemView) {
  if (item.format === "mc_reason") {
    return (
      <>
        <div role="radiogroup" aria-labelledby={promptId} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {(item.options ?? []).map((o, i) => (
            <label key={o.letter} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 14 }}>
              <input
                data-testid={`review-option-${o.letter}`}
                data-answer-start={(choice ? choice === o.letter : i === 0) ? "" : undefined}
                type="radio"
                name={`review-${item.id}`}
                value={o.letter}
                checked={choice === o.letter}
                disabled={answered}
                onChange={() => setChoice(o.letter)}
              />
              <span>{o.letter}. {o.text}</span>
            </label>
          ))}
        </div>
        <textarea
          data-testid="review-reason-input"
          aria-label="Review reasoning"
          placeholder="In one sentence: why?"
          value={reason}
          disabled={answered}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
        />
      </>
    );
  }
  return (
    <textarea
      data-testid="review-answer-input"
      data-answer-start=""
      aria-label="Review answer"
      aria-describedby={promptId}
      placeholder="Your answer"
      value={answer}
      disabled={answered}
      onChange={(e) => setAnswer(e.target.value)}
      rows={3}
    />
  );
}

function renderCheckItem(view: CheckItemView) {
  const { item, promptId, answered, confidence, setConfidence, busy, canSubmit, retryable, reportsOn, onSubmit, onReport } = view;
  return (
    <>
      {item.concept_name && (
        <span className="chip" style={{ alignSelf: "flex-start" }}>{item.concept_name}</span>
      )}
      <div id={promptId} style={{ fontSize: 15, whiteSpace: "pre-wrap" }}>{item.prompt}</div>
      {renderCheckAnswer(view)}
      {!answered && (
        <ConfidenceControl
          testIdPrefix="review-confidence"
          value={confidence}
          onChange={setConfidence}
          disabled={busy}
        />
      )}
      {!answered && (
        <button
          data-testid="review-submit"
          className="btn btn--sm btn--primary"
          style={{ alignSelf: "flex-start" }}
          disabled={!canSubmit}
          onClick={onSubmit}
        >
          {retryable ? "Try again" : "Check"}
        </button>
      )}
      {reportsOn && (
        <ReportQuestion key={item.id} testIdPrefix="review-report" disabled={busy} onReport={onReport} />
      )}
    </>
  );
}

function renderFlashcardItem({ item, flipped, backRef, flipRef, answered, busy, onRate, onFlip }: {
  item: ReviewItem;
  flipped: boolean;
  backRef: React.RefObject<HTMLDivElement | null>;
  flipRef: React.RefObject<HTMLButtonElement | null>;
  answered: boolean;
  busy: boolean;
  onRate: (rating: number) => void;
  onFlip: () => void;
}) {
  return (
    <>
      {item.topic && <span className="chip" style={{ alignSelf: "flex-start" }}>{item.topic}</span>}
      <div style={{ fontSize: 15, whiteSpace: "pre-wrap" }}>{item.front}</div>
      {flipped ? (
        <>
          <div ref={backRef} tabIndex={-1} style={{ fontSize: 15, whiteSpace: "pre-wrap", color: "var(--text-dim)" }}>{item.back}</div>
          {!answered && (
            <div style={{ display: "flex", gap: 8 }}>
              {RATINGS.map((r) => (
                <button
                  key={r.n}
                  data-testid={`review-rate-${r.n}`}
                  className="btn btn--sm"
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
          className="btn btn--sm"
          style={{ alignSelf: "flex-start" }}
          onClick={onFlip}
        >
          Show answer
        </button>
      )}
    </>
  );
}
