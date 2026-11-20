/**
 * How the legacy tutor screen (Learn.tsx's LearnInner) reads a refused turn:
 * the ADR 0020 Retry's bubble surgery, the ended-session 409 (#761/#762), and
 * an answer only the learning loop gives (#866 K49, K13).
 */
import type { ChatMsg } from "../../chat/ChatPanel";
import { tutorPauseMessage } from "../../learn/BudgetPausedBanner";
import { budgetPauseOf } from "@/lib/api";
import { errorCodeOf, statusOf } from "@/lib/errorMessage";

// ADR 0020 Retry: drop the interrupted assistant bubble and — when it sits
// directly before it — the user bubble of the same turn, so the re-send
// (which appends a fresh user bubble) doesn't duplicate either. Pure and
// exported for Learn.resume.test.ts.
export function removeInterruptedTurn(
  messages: ChatMsg[],
  interruptedId: string,
  retryText: string,
): ChatMsg[] {
  const i = messages.findIndex(m => m.id === interruptedId);
  if (i === -1) return messages;
  const next = [...messages.slice(0, i), ...messages.slice(i + 1)];
  if (i > 0 && next[i - 1]?.role === "user" && next[i - 1].content === retryText) {
    next.splice(i - 1, 1);
  }
  return next;
}

// A turn the server refused because the session is already over (#761 /
// #762): a 409 whose envelope carries `error.code: "SESSION_ENDED"` —
// `ApiError.code` off fetchJSON, the same `code` streamSSE attaches. A coded
// error decides it by its code (a 409 with any OTHER code is an ordinary
// error); only an error with no code at all — an older backend — falls back
// to the bare 409.
export const SESSION_ENDED_CODE = "SESSION_ENDED";
export function isSessionEndedError(err: unknown): boolean {
  const code = err !== null && typeof err === "object" ? (err as { code?: unknown }).code : undefined;
  if (typeof code === "string") return code === SESSION_ENDED_CODE;
  return statusOf(err) === 409;
}

/**
 * Whether a tutor call's refusal came from the learning loop, which the
 * server runs for this student when their `learning_loop` gate is on: it
 * reads the gate per request, while this tab's flags are up to a minute old
 * (#866 K49). Only the loop's routes read the AI budget (owner decision
 * 2026-11-18), so a budget pause is the loop's; and the legacy tutor's only
 * refused turn is the coded SESSION_ENDED 409, so any other 409 is one of the
 * loop's phase gates ("finish the probe first"). With the loop off neither
 * can happen. The screen then asks useLoopStatus to recheck.
 */
export function answeredByTheLoop(err: unknown): boolean {
  if (budgetPauseOf(err)) return true;
  return statusOf(err) === 409 && errorCodeOf(err) !== SESSION_ENDED_CODE;
}

/** A budget pause as the tutor's pause, with its reset time, instead of the
 *  429's raw "ai budget reached" (#866 K13); any other error as `copy`. Only
 *  the loop answers a pause, so with the loop off this is always `copy`. */
export function pauseCopyOr(err: unknown, copy: string): string {
  const pause = budgetPauseOf(err);
  return pause ? tutorPauseMessage(pause.resetAt, pause.sessionCapped) : copy;
}
