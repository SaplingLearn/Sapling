/**
 * Admin step-up (backend services/auth_guard.py). Admin routes need a recent
 * Google sign-in: 12 h, and 30 min for destructive actions. An older session
 * answers 401 with `detail.code === "reauth_required"`. That is NOT a dead
 * session — the rest of the app keeps working — so `fetchJSON` (lib/api.ts)
 * does not report it to the session-expired listeners (which tear the
 * identity down); it reports it here, and the admin screens'
 * `AdminReauthBanner` offers to sign in again.
 *
 * Its own module (not lib/api.ts) so a test that mocks `@/lib/api` still
 * gets the real listener plumbing.
 */

import { signInStartPath } from '@/lib/signinStart';

/** The `detail.code` (or coded-envelope `error.code`) of an admin step-up 401. */
export const REAUTH_REQUIRED = 'reauth_required';

/** sessionStorage key: where to land after the step-up sign-in (same tab). */
export const POST_SIGNIN_PATH_KEY = 'sapling_post_signin_path';

type ReauthListener = () => void;
const reauthListeners = new Set<ReauthListener>();

/** Subscribe to "an admin call needs a fresh sign-in". Returns the unsubscribe. */
export function onReauthRequired(listener: ReauthListener): () => void {
  reauthListeners.add(listener);
  return () => {
    reauthListeners.delete(listener);
  };
}

export function notifyReauthRequired(): void {
  for (const listener of [...reauthListeners]) {
    try {
      listener();
    } catch (err) {
      console.error('[reauth] listener failed', err);
    }
  }
}

/** Whether a parsed error body is the admin step-up 401's. */
export function isReauthRequired(body: unknown): boolean {
  if (body === null || typeof body !== 'object') return false;
  const record = body as Record<string, unknown>;
  for (const key of ['detail', 'error']) {
    const inner = record[key];
    if (inner !== null && typeof inner === 'object'
        && (inner as Record<string, unknown>).code === REAUTH_REQUIRED) return true;
  }
  return false;
}

/**
 * Send the admin through Google sign-in again (same tab), remembering the
 * current admin page so the callback can return there. A fresh sign-in mints
 * a fresh session, which satisfies the step-up window. Same-origin
 * `/auth/start`, as the sign-in modal and /pending use.
 */
export function startReauth(): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.setItem(
      POST_SIGNIN_PATH_KEY,
      `${window.location.pathname}${window.location.search}`,
    );
  } catch {}
  // Absolute, on this origin: /auth/start sets the sign-in nonce cookie
  // (sec2 M2) and hands on to the backend's /api/auth/google. A route
  // handler, not a page: it needs a full navigation, never router.push.
  window.location.assign(`${window.location.origin}${signInStartPath()}`);
}

/**
 * The admin page `startReauth` left from, once, then forgotten. Only an
 * in-app `/admin` path is honoured, so the stash can never send the browser
 * anywhere else (no open redirect).
 */
export function takePostSignInPath(): string | null {
  if (typeof window === 'undefined') return null;
  let path: string | null = null;
  try {
    path = window.sessionStorage.getItem(POST_SIGNIN_PATH_KEY);
    window.sessionStorage.removeItem(POST_SIGNIN_PATH_KEY);
  } catch {
    return null;
  }
  if (!path || !/^\/admin(?:[/?#]|$)/.test(path)) return null;
  return path;
}
