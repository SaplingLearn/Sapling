"use client";
// "Due today" — the learning loop's daily review queue on Study (PKG-12; spec §3.2,
// §11.3). Driven by /api/learn/loop/review/next → /review/answer → next. Rendered only
// when the loop is on for the student (Study.tsx probes getLoopStatus first). Launch
// polish (PKG-13): the budget pause banner (a 429 "ai budget reached", or novice
// concepts paused at the tutor hard level per /review/summary — spec §3.5), a real
// "All caught up" state, and a testid on every control.
//
// A check item's reference answer never reaches the client until the server returns it
// in the corrective `hint` after a wrong answer; an mc_reason item's options are shown
// in their stored order and the UI never infers which one is correct (A22).
import React from "react";
import {
  answerReview,
  budgetPauseOf,
  getReviewNext,
  getReviewSummary,
  type LoopBudgetPause,
  type ReviewAnswerResponse,
  type ReviewNextResponse,
  type ReviewSummaryResponse,
} from "@/lib/api";
import { extractErrorDetail } from "@/lib/errorMessage";
import { BudgetPausedBanner, formatResetAt } from "./BudgetPausedBanner";

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
  const [next, setNext] = React.useState<ReviewNextResponse | null>(null);
  const [answer, setAnswer] = React.useState("");
  const [choice, setChoice] = React.useState("");
  const [reason, setReason] = React.useState("");
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

  const load = React.useCallback(async () => {
    if (!userId) return;
    const mine = ++seq.current;
    setBusy(true);
    setError(null);
    try {
      const r = await getReviewNext(userId, courseId);
      if (mine !== seq.current) return;
      setNext(r);
      setAnswer("");
      setChoice("");
      setReason("");
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
  }, [userId, courseId]);

  React.useEffect(() => {
    load();
  }, [load]);

  // The summary only feeds the banner and the empty state: a failure is ignored.
  React.useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    getReviewSummary(userId, courseId)
      .then((r) => { if (!cancelled) setSummary(r); })
      .catch(() => { /* optional */ });
    return () => { cancelled = true; };
  }, [userId, courseId]);

  const item = next?.item ?? null;

  const submit = async (extra: { rating?: number } = {}) => {
    if (!next || !item || busy) return;
    const mine = seq.current;
    setBusy(true);
    setError(null);
    try {
      const body =
        item.kind === "flashcard"
          ? { rating: extra.rating }
          : item.format === "mc_reason"
            ? { selected_option: choice, reason: reason || undefined }
            : { answer };
      const r = await answerReview({
        user_id: userId,
        session_id: next.session_id,
        course_id: courseId,
        kind: item.kind,
        item_id: item.id,
        ...body,
      });
      if (mine !== seq.current) return; // the panel moved on: never attach it
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

  // After a refusal or an outage nothing was recorded: the item stays answerable.
  const retryable = result !== null && result.unavailable;
  const answered = alreadyGraded || (result !== null && !result.unavailable);
  const pausedConcepts = summary?.paused ?? 0;
  const dueLater = summary ? summary.due.flashcard + summary.due.check : 0;
  const canSubmit =
    !busy &&
    !answered &&
    item?.kind === "check" &&
    (item.format === "mc_reason" ? choice !== "" : answer.trim() !== "");

  return (
    <div
      data-testid="review-due-panel"
      className="card"
      style={{ margin: "14px 32px 0", padding: 16, display: "flex", flexDirection: "column", gap: 12 }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div className="h-serif" style={{ fontSize: 17 }}>Due today</div>
        <div style={{ flex: 1 }} />
        {next && (
          <span data-testid="review-budget" className="chip chip--accent">
            {Math.max(0, Math.round(next.remaining_budget_s / 60))} min left
          </span>
        )}
      </div>

      {pause ? (
        <BudgetPausedBanner
          testId="review-budget-paused"
          resetAt={pause.resetAt}
          sessionCapped={pause.sessionCapped}
          message={answerPauseMessage(pause)}
        />
      ) : pausedConcepts > 0 ? (
        <BudgetPausedBanner testId="review-budget-paused" resetAt={null} message={pausedConceptsMessage(pausedConcepts)} />
      ) : null}

      {error && <div style={{ fontSize: 13, color: "var(--text-muted)" }}>{error}</div>}

      {next && !item && next.due_total > 0 && (
        <div data-testid="review-budget-spent" style={{ fontSize: 14, color: "var(--text-muted)" }}>
          That&apos;s today&apos;s review time. {next.due_total} more due — they&apos;ll wait for tomorrow.
        </div>
      )}
      {next && !item && next.due_total === 0 && (
        <div data-testid="review-empty" style={{ fontSize: 14, color: "var(--text-muted)" }}>
          All caught up — nothing is due right now.
          {dueLater > 0 && ` ${dueLater} more ${dueLater === 1 ? "is" : "are"} due later.`}
        </div>
      )}

      {item && (
        <div data-testid="review-item" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {item.kind === "check" ? (
            <>
              {item.concept_name && (
                <span className="chip" style={{ alignSelf: "flex-start" }}>{item.concept_name}</span>
              )}
              <div style={{ fontSize: 15, whiteSpace: "pre-wrap" }}>{item.prompt}</div>
              {item.format === "mc_reason" ? (
                <>
                  <div role="radiogroup" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {(item.options ?? []).map((o) => (
                      <label key={o.letter} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 14 }}>
                        <input
                          data-testid={`review-option-${o.letter}`}
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
                    placeholder="In one sentence: why?"
                    value={reason}
                    disabled={answered}
                    onChange={(e) => setReason(e.target.value)}
                    rows={2}
                  />
                </>
              ) : (
                <textarea
                  data-testid="review-answer-input"
                  placeholder="Your answer"
                  value={answer}
                  disabled={answered}
                  onChange={(e) => setAnswer(e.target.value)}
                  rows={3}
                />
              )}
              {!answered && (
                <button
                  data-testid="review-submit"
                  className="btn btn--sm btn--primary"
                  style={{ alignSelf: "flex-start" }}
                  disabled={!canSubmit}
                  onClick={() => submit()}
                >
                  {retryable ? "Try again" : "Check"}
                </button>
              )}
            </>
          ) : (
            <>
              {item.topic && <span className="chip" style={{ alignSelf: "flex-start" }}>{item.topic}</span>}
              <div style={{ fontSize: 15, whiteSpace: "pre-wrap" }}>{item.front}</div>
              {flipped ? (
                <>
                  <div style={{ fontSize: 15, whiteSpace: "pre-wrap", color: "var(--text-dim)" }}>{item.back}</div>
                  {!answered && (
                    <div style={{ display: "flex", gap: 8 }}>
                      {RATINGS.map((r) => (
                        <button
                          key={r.n}
                          data-testid={`review-rate-${r.n}`}
                          className="btn btn--sm"
                          disabled={busy}
                          onClick={() => submit({ rating: r.n })}
                        >
                          {r.label}
                        </button>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <button
                  data-testid="review-flip"
                  className="btn btn--sm"
                  style={{ alignSelf: "flex-start" }}
                  onClick={() => setFlipped(true)}
                >
                  Show answer
                </button>
              )}
            </>
          )}

          {result && (
            <div data-testid="review-hint" style={{ fontSize: 14, whiteSpace: "pre-wrap" }}>
              {result.refused
                ? "Answer in your own words — that read as instructions to the grader."
                : result.unavailable
                  ? "Grader unavailable — try again later."
                  : (
                    <>
                      <strong>{result.correct ? "Correct." : "Not yet."}</strong>
                      {result.hint ? ` ${result.hint}` : ""}
                    </>
                  )}
            </div>
          )}

          {alreadyGraded && !result && (
            <div data-testid="review-graded" style={{ fontSize: 14, color: "var(--text-muted)" }}>
              Your answer is already recorded.
            </div>
          )}

          {(answered || pause !== null) && (
            <button
              data-testid="review-next"
              className="btn btn--sm"
              style={{ alignSelf: "flex-start" }}
              disabled={busy}
              onClick={() => load()}
            >
              Next
            </button>
          )}
        </div>
      )}
    </div>
  );
}
