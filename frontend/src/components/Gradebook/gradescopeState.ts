/**
 * Gradescope connection state + typed-error classification (#770).
 *
 * The backend answers a Gradescope credential failure with a typed non-401
 * (`error.code`, surfaced as `ApiError.code`). A 401 is never one of these: it
 * means Sapling's own session is gone, which the app's global session handling
 * owns — treating it as "reconnect Gradescope" sent a signed-out student into
 * the Gradescope sign-in flow.
 *
 * Kept out of `lib/api.ts` on purpose: component tests mock that module whole,
 * and these are pure helpers that must keep working under those mocks.
 */
import type { GradescopeConnectedVia, GradescopeConnectionState, GradescopeStatus } from "@/lib/api";

export const GRADESCOPE_AUTH_FAILED = "gradescope_auth_failed";
export const GRADESCOPE_REAUTH_REQUIRED = "gradescope_reauth_required";
export const GRADESCOPE_NOT_CONNECTED = "gradescope_not_connected";

/** The typed Gradescope code on a thrown API error, if it carries one. */
export function gradescopeErrorCode(err: unknown): string | undefined {
  if (err === null || typeof err !== "object") return undefined;
  const record = err as { code?: unknown; body?: unknown };
  if (typeof record.code === "string") return record.code;
  // Tolerate an error whose code only survived in the parsed body.
  const body = record.body as { error?: { code?: unknown } } | undefined;
  const nested = body?.error?.code;
  return typeof nested === "string" ? nested : undefined;
}

/** True when the remedy is "connect / reconnect Gradescope": the submitted or
 *  stored Gradescope credentials were rejected, or none are stored. */
export function needsGradescopeSignIn(err: unknown): boolean {
  const code = gradescopeErrorCode(err);
  return code === GRADESCOPE_AUTH_FAILED
    || code === GRADESCOPE_REAUTH_REQUIRED
    || code === GRADESCOPE_NOT_CONNECTED;
}

/** The connection state, derived for a backend that predates `state`. */
export function gradescopeConnectionState(status: GradescopeStatus): GradescopeConnectionState {
  if (status.state) return status.state;
  if (!status.has_credentials) return "disconnected";
  return status.needs_reauth ? "needs_reauth" : "connected";
}

/** How the stored session was obtained; derived from `auth_mode` for a
 *  backend that predates `connected_via`. Null when nothing is stored. */
export function gradescopeConnectedVia(status: GradescopeStatus): GradescopeConnectedVia | null {
  if (status.connected_via) return status.connected_via;
  if (!status.auth_mode) return null;
  return status.auth_mode === "password" ? "password" : "cookies";
}

/** Short label for how Gradescope is connected (Settings → Connections). */
export function gradescopeModeLabel(status: GradescopeStatus): string {
  const via = gradescopeConnectedVia(status);
  if (via === "password") return "password";
  if (via === "bu_sso") return "BU SSO";
  return "session cookies (SSO)";
}

/** What an expired session asks the student to do. Sapling never keeps a
 *  Gradescope or BU password, so a password user enters it again. */
export function gradescopeReauthMessage(status: GradescopeStatus): string {
  const via = gradescopeConnectedVia(status);
  if (via === "password") {
    return "Your Gradescope session expired. Enter your Gradescope password again to keep syncing; Sapling doesn't keep it.";
  }
  if (via === "bu_sso") return "Your Gradescope session expired. Sign in with BU again to keep syncing.";
  return "Gradescope rejected your saved session. Reconnect to keep syncing.";
}

/** The one-line status for an expired session (Settings → Connections). */
export function gradescopeReauthShort(status: GradescopeStatus): string {
  return gradescopeConnectedVia(status) === "password"
    ? "Session expired · enter your password again"
    : "Sign-in expired · reconnect needed";
}
