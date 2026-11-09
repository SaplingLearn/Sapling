/**
 * The two network legs of one `AskPanel` turn, lifted out of its `runTurn` so
 * each rung of the failure ladder reads on its own. Nothing here touches React
 * state: the panel passes in the signal, the stream handlers and the one state
 * write the JSON rung needs, and keeps every stale-turn guard itself.
 */

import {
  sendChat,
  shouldFallBackToJson,
  startSession,
  startSessionStream,
  streamChat,
  type StreamChatHandlers,
} from "@/lib/api";

/** The tutor mode a "why was I wrong" question wants. */
export const TUTOR_MODE = "socratic";

/** The turn was aborted mid-request: the caller returns, writing nothing more. */
export const ABORTED = Symbol("aborted");

/** What the turn has streamed so far — shared with the panel's token handler. */
export interface TurnProgress {
  /** A non-blank token arrived, so the JSON rung must not re-run the turn. */
  sawToken: boolean;
  /** The partial reply so far (ADR 0020 keeps it if the turn fails). */
  partial: string;
}

/**
 * Open the tutor session on the concept. A stream that falls over retries on
 * the JSON route — the greeting is thrown away either way, so there is no
 * partial text to lose. Resolves the (possibly missing) session id, or
 * `ABORTED` when the turn was cancelled while the stream was opening.
 */
export async function openTutorSession(
  userId: string,
  conceptName: string,
  courseId: string | null,
  signal: AbortSignal,
): Promise<string | null | typeof ABORTED> {
  try {
    const started = await startSessionStream(
      userId,
      conceptName,
      TUTOR_MODE,
      true,
      courseId ?? undefined,
      undefined,
      { signal },
    );
    return started.session_id ?? null;
  } catch (err) {
    if (signal.aborted) return ABORTED;
    if (!shouldFallBackToJson(err)) throw err;
    const started = await startSession(
      userId,
      conceptName,
      TUTOR_MODE,
      courseId ?? undefined,
      true,
    );
    return started.session_id;
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
 */
export async function chatWithFallback(
  { sid, userId, message, turnId, signal, progress }: ChatLeg,
  { onToken, onProgress }: Pick<StreamChatHandlers, "onToken" | "onProgress">,
  beforeFallback: () => void,
): Promise<string | typeof ABORTED> {
  try {
    // `graph_update` events are deliberately unhandled: this panel is a
    // read of the student's own mistake, not a study turn that should
    // move the graph under the quiz.
    const res = await streamChat(sid, userId, message, TUTOR_MODE, true, undefined, {
      onToken,
      onProgress,
      signal,
    }, turnId);
    return res.reply || "";
  } catch (err) {
    if (signal.aborted) return ABORTED;
    if (progress.sawToken || !shouldFallBackToJson(err)) throw err;
    beforeFallback();
    const res = await sendChat(sid, userId, message, TUTOR_MODE, true, undefined, turnId);
    return res.reply || "";
  }
}

/** The inline error copy for a failed turn. */
export function askErrorCopy(err: unknown): string {
  return err instanceof Error ? err.message : "The tutor is unavailable.";
}
