/**
 * Where every Google sign-in starts (sec2 M2): the same-origin `/auth/start`
 * route, which sets this browser's sign-in nonce cookie and then sends it on
 * to the backend's `/api/auth/google` (see lib/signinNonce.ts). Client-safe:
 * no server imports. The route itself supplies `return_to` (its own origin).
 */
export const SIGNIN_START_PATH = '/auth/start';

/** The sign-in start path, with `popup_id` for the popup flow. */
export function signInStartPath(opts?: { popupId?: string }): string {
  if (!opts?.popupId) return SIGNIN_START_PATH;
  return `${SIGNIN_START_PATH}?popup_id=${encodeURIComponent(opts.popupId)}`;
}
