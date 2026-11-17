/**
 * Which cookie carries the session, and how it is read, written and cleared
 * (sec2 M1). The one place that decides the cookie's NAME — the frontend twin
 * of backend services/session_tokens.py `session_cookie_name`.
 *
 * Over https (every deployed environment: prod, staging, previews) the session
 * cookie is HOST-ONLY and named `__Host-sapling_session`. The prefix makes the
 * browser refuse the cookie unless it is Secure, Path=/ and has no Domain, so
 * no sibling subdomain (staging.*, api.staging.*, a preview) can receive it,
 * overwrite it or plant one in its place. It used to be
 * `sapling_session; Domain=.saplinglearn.com`, sent to — and settable by —
 * every subdomain.
 *
 * Local http dev and the E2E stack cannot use the prefix (it requires Secure),
 * so they keep the plain `sapling_session` name.
 *
 * Transition (read-only grace): a session minted before this change lives in
 * the legacy plain-named, domain-wide cookie. It is still READ on https, but
 * only when the token lacks the `cookie: "host"` claim every session minted
 * now carries (`signSession`) — i.e. only a session the old BFF minted, all of
 * which expire within SESSION_MAX_AGE (7 days) of the deploy. A current session
 * planted under the old name by a sibling subdomain carries the claim and is
 * refused. Signing in or out clears the legacy cookie. Nobody is logged out by
 * the deploy, and the grace ends by itself.
 */
import { resolveFrontendEnv } from '@/lib/deployGuard';
import { verifySession } from '@/lib/sessionToken';
import { sanitizeCookieDomain } from '@/lib/cookieDomain';

/** The https (deployed) session cookie. */
export const HOST_SESSION_COOKIE_NAME = '__Host-sapling_session';
/** The http (local dev, E2E) session cookie — and, on https, the legacy one. */
export const PLAIN_SESSION_COOKIE_NAME = 'sapling_session';

/** What a request carries, cookies-wise (NextRequest, or a test double). */
export interface CookieRequest {
  url: string;
  headers: Headers;
  cookies: { get(name: string): { value: string } | undefined };
}

function env(): Record<string, string | undefined> {
  return process.env as Record<string, string | undefined>;
}

/** The request arrived over https (directly, or behind a TLS proxy). */
export function isHttpsRequest(request: Pick<CookieRequest, 'url' | 'headers'>): boolean {
  try {
    if (new URL(request.url).protocol === 'https:') return true;
  } catch {
    // fall through to the forwarded header
  }
  const forwarded = request.headers.get('x-forwarded-proto') ?? '';
  return forwarded.split(',')[0].trim().toLowerCase() === 'https';
}

/**
 * Whether this request's cookies use the `__Host-` names. Always in a deployed
 * environment (DEPLOY_ENV names prod or staging — previews included), whatever
 * the request's scheme says, so a stray plain-http request can never make the
 * worker fall back to the plain (tossable) name; otherwise by the scheme.
 */
export function usesHostCookies(request: Pick<CookieRequest, 'url' | 'headers'>): boolean {
  if (resolveFrontendEnv(env()).env !== null) return true;
  return isHttpsRequest(request);
}

/** The session cookie's name for this request. */
export function sessionCookieName(request: Pick<CookieRequest, 'url' | 'headers'>): string {
  return usesHostCookies(request) ? HOST_SESSION_COOKIE_NAME : PLAIN_SESSION_COOKIE_NAME;
}

/**
 * The raw (UNVERIFIED) session token this request carries, and whether it came
 * from the legacy cookie. Over https the `__Host-` cookie wins; the plain one
 * is read only as the legacy fallback. Over http the plain cookie is the
 * session cookie.
 */
export function readSessionCookie(
  request: CookieRequest,
): { token: string; legacy: boolean } | null {
  if (usesHostCookies(request)) {
    const host = request.cookies.get(HOST_SESSION_COOKIE_NAME)?.value;
    if (host) return { token: host, legacy: false };
    const legacy = request.cookies.get(PLAIN_SESSION_COOKIE_NAME)?.value;
    return legacy ? { token: legacy, legacy: true } : null;
  }
  const plain = request.cookies.get(PLAIN_SESSION_COOKIE_NAME)?.value;
  return plain ? { token: plain, legacy: false } : null;
}

/** The verified session this request carries (signature, expiry, age, type,
 * and the legacy-cookie rule above), with its raw token; null otherwise. */
export async function verifiedSessionCookie(
  request: CookieRequest,
): Promise<{ userId: string; token: string } | null> {
  const presented = readSessionCookie(request);
  if (!presented) return null;
  const session = await verifySession(presented.token, { legacyCookie: presented.legacy });
  return session ? { userId: session.userId, token: presented.token } : null;
}

/**
 * The `Cookie` header for a server-side call to the backend on this session's
 * behalf. Always the `__Host-` name: the backend reads it in every
 * environment, and the frontend has already applied the legacy rule above.
 */
export function backendSessionCookieHeader(token: string): string {
  return `${HOST_SESSION_COOKIE_NAME}=${token}`;
}

/** The `Secure` attribute for a cookie on this response: a `__Host-` cookie
 * must be Secure; a plain one is Secure in a production build or over https. */
export function cookieIsSecure(request: Pick<CookieRequest, 'url' | 'headers'>): boolean {
  if (usesHostCookies(request)) return true;
  if (process.env.NODE_ENV === 'production') return true;
  return isHttpsRequest(request);
}

/** Attributes for the session cookie (and the sign-in nonce cookie): host-only
 * (never a Domain), Path=/, HttpOnly, SameSite=Lax. */
export function hostOnlyCookieOptions(
  request: Pick<CookieRequest, 'url' | 'headers'>,
  maxAge: number,
): { httpOnly: true; sameSite: 'lax'; secure: boolean; path: '/'; maxAge: number } {
  return { httpOnly: true, sameSite: 'lax', secure: cookieIsSecure(request), path: '/', maxAge };
}

/**
 * `Set-Cookie` header values that delete the LEGACY plain-named session cookie
 * on an https host: once with the old Domain (`.saplinglearn.com` /
 * `.staging.saplinglearn.com`, when this host is inside it) and once host-only
 * (what a preview got). Empty over http, where the plain cookie is the live
 * session cookie. Appended raw because a response's cookie map holds one entry
 * per name.
 */
export function legacySessionCookieClears(
  request: Pick<CookieRequest, 'url' | 'headers'>,
): string[] {
  if (!usesHostCookies(request)) return [];
  const base = `${PLAIN_SESSION_COOKIE_NAME}=; Path=/; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Secure; HttpOnly; SameSite=Lax`;
  const clears = [base];
  const domain = sanitizeCookieDomain(resolveFrontendEnv(env()).cookieDomain);
  if (domain) {
    let host = '';
    try {
      host = new URL(request.url).hostname.toLowerCase();
    } catch {
      host = '';
    }
    const bare = domain.replace(/^\./, '');
    if (host === bare || host.endsWith(`.${bare}`)) clears.push(`${base}; Domain=${domain}`);
  }
  return clears;
}
