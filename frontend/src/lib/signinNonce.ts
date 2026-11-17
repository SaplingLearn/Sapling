/**
 * The sign-in nonce that binds an OAuth handoff to the browser that started
 * the sign-in (sec2 M2).
 *
 * `/auth/start` (app/auth/start/route.ts) mints a random nonce into an
 * HttpOnly, host-only cookie and sends `binding = base64url(sha256(nonce))` to
 * the backend's `GET /api/auth/google`. The backend seals the binding into its
 * signed OAuth state and signs it into the handoff (`bh`). The session BFF
 * (app/api/auth/session) sends the handoff AND this cookie's nonce to the
 * backend's `POST /api/auth/handoff/exchange`, which refuses a handoff whose
 * binding the nonce does not hash to, and consumes it so it works only once.
 * A handoff link opened in any other browser (the login-CSRF / fixation
 * attack: an attacker's own callback link sent to a victim) is refused.
 *
 * Twin of backend services/auth/handoff.py.
 */
import { usesHostCookies, type CookieRequest } from '@/lib/sessionCookie';

export const HOST_SIGNIN_COOKIE_NAME = '__Host-sapling_signin';
export const PLAIN_SIGNIN_COOKIE_NAME = 'sapling_signin';

/** How long a started sign-in may take (the backend's OAuth state cookie
 * lives as long). */
export const SIGNIN_NONCE_MAX_AGE = 600;

/** The sign-in nonce cookie's name for this request (`__Host-` over https). */
export function signinCookieName(request: Pick<CookieRequest, 'url' | 'headers'>): string {
  return usesHostCookies(request) ? HOST_SIGNIN_COOKIE_NAME : PLAIN_SIGNIN_COOKIE_NAME;
}

function toBase64Url(bytes: Uint8Array): string {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

/** A fresh nonce: 32 random bytes, base64url (43 characters). */
export function newSigninNonce(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return toBase64Url(bytes);
}

/** `base64url(sha256(nonce))` without padding — twin of backend
 * handoff.binding_for_nonce. */
export async function signinBinding(nonce: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(nonce));
  return toBase64Url(new Uint8Array(digest));
}
