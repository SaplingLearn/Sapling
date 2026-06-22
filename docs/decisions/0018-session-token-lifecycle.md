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
   `httpOnly`, `Secure`, `SameSite=Lax` **`sapling_session` cookie** (scoped to
   `COOKIE_DOMAIN` so it is also sent to the backend subdomain).

3. **Backend — every authed request** (`services/auth_guard.py::_decode_session`)
   reads `sapling_session` from the cookie, verifies the HMAC with the same
   `SESSION_SECRET`, and checks `exp`. Because the frontend signed it in a
   **byte-identical format** (`payload_b64.sig_b64`, base64url no padding,
   HMAC-SHA256 over the payload bytes, JSON `{"user_id", "exp"}`) with a 30-day
   `exp`, the backend accepts it for the full 30 days.

So the effective session lifetime is **30 days**, refreshed implicitly on the
next sign-in. The 5-minute death scenario does not occur in the deployed
frontend-BFF topology.

## Preconditions (operational)

The contract holds only if both are true in production:

- **`SESSION_SECRET` is identical** on the frontend and backend deployments
  (the BFF returns 401 "Invalid or expired auth token (SESSION_SECRET likely
  does not match the backend)" if not).
- **`COOKIE_DOMAIN` covers both subdomains** so the browser sends
  `sapling_session` to the backend on cross-origin API calls (`credentials:
  'include'`). An unset/host-only cookie would not reach the backend.

## Decision

No backend session-lifetime bug to fix. Changes made under #168:

- Named the magic `300` as `_REDIRECT_TOKEN_TTL_SECONDS` (env-overridable via
  `SAPLING_AUTH_REDIRECT_TOKEN_TTL`) and corrected the comment to state it is
  the redirect-handoff TTL, not the session TTL.
- Added `tests/test_auth_session_contract.py` to lock the cross-service token
  contract: a frontend-style 30-day token is accepted by the backend decoder,
  expired/tampered tokens are rejected.

## Follow-ups (not blocking, out of scope here)

- Sliding refresh: the 30-day token is fixed-window, not sliding. If a sliding
  session is desired, the BFF should re-mint on activity. Frontend scope.
- The two services independently re-implement the same token format; a shared
  spec/fixture (this doc + the contract test) is the guard against drift.
