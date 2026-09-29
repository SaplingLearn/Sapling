"use client";
// "Due today" — the learning loop's daily review queue on Study (PKG-12; spec §3.2,
// §11.3). Driven by /api/learn/loop/review/next → /review/answer → next. Rendered only
// when the loop is on for the student (Study.tsx probes getLoopStatus first); PKG-13
// adds the budget banner and launch polish.
//
// A check item's reference answer never reaches the client until the server returns it
// in the corrective `hint` after a wrong answer; an mc_reason item's options are shown
// in their stored order and the UI never infers which one is correct (A22).
import React from "react";
import {
  answerReview,
  getReviewNext,
  type ReviewAnswerResponse,
  type ReviewNextResponse,
} from "@/lib/api";
import { statusOf } from "@/lib/errorMessage";

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
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    if (!userId) return;
    setBusy(true);
    setError(null);
    try {
      const r = await getReviewNext(userId, courseId);
      setNext(r);
      setAnswer("");
      setChoice("");
      setReason("");
      setFlipped(false);
      setResult(null);
    } catch (err) {
      console.error("review next failed", err);
      setError("Couldn't load your review queue.");
    } finally {
      setBusy(false);
    }
  }, [userId, courseId]);

  React.useEffect(() => {
    load();
  }, [load]);

  const item = next?.item ?? null;

  const submit = async (extra: { rating?: number } = {}) => {
    if (!next || !item || busy) return;
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
      setResult(r);
      setNext({ ...next, remaining_budget_s: r.remaining_budget_s });
    } catch (err) {
      // 409: already graded, not served or a new day began — the queue moved on.
      if (statusOf(err) === 409) {
        await load();
        return;
      }
      console.error("review answer failed", err);
      setError("Couldn't send that answer.");
    } finally {
      setBusy(false);
    }
  };

  // After a refusal or an outage nothing was recorded: the item stays answerable.
  const retryable = result !== null && result.unavailable;
  const answered = result !== null && !result.unavailable;
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

      {error && <div style={{ fontSize: 13, color: "var(--text-muted)" }}>{error}</div>}

      {next && !item && (
        <div data-testid="review-empty" style={{ fontSize: 14, color: "var(--text-muted)" }}>
          All caught up for today.
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

          {answered && (
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
