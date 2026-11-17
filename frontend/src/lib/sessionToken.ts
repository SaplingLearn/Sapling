/**
 * The session cookie's NAME depends on the request (`__Host-sapling_session`
 * over https, `sapling_session` over http): lib/sessionCookie.ts decides it.
 */

/**
 * The claim every session minted here carries (sec2 M1): it was minted for
 * the host-only `__Host-` cookie. The legacy domain-wide cookie is honoured
 * only for a token WITHOUT it (minted before the host-only cookie), so a
 * sibling subdomain cannot plant a current session under the old name.
 * Twin of backend services/session_tokens.py `HOST_COOKIE_CLAIM`.
 */
export const HOST_COOKIE_CLAIM = 'cookie';
export const HOST_COOKIE_CLAIM_VALUE = 'host';

/**
 * A session's lifetime from issue (`iat`), in seconds: 7 days. Twin of backend
 * config.py `SESSION_MAX_AGE_SECONDS`, which refuses an older session whatever
 * its `exp` says. Sign-out revokes a session sooner, server-side
 * (`users.sessions_valid_after`, via the session BFF's DELETE).
 */
export const SESSION_MAX_AGE = 604800;

/** What the BFF minted before `iat` existed: such a session is dated
 * `exp - LEGACY_SESSION_LIFETIME` (backend auth_guard.session_issued_at). */
const LEGACY_SESSION_LIFETIME = 2592000; // 30 days

/** Tolerance for an `iat` slightly in the future (separate clocks). */
const IAT_CLOCK_SKEW = 300;

/** When a verified session payload was issued (unix seconds). */
export function issuedAt(payload: { iat?: unknown; exp?: unknown }): number | null {
  if (typeof payload.iat === 'number') return Math.floor(payload.iat);
  if (typeof payload.exp === 'number') return Math.floor(payload.exp) - LEGACY_SESSION_LIFETIME;
  return null;
}

/**
 * The token's `typ` claim (#756) — twin of backend services/session_tokens.py.
 * `session` is the API credential this module mints into the cookie; `handoff`
 * is the short-lived token the OAuth callback puts in the redirect, which only
 * the session BFF (`app/api/auth/session`) may exchange. A legacy token minted
 * before the claim existed carries none and counts as a `session`.
 */
export type TokenType = 'session' | 'handoff';

function getSecret(): string {
  const secret = process.env.SESSION_SECRET;
  if (!secret) throw new Error('SESSION_SECRET env var is not set');
  if (new TextEncoder().encode(secret).byteLength < 32)
    throw new Error('SESSION_SECRET must be at least 32 bytes long');
  return secret;
}

function toBase64Url(buf: ArrayBuffer | Uint8Array): string {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

function fromBase64Url(str: string): Uint8Array<ArrayBuffer> {
  const padded = str.replace(/-/g, '+').replace(/_/g, '/');
  const padding = '='.repeat((4 - (padded.length % 4)) % 4);
  const binary = atob(padded + padding);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function importKey(): Promise<CryptoKey> {
  const raw = new TextEncoder().encode(getSecret());
  return crypto.subtle.importKey('raw', raw, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']);
}

export async function signSession(userId: string): Promise<string> {
  // Unix seconds TRUNCATED to the millisecond (a JWT NumericDate may be
  // fractional): never rounded up, which could date a session after a
  // sign-out it preceded. Date.now() is already whole milliseconds; the floor
  // keeps that true whatever it returns.
  const now = Math.floor(Date.now()) / 1000;
  // `iat` is what server-side revocation (sign-out) and the admin step-up
  // window compare against (backend services/auth_guard.py). Its milliseconds
  // keep a session minted earlier in a sign-out's own second older than the
  // sign-out (auth_guard.issued_before); `exp` stays whole seconds.
  // `iat_precision: 'ms'` says so: JSON.stringify writes an iat on a whole
  // second as an integer, which without it would read as a legacy
  // whole-second iat (twin of backend session_tokens.IAT_PRECISION_CLAIM).
  const payload = JSON.stringify({
    user_id: userId,
    exp: Math.floor(now) + SESSION_MAX_AGE,
    typ: 'session',
    iat: now,
    iat_precision: 'ms',
    [HOST_COOKIE_CLAIM]: HOST_COOKIE_CLAIM_VALUE,
  });
  const payloadB64 = toBase64Url(new TextEncoder().encode(payload));
  const key = await importKey();
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payloadB64));
  return `${payloadB64}.${toBase64Url(sig)}`;
}

/** The verified token's `typ`, a legacy (absent) claim reading as `session`;
 * null for anything else. */
export function tokenTypeOf(payload: { typ?: unknown }): TokenType | null {
  const typ = payload.typ ?? 'session';
  return typ === 'session' || typ === 'handoff' ? typ : null;
}

/** Verify a session cookie value: signature, expiry, age (at most
 * SESSION_MAX_AGE since `iat`), and that it is a SESSION token — a `handoff`
 * token is not a session (#756). `legacyCookie`: the token came from the
 * legacy plain-named cookie on an https host, honoured only for a session
 * minted before the host-only cookie (no HOST_COOKIE_CLAIM). Revocation is
 * the backend's to decide. */
export async function verifySession(
  token: string,
  opts?: { legacyCookie?: boolean },
): Promise<{ userId: string } | null> {
  const dot = token.lastIndexOf('.');
  if (dot < 0) return null;
  const payloadB64 = token.slice(0, dot);
  const sigB64 = token.slice(dot + 1);
  try {
    const key = await importKey();
    const valid = await crypto.subtle.verify(
      'HMAC',
      key,
      fromBase64Url(sigB64),
      new TextEncoder().encode(payloadB64),
    );
    if (!valid) return null;
    const payload = JSON.parse(new TextDecoder().decode(fromBase64Url(payloadB64)));
    const now = Math.floor(Date.now() / 1000);
    if (typeof payload.exp !== 'number' || payload.exp < now) return null;
    const iat = issuedAt(payload);
    if (iat === null || iat > now + IAT_CLOCK_SKEW || now - iat > SESSION_MAX_AGE) return null;
    if (typeof payload.user_id !== 'string') return null;
    if (tokenTypeOf(payload) !== 'session') return null;
    if (opts?.legacyCookie && payload[HOST_COOKIE_CLAIM] === HOST_COOKIE_CLAIM_VALUE) return null;
    return { userId: payload.user_id };
  } catch {
    return null;
  }
}
