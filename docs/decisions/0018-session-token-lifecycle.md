# 0018 — Session token lifecycle (verification of #168)

**Status:** documented · **Issue:** #168 (filed as a flagged "verify" finding)

## The claim

#168 raised the concern that the backend session has a hard 5-minute lifetime
with no refresh path: the only place the backend mints a token is the OAuth
callback with `exp = now + 300`, there is no `/refresh` route, and the
`sapling_session` cookie the decoder accepts is never `set_cookie`'d by the
backend. If accurate, every request would 401 with "Session expired" five
minutes after sign-in and force a full Google re-login.

## What actually happens

Verified by reading the full path across both services. The 300-second token is
**not** the session — it is a one-shot handoff token:

1. **Backend — OAuth callback** (`routes/auth.py`) mints a short-lived HMAC
   token (`{user_id, exp}`, `exp = now + _REDIRECT_TOKEN_TTL_SECONDS`, default
   300s) and redirects to `FRONTEND_URL/auth/callback?auth_token=…`. It only
   needs to survive the redirect round-trip.

2. **Frontend — session BFF** (`frontend/src/app/api/auth/session/route.ts`)
   receives that `auth_token`, verifies its HMAC + expiry against the shared
   `SESSION_SECRET`, and on success re-mints a **30-day** token
   (`signSession`, `SESSION_MAX_AGE = 2592000`) which it sets as the
   `httpOnly`, `Secure`, `SameSite=Lax` **`sapling_session` cookie**.

3. **Backend — every authed request** (`services/auth_guard.py::_decode_session`)
   reads `sapling_session` from the cookie, verifies the HMAC with the same
   `SESSION_SECRET`, and checks `exp`. Because the frontend signed it in a
   **compatible format** (`payload_b64.sig_b64`, base64url no padding,
   HMAC-SHA256 over the `payload_b64` *string*, JSON `{"user_id", "exp"}`) with
   a 30-day `exp`, the backend accepts it for the full 30 days.

   The two mints are compatible, not byte-identical: Python's `json.dumps` emits
   `{"user_id": "x", "exp": 1}` (with spaces), JS `JSON.stringify` emits
   `{"user_id":"x","exp":1}` (without). This is immaterial — the verifier HMACs
   the received `payload_b64` opaquely and never re-serializes — but the formats
   are *interoperable*, not identical, and nothing should be built on assuming
   the latter.

So the effective session lifetime is **30 days**, refreshed implicitly on the
next sign-in. The 5-minute death scenario does not occur in the deployed
frontend-BFF topology.

## How the cookie actually reaches the backend

**Authed API calls are same-origin.** `frontend/src/lib/api.ts` sets
`API_URL = ''`, so all ~135 `fetchJSON` call sites request same-origin paths like
`/api/graph/…`. `frontend/next.config.ts` rewrites `/api/:path*` →
`${BACKEND_URL}/api/:path*` **server-side**, and that server-side hop forwards the
`Cookie` header to the backend. The browser never makes a cross-origin authed API
call, so the cookie's `domain` attribute is not what carries it to the backend —
a host-only cookie would reach the backend just fine.

## Preconditions (operational)

The contract holds only if both are true in production:

- **`SESSION_SECRET` is identical** on the frontend and backend deployments
  (the BFF returns 401 "Invalid or expired auth token (SESSION_SECRET likely
  does not match the backend)" if not).
- **`BACKEND_URL` is set at _build_ time** on the Cloudflare Worker. It is read
  in `next.config.ts` at build time and baked into the rewrite, *not* resolved
  per-request from the runtime env. Set only as a runtime var, the rewrite falls
  back to `http://localhost:5000` and every `/api/*` call 500s — which looks like
  a session bug but is a config bug. This is the genuinely load-bearing
  precondition.

`COOKIE_DOMAIN` governs only the cookie's `domain` attribute (widening it from
host-only to all `*.saplinglearn.com` hosts). It is set — `.saplinglearn.com` in
`frontend/wrangler.toml`, validated through `sanitizeCookieDomain` (#190) — so
nothing is broken today, but it is **not** the mechanism by which the session
reaches the backend, and the contract would hold without it.

> **Do not "fix" an authed call by pointing it at `NEXT_PUBLIC_API_URL`.** That
> makes the request cross-origin, and the browser will not attach
> `sapling_session` unless the call also sets `credentials: 'include'` *and* the
> backend runs the matching CORS + cookie-domain setup. This is exactly the
> 2026-06-30 onboarding-loop bug: onboarding POSTed to
> `${NEXT_PUBLIC_API_URL}/api/onboarding/profile` cross-origin with no
> `credentials`, so the cookie was dropped, `require_self` 401'd, and
> `onboarding_completed` never flipped — trapping the user in "Get Started" on
> every sign-in. It was fixed by routing through `submitOnboardingProfile()` →
> `fetchJSON`; `frontend/src/app/(public)/page.tsx` still carries a comment
> recording it. Authed calls go through `lib/api.ts` `fetchJSON`; see
> `frontend/.env.example`, which documents leaving `NEXT_PUBLIC_API_URL` empty in
> production.

## Decision

No backend session-lifetime bug to fix. Changes made under #168:

- Named the magic `300` as `_REDIRECT_TOKEN_TTL_SECONDS` (env-overridable via
  `SAPLING_AUTH_REDIRECT_TOKEN_TTL`) and corrected the comment to state it is
  the redirect-handoff TTL, not the session TTL.
- Added `tests/test_auth_session_contract.py` covering the backend half of the
  token contract: a frontend-*style* 30-day token is accepted by the backend
  decoder, expired/tampered/wrong-secret tokens are rejected.
- Hardened the `SAPLING_AUTH_REDIRECT_TOKEN_TTL` override: it is parsed inside a
  `try/except ValueError` and falls back to 300s with a warning. `routes/auth.py`
  is imported at router-mount time, so a malformed value (`abc`, or the var
  declared with an empty value) previously raised at import and stopped the app
  from booting.

## Follow-ups (not blocking, out of scope here)

- **`?auth_token=` is a live but unused credential channel.**
  `auth_guard._decode_session` reads `request.query_params["auth_token"]` *before*
  the cookie, but no client sends it to the backend: the backend puts the redirect
  token in a URL pointing at the *frontend*, and `auth/callback/page.tsx` reads it
  there and POSTs it to the BFF in a JSON body. The decoder applies no
  ttl/purpose distinction, so a 30-day session token in `?auth_token=` is accepted
  identically — and tokens in URLs leak via access logs, `Referer`, and history.
  Removing the channel is its own change (it is not a session-lifetime issue);
  `test_legacy_unused_auth_token_query_param_is_still_accepted` characterizes
  today's behaviour so the removal is a deliberate, visible edit.
- **The contract test is not yet a true cross-service lock.** Its `_mint` helper
  is a *third* Python re-implementation of the format, so it proves a
  Python-minted token is accepted, not a real frontend-minted one. There is no
  `frontend/src/lib/sessionToken.test.ts`, and the BFF (`route.ts`) hand-rolls
  `verifyAuthToken` as a duplicate of `sessionToken.ts::verifySession` — two
  frontend copies to drift from. The real lock would be a **shared JSON fixture**
  (tokens + expected verdicts) checked into the repo and consumed by both the
  pytest suite and a frontend test.
- Sliding refresh: the 30-day token is fixed-window, not sliding. If a sliding
  session is desired, the BFF should re-mint on activity. Frontend scope.
- Fix `page.tsx:619` (#339) to route onboarding through `lib/api.ts` `fetchJSON`.
