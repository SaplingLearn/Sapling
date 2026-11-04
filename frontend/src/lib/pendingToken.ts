/**
 * Hand-off for the short-lived pending token an unapproved Google sign-in
 * gets back from the backend (backend/routes/auth.py). It is not a session:
 * it carries only the account id, expires in about an hour, and is good for
 * exactly two calls — `getPendingStatus` and `joinWaitlistFromPending`.
 *
 * It arrives either on the same-tab redirect (`/pending?t=…`), on the
 * callback URL (`/auth/callback?error=not_approved&pending_token=…`), or over
 * the popup's BroadcastChannel. Every arrival stashes it here so `/pending`
 * can strip it from the address bar and still find it on a reload.
 *
 * sessionStorage, not localStorage: the token belongs to this tab's sign-in
 * attempt and should die with it. Every access is wrapped — private windows
 * and blocked site data make the accessor throw, and the page still has to
 * render (it falls back to the "sign in again" state).
 */
export const PENDING_TOKEN_KEY = 'sapling_pending_token';

export function stashPendingToken(token: string): void {
  try {
    window.sessionStorage.setItem(PENDING_TOKEN_KEY, token);
  } catch {}
}

export function readPendingToken(): string | null {
  try {
    return window.sessionStorage.getItem(PENDING_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function clearPendingToken(): void {
  try {
    window.sessionStorage.removeItem(PENDING_TOKEN_KEY);
  } catch {}
}
