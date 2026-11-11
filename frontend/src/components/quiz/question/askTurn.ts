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
  type QuizAskOrigin,
  type StreamChatHandlers,
} from "@/lib/api";
import { crisisSupportIn, type CrisisSupport } from "@/lib/crisisSupport";

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

/** The quiz question the panel asks about, as the `quiz_ask` origin the
 *  session start sends (spec §13 A99), or `undefined` without an attempt. */
export function quizAskOrigin(
  attemptId: string | undefined,
  questionIndex: number | undefined,
): QuizAskOrigin | undefined {
  return attemptId != null && questionIndex != null ? { attemptId, questionIndex } : undefined;
}

/** A session start the crisis screen answered (docs/safety/crisis-support.md):
 *  the card instead of a session — none was opened. */
export interface CrisisStart {
  crisisSupport: CrisisSupport;
  text: string;
}

export function isCrisisStart(opened: string | null | CrisisStart): opened is CrisisStart {
  return opened !== null && typeof opened === "object";
}

/** The start's crisis card, else its session id. */
function startedAs(
  started: { session_id?: string | null },
  greeting: string | undefined,
): string | null | CrisisStart {
  const crisisSupport = crisisSupportIn(started);
  if (crisisSupport) return { crisisSupport, text: greeting || "" };
  return started.session_id ?? null;
}

/**
 * Open the tutor session on the concept. A stream that falls over retries on
 * the JSON route — the greeting is thrown away either way, so there is no
 * partial text to lose. `origin` names the quiz question (spec §13 A99): the
 * server records the help on it and, on the loop path, opens the session
 * teaching the quiz's concept. Resolves the (possibly missing) session id, the
 * crisis card when the crisis screen answered instead, or `ABORTED` when the
 * turn was cancelled while the stream was opening.
 */
export async function openTutorSession(
  userId: string,
  conceptName: string,
  courseId: string | null,
  signal: AbortSignal,
  origin?: QuizAskOrigin,
): Promise<string | null | CrisisStart | typeof ABORTED> {
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
    return startedAs(started, started.reply);
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
    return startedAs(started, started.initial_message);
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

/** The tutor's answer to one turn: its text, or the crisis card in its place. */
export interface AskReply {
  text: string;
  crisisSupport: CrisisSupport | null;
}

function replyOf(res: { reply?: string | null }): AskReply {
  return { text: res.reply || "", crisisSupport: crisisSupportIn(res) };
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
): Promise<AskReply | typeof ABORTED> {
  try {
    // `graph_update` events are deliberately unhandled: this panel is a
    // read of the student's own mistake, not a study turn that should
    // move the graph under the quiz.
    const res = await streamChat(sid, userId, message, TUTOR_MODE, true, undefined, {
      onToken,
      onProgress,
      signal,
    }, turnId);
    return replyOf(res);
  } catch (err) {
    if (signal.aborted) return ABORTED;
    if (progress.sawToken || !shouldFallBackToJson(err)) throw err;
    beforeFallback();
    const res = await sendChat(sid, userId, message, TUTOR_MODE, true, undefined, turnId);
    return replyOf(res);
  }
}

/** The inline error copy for a failed turn. */
export function askErrorCopy(err: unknown): string {
  return err instanceof Error ? err.message : "The tutor is unavailable.";
}
