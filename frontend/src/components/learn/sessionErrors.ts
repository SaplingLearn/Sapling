// How Tutor V2 reads a loop route's refusal of the session on screen (#866 K26):
// the session is closed or gone, or it has moved to another phase (another tab
// or device moved it). Each is answered from the server's own state, never by
// repeating a request that cannot succeed.

/** routes/learn_loop.py `_SESSION_CLOSED`: every teaching route after the close (A60). */
export const SESSION_CLOSED_DETAIL = "this session is closed";
/** The session no longer exists (`_session_scope`, /close): a pending session
 *  the server lost, or one deleted in another tab. */
export const SESSION_GONE_DETAIL = "Session not found";

/** The 409s of a route the session's phase refuses: the probe and plan routes'
 *  `_require_phase` ("phase is <phase>") and the teaching routes'
 *  `_TEACHING_CLOSED` during the check-in or the plan. */
const PHASE_MOVED = new Set([
  "phase is probe", "phase is plan", "phase is teach", "phase is close",
  "finish the probe first", "finish the plan first",
]);

export type SessionRefusal = "closed" | "moved" | null;

/** What a route's error says about the session on screen: it is closed (or gone:
 *  its stored close, or that it was closed, is what to show), or it has moved
 *  to another phase (re-read where it is); null for anything else. */
export function sessionRefusal(status: number | undefined, detail: string | undefined): SessionRefusal {
  if (!detail) return null;
  if ((status === 409 && detail === SESSION_CLOSED_DETAIL) || (status === 404 && detail === SESSION_GONE_DETAIL)) return "closed";
  return status === 409 && PHASE_MOVED.has(detail) ? "moved" : null;
}
