/**
 * The two network legs of one `AskPanel` turn, lifted out of its `runTurn` so
 * each rung of the failure ladder reads on its own. Nothing here touches React
 * state: the panel passes in the signal, the stream handlers and the one state
 * write the JSON rung needs, and keeps every stale-turn guard itself.
 */

import {
  budgetPauseOf,
  sendChat,
  shouldFallBackToJson,
  startSession,
  startSessionStream,
  streamChat,
  type LoopBudgetPause,
  type QuizAskOrigin,
  type StreamChatHandlers,
} from "@/lib/api";
import { readableError } from "@/lib/errorMessage";
import { crisisSupportIn, type CrisisSupport } from "@/lib/crisisSupport";

/** The tutor mode a "why was I wrong" question wants. */
export const TUTOR_MODE = "socratic";

/** The turn was aborted mid-request: the caller returns, writing nothing more. */
export const ABORTED = Symbol("aborted");

/**
 * docs/safety/crisis-support.md: the backend answered with the crisis-support
 * card instead of a session or a reply. The panel shows the card in the
 * thread; no session was opened and nothing of the turn was recorded.
 */
export interface CrisisAnswer {
  crisis: CrisisSupport;
}

function crisisAnswer(response: unknown): CrisisAnswer | null {
  const crisis = crisisSupportIn(response);
  return crisis ? { crisis } : null;
}

/**
 * The learning loop paused the tutor for the student's AI budget (spec §3.5,
 * §13 A20/A39): the stream sent its `budget` event and ended without a reply.
 * Thrown, so a caller that treats every failure alike still does; a caller
 * that can show the pause reads it with `turnPauseOf`.
 */
export class BudgetPausedError extends Error {
  readonly paused: LoopBudgetPause;

  constructor(paused: LoopBudgetPause) {
    super("Tutor chat paused.");
    this.name = "BudgetPausedError";
    this.paused = paused;
  }
}

/** The budget pause behind a failed turn — the stream's, or a 429 "ai budget
 *  reached" from any leg — or null when the failure was something else. A
 *  state of the student's day, not an error: nothing of the turn was answered. */
export function turnPauseOf(err: unknown): LoopBudgetPause | null {
  return err instanceof BudgetPausedError ? err.paused : budgetPauseOf(err);
}

/** What the turn has streamed so far — shared with the panel's token handler. */
export interface TurnProgress {
  /** A non-blank token arrived, so the JSON rung must not re-run the turn. */
  sawToken: boolean;
  /** The partial reply so far (ADR 0020 keeps it if the turn fails). */
  partial: string;
  /** The stream's `budget` notice, when it sent one (the panel records it). */
  budget?: LoopBudgetPause;
}

/** The quiz question the panel asks about, as the `quiz_ask` origin the
 *  session start sends (spec §13 A99), or `undefined` without an attempt. */
export function quizAskOrigin(
  attemptId: string | undefined,
  questionIndex: number | undefined,
): QuizAskOrigin | undefined {
  return attemptId != null && questionIndex != null ? { attemptId, questionIndex } : undefined;
}

/**
 * Open the tutor session on the concept. A stream that falls over retries on
 * the JSON route — the greeting is thrown away either way, so there is no
 * partial text to lose. `origin` names the quiz question (spec §13 A99): the
 * server records the help on it and, on the loop path, opens the session
 * teaching the quiz's concept. Resolves the (possibly missing) session id,
 * `ABORTED` when the turn was cancelled while the stream was opening, or a
 * `CrisisAnswer` when the crisis screen answered instead of a session.
 */
export async function openTutorSession(
  userId: string,
  conceptName: string,
  courseId: string | null,
  signal: AbortSignal,
  origin?: QuizAskOrigin,
): Promise<string | null | typeof ABORTED | CrisisAnswer> {
  try {
    const started = await startSessionStream(
      userId,
      conceptName,
      TUTOR_MODE,
      true,
      courseId ?? undefined,
      undefined,
      { signal },
      origin,
    );
    return crisisAnswer(started) ?? started.session_id ?? null;
  } catch (err) {
    if (signal.aborted) return ABORTED;
    if (!shouldFallBackToJson(err)) throw err;
    const started = await startSession(
      userId,
      conceptName,
      TUTOR_MODE,
      courseId ?? undefined,
      true,
      undefined,
      origin,
    );
    return crisisAnswer(started) ?? started.session_id;
  }
}

export interface ChatLeg {
  sid: string;
  userId: string;
  message: string;
  turnId: string;
  signal: AbortSignal;
  progress: TurnProgress;
}

/**
 * Send the message on the stream, falling back to the JSON route only when
 * the stream produced nothing AND the failure is one the JSON route wouldn't
 * repeat (#151a). Tokens already on screen are surfaced as an error instead —
 * the partial survives via the caller's catch. `beforeFallback` runs right
 * before the JSON call (the panel clears its streaming text and status there).
 *
 * With the learning loop on, `/chat/stream` hands the turn to the loop, whose
 * stream also sends `retract` (A46: drop every token shown so far; the whole
 * text follows) and `budget` (the student's AI budget paused the tutor). A
 * paused turn sends its `budget` and ends without a reply: that throws
 * `BudgetPausedError`, never a JSON retry the budget would refuse again.
 */
export async function chatWithFallback(
  { sid, userId, message, turnId, signal, progress }: ChatLeg,
  { onToken, onProgress, onRetract, onBudget }: Pick<StreamChatHandlers, "onToken" | "onProgress" | "onRetract" | "onBudget">,
  beforeFallback: () => void,
): Promise<string | typeof ABORTED | CrisisAnswer> {
  try {
    // `graph_update` events are deliberately unhandled: this panel is a
    // read of the student's own mistake, not a study turn that should
    // move the graph under the quiz.
    const res = await streamChat(sid, userId, message, TUTOR_MODE, true, undefined, {
      onToken,
      onProgress,
      onRetract,
      onBudget: notice => {
        progress.budget = { resetAt: notice.reset_at, sessionCapped: notice.session_capped };
        onBudget?.(notice);
      },
      signal,
    }, turnId);
    return crisisAnswer(res) ?? (res.reply || "");
  } catch (err) {
    if (signal.aborted) return ABORTED;
    // the paused stream's end (no reply, no token): the pause, not a JSON retry
    if (progress.budget && !progress.sawToken && !budgetPauseOf(err)) throw new BudgetPausedError(progress.budget);
    if (progress.sawToken || !shouldFallBackToJson(err)) throw err;
    beforeFallback();
    const res = await sendChat(sid, userId, message, TUTOR_MODE, true, undefined, turnId);
    return crisisAnswer(res) ?? (res.reply || "");
  }
}

/** The inline error copy for a failed turn. */
export function askErrorCopy(err: unknown): string {
  // readableError: a 429 or 422 body shows its detail, never the raw JSON.
  return err instanceof Error ? readableError(err, "The tutor is unavailable.") : "The tutor is unavailable.";
}
