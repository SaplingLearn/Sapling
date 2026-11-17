import { NextRequest, NextResponse } from 'next/server';
import { signSession, tokenTypeOf, SESSION_MAX_AGE } from '@/lib/sessionToken';
import { resolveFrontendEnv } from '@/lib/deployGuard';
import {
  HOST_SESSION_COOKIE_NAME,
  PLAIN_SESSION_COOKIE_NAME,
  backendSessionCookieHeader,
  hostOnlyCookieOptions,
  legacySessionCookieClears,
  readSessionCookie,
  sessionCookieName,
  usesHostCookies,
} from '@/lib/sessionCookie';
import { signinCookieName } from '@/lib/signinNonce';

const SESSION_SECRET = process.env.SESSION_SECRET;
// The backend origin as seen from this server (the middleware's choice too):
// the handoff is consumed there before a session is minted, and sign-out
// revokes the session there before the cookie is cleared.
const RESOLVED_ENV = resolveFrontendEnv(process.env as Record<string, string | undefined>);
const BACKEND_ORIGIN = RESOLVED_ENV.apiUrl.replace(/\/+$/, '');
const BACKEND_TIMEOUT_MS = 5000;

// sec2 M1: the session cookie is host-only — `__Host-sapling_session` (no
// Domain, Secure, Path=/) over https, the plain name over http (local dev,
// E2E). lib/sessionCookie.ts owns the name and the attributes; this route only
// sets, clears and reads through it. It used to carry
// `Domain=.saplinglearn.com`, which sent it to (and let it be overwritten by)
// every subdomain; signing in or out now also deletes that legacy cookie.

async function backendFetch(path: string, init: RequestInit): Promise<Response | null> {
  if (!BACKEND_ORIGIN) return null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);
  try {
    return await fetch(`${BACKEND_ORIGIN}${path}`, {
      ...init,
      signal: controller.signal,
      cache: 'no-store',
    });
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * Revoke every session of the cookie's account on the backend
 * (POST /api/auth/logout stamps `users.sessions_valid_after`), so a copy of
 * the token stops working now instead of at its `exp`. Best effort: the
 * cookie is cleared whatever happens here — a user who asked to sign out is
 * signed out of this browser either way. True when the backend confirmed.
 * A server-side call (no Origin, no Sec-Fetch-*): the backend's CSRF origin
 * check treats it as a non-browser client.
 */
async function revokeOnBackend(token: string): Promise<boolean> {
  const res = await backendFetch('/api/auth/logout', {
    method: 'POST',
    headers: { Cookie: backendSessionCookieHeader(token) },
  });
  return !!res?.ok;
}

/**
 * sec2 M2: consume the OAuth handoff on the backend
 * (POST /api/auth/handoff/exchange), which checks that it is genuine, bound
 * to THIS browser's sign-in nonce, and never exchanged before (single use
 * across replicas). The user id it signs in, or null when refused; 'unavailable'
 * when the backend could not answer.
 */
async function exchangeOnBackend(
  authToken: string,
  nonce: string | undefined,
): Promise<string | null | 'unavailable'> {
  const res = await backendFetch('/api/auth/handoff/exchange', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token: authToken, nonce: nonce ?? null }),
  });
  if (!res) return 'unavailable';
  if (res.status >= 500) return 'unavailable';
  if (!res.ok) return null;
  try {
    const body = (await res.json()) as { user_id?: unknown };
    return typeof body.user_id === 'string' && body.user_id ? body.user_id : null;
  } catch {
    return 'unavailable';
  }
}

/**
 * CSRF defense beyond SameSite=Lax (#190): reject cross-origin requests to the
 * session endpoint. When a browser sends an Origin header (always, for these
 * fetch POST/DELETE calls), its host must match this route's host. A missing
 * Origin (non-browser client) is allowed — CSRF is a browser-driven attack and
 * browsers always send Origin here. This is the documented anti-CSRF strategy
 * for the state-changing session endpoint, layered on top of SameSite=Lax.
 */
function isCrossOrigin(request: NextRequest): boolean {
  const origin = request.headers.get('origin');
  if (!origin) return false;
  try {
    return new URL(origin).host !== request.nextUrl.host;
  } catch {
    return true;
  }
}

function b64urlToBytes(s: string): Uint8Array<ArrayBuffer> {
  const padded = s.replace(/-/g, '+').replace(/_/g, '/');
  const pad = '='.repeat((4 - (padded.length % 4)) % 4);
  const binary = atob(padded + pad);
  const buf = new ArrayBuffer(binary.length);
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/**
 * The user id of a validly signed, unexpired OAuth HANDOFF token (the backend's
 * redirect token, `typ=handoff`), or null — a cheap local pre-check before the
 * backend exchange, so garbage never costs a round trip. #756: a session token
 * is refused, so a session can never be re-minted into a fresh one. sec2 M2:
 * an untyped token is no longer exchanged (a handoff must carry `jti` and `bh`,
 * which only a current backend mints); the backend decides the rest.
 */
async function verifyAuthToken(token: string): Promise<string | null> {
  if (!SESSION_SECRET) return null;
  const dot = token.lastIndexOf('.');
  if (dot < 0) return null;
  const payloadB64 = token.slice(0, dot);
  const sigB64 = token.slice(dot + 1);
  try {
    const key = await crypto.subtle.importKey(
      'raw',
      new TextEncoder().encode(SESSION_SECRET),
      { name: 'HMAC', hash: 'SHA-256' },
      false,
      ['verify'],
    );
    const valid = await crypto.subtle.verify(
      'HMAC',
      key,
      b64urlToBytes(sigB64),
      new TextEncoder().encode(payloadB64),
    );
    if (!valid) return null;

    const payload = JSON.parse(new TextDecoder().decode(b64urlToBytes(payloadB64)));
    const now = Math.floor(Date.now() / 1000);
    if (typeof payload.exp !== 'number' || payload.exp < now) return null;
    if (typeof payload.user_id !== 'string') return null;
    if (payload.typ === undefined || tokenTypeOf(payload) !== 'handoff') return null;
    return payload.user_id;
  } catch {
    return null;
  }
}

/** Delete the sign-in nonce cookie (it has done its job, or must not linger). */
function clearSigninNonce(response: NextResponse, request: NextRequest): void {
  response.cookies.set(signinCookieName(request), '', hostOnlyCookieOptions(request, 0));
}

/** Append the legacy domain-wide session cookie's deletions. Called LAST:
 * `response.cookies.set` rewrites every Set-Cookie header from its own map. */
function appendLegacyClears(response: NextResponse, request: NextRequest): void {
  for (const header of legacySessionCookieClears(request)) {
    response.headers.append('Set-Cookie', header);
  }
}

export async function POST(request: NextRequest) {
  if (isCrossOrigin(request)) {
    return NextResponse.json({ error: 'Cross-origin request rejected' }, { status: 403 });
  }

  // `request.json()` THROWS on an absent or malformed body, and the throw
  // escaped this handler — so `POST /api/auth/session` with a non-JSON body
  // (trivially reachable: curl, or any client that forgets the body) answered
  // 500 with a stack trace in the worker logs instead of a 400. Parse
  // defensively and treat anything unusable as a missing token.
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON body' }, { status: 400 });
  }
  const authToken =
    body && typeof body === 'object' && typeof (body as { authToken?: unknown }).authToken === 'string'
      ? (body as { authToken: string }).authToken
      : undefined;

  if (!SESSION_SECRET) {
    return NextResponse.json(
      { error: 'SESSION_SECRET is not configured on the frontend deployment' },
      { status: 500 },
    );
  }
  if (!authToken) {
    return NextResponse.json({ error: 'authToken is required' }, { status: 400 });
  }

  const verifiedUserId = await verifyAuthToken(authToken);
  if (!verifiedUserId) {
    return NextResponse.json(
      { error: 'Invalid or expired auth token (SESSION_SECRET likely does not match the backend)' },
      { status: 401 },
    );
  }

  // sec2 M2: single use, and only in the browser that started this sign-in
  // (its HttpOnly nonce cookie, set by /auth/start). Whatever the answer, the
  // nonce is spent.
  const nonce = request.cookies.get(signinCookieName(request))?.value;
  const exchanged = await exchangeOnBackend(authToken, nonce);
  if (exchanged === 'unavailable') {
    const res = NextResponse.json({ error: 'Could not complete sign-in' }, { status: 503 });
    clearSigninNonce(res, request);
    return res;
  }
  if (exchanged === null || exchanged !== verifiedUserId) {
    const res = NextResponse.json(
      { error: 'This sign-in link is invalid, was already used, or was started in another browser' },
      { status: 401 },
    );
    clearSigninNonce(res, request);
    return res;
  }

  try {
    const token = await signSession(exchanged);
    const response = NextResponse.json({ ok: true });
    response.cookies.set(sessionCookieName(request), token, hostOnlyCookieOptions(request, SESSION_MAX_AGE));
    clearSigninNonce(response, request);
    appendLegacyClears(response, request);
    return response;
  } catch {
    return NextResponse.json({ error: 'Session signing failed — SESSION_SECRET may not be configured' }, { status: 500 });
  }
}

export async function DELETE(request: NextRequest) {
  if (isCrossOrigin(request)) {
    return NextResponse.json({ error: 'Cross-origin request rejected' }, { status: 403 });
  }

  // Revoke server-side first, while the cookie still authenticates the call.
  // Revocation covers every session of the account (sign out everywhere);
  // `?scope=local` only drops this browser's cookie — for the sign-in
  // callback discarding a half-made session, which must not sign the student
  // out of their other devices.
  const token = readSessionCookie(request)?.token;
  const localOnly = request.nextUrl.searchParams.get('scope') === 'local';
  const revoked = token && !localOnly ? await revokeOnBackend(token) : false;

  const response = NextResponse.json({ ok: true, revoked });
  // Over https: the `__Host-` cookie, then (below) every legacy plain one.
  // Over http the plain cookie IS the session cookie.
  response.cookies.set(
    usesHostCookies(request) ? HOST_SESSION_COOKIE_NAME : PLAIN_SESSION_COOKIE_NAME,
    '',
    hostOnlyCookieOptions(request, 0),
  );
  appendLegacyClears(response, request);
  return response;
}
