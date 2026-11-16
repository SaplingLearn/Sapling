/**
 * `GET /auth/start` — the first hop of every Google sign-in (sec2 M2).
 *
 * Sets this browser's sign-in nonce in an HttpOnly, host-only cookie
 * (`__Host-sapling_signin` over https) and redirects to the backend's
 * `/api/auth/google` with `binding = base64url(sha256(nonce))`. The session
 * BFF later exchanges the OAuth handoff only together with this cookie, so
 * the handoff works only in the browser that started the sign-in. See
 * lib/signinNonce.ts.
 *
 * The backend URL is the one the sign-in buttons used before this route
 * existed: the browser-facing API origin (`api.saplinglearn.com` /
 * `api.staging.saplinglearn.com`, derived from DEPLOY_ENV; else
 * NEXT_PUBLIC_API_URL; else this origin through the /api rewrite). That
 * matters: the backend's own OAuth state cookie lands on whichever host
 * `/api/auth/google` is served from, and Google calls back to the registered
 * GOOGLE_AUTH_REDIRECT_URI on the API host. The nonce cookie, by contrast,
 * lives on THIS host, where the BFF reads it.
 *
 * `popup_id` is passed through; `return_to` is always this route's own origin
 * (the backend honours it only for an allowlisted staging preview origin).
 */
import { NextRequest, NextResponse } from 'next/server';
import { resolveFrontendEnv } from '@/lib/deployGuard';
import { hostOnlyCookieOptions } from '@/lib/sessionCookie';
import {
  SIGNIN_NONCE_MAX_AGE,
  newSigninNonce,
  signinBinding,
  signinCookieName,
} from '@/lib/signinNonce';

export const dynamic = 'force-dynamic';

const POPUP_ID_RE = /^[A-Za-z0-9_-]{1,128}$/;

/** The browser-facing backend origin, or '' for this origin (the /api rewrite).
 * Never BACKEND_URL: that is the server-side origin (docker's backend:5000). */
function browserApiOrigin(): string {
  const env = process.env as Record<string, string | undefined>;
  const resolved = resolveFrontendEnv(env);
  const origin = resolved.derived ? resolved.apiUrl : (env.NEXT_PUBLIC_API_URL ?? '').trim();
  return origin.replace(/\/+$/, '');
}

export async function GET(request: NextRequest) {
  const nonce = newSigninNonce();
  const target = new URL(`${browserApiOrigin()}/api/auth/google`, request.url);
  const popupId = request.nextUrl.searchParams.get('popup_id');
  if (popupId && POPUP_ID_RE.test(popupId)) target.searchParams.set('popup_id', popupId);
  target.searchParams.set('return_to', request.nextUrl.origin);
  target.searchParams.set('binding', await signinBinding(nonce));

  const response = NextResponse.redirect(target, 302);
  response.headers.set('Cache-Control', 'no-store');
  response.cookies.set(
    signinCookieName(request),
    nonce,
    hostOnlyCookieOptions(request, SIGNIN_NONCE_MAX_AGE),
  );
  return response;
}
