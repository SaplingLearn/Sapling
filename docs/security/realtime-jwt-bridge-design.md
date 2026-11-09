# Realtime option (a) — JWT-mint bridge (design, #231)

**Status: SHIPPED behind the `realtime_rls` flag (RLS step 2e, Trov #115).**
What was built, and the manual enable sequence, are in "Step 2e (shipped)" at
the end; the sections before it are the original design.

## Goal
Keep live chat working once RLS is enabled, **without** the public anon key:
the realtime client authenticates as the logged-in user via a Supabase JWT, and
an RLS policy scopes delivery to the user's room memberships.

## Why a JWT is needed
Sapling uses its **own HMAC session** (`sapling_session`), not Supabase Auth, so
`auth.uid()` is empty and RLS can't identify the user. We bridge by minting a
Supabase-format JWT for the same user and handing it to the realtime client.

## Components

### 1. Mint a Supabase JWT (backend)
At login (and on refresh), the backend mints a short-lived JWT signed with the
**Supabase JWT secret** (legacy HS256; the same secret behind the anon key):
```
claims: { sub: <user_id>, role: "authenticated", aud: "authenticated", exp: now+1h, iat: now }
```
- New endpoint, e.g. `GET /api/auth/realtime-token` (auth-gated by the existing
  session): returns `{ token, expires_at }`, minted from the still-valid 30-day
  session.
- New env `SUPABASE_JWT_SECRET` (from Supabase → Settings → API → JWT secret).
  Add it to `validate_config()` (#174) as required outside local.
- Note: Supabase is migrating to **asymmetric signing keys**. If this project is
  on the new keys, mint/verify with the project's signing key instead of an
  HS256 shared secret — confirm which at build time.

### 2. RLS SELECT policy on room_messages (membership-scoped)
```sql
CREATE POLICY room_messages_member_read ON public.room_messages
  FOR SELECT TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.room_members m
    WHERE m.room_id = room_messages.room_id AND m.user_id = auth.uid()
  ));
```
With the lockdown's RLS enabled and the JWT setting `auth.uid()`, an
`authenticated` subscriber receives changes **only for rooms they belong to** —
the client-side `room_id` filter stops being the only gate. (`authenticated`
still holds the table GRANT SELECT, which the lockdown intentionally left.)

### 3. Realtime delivery
Two options, smallest first:
- **(i) postgres_changes + the RLS policy above (recommended).** Realtime
  evaluates the subscriber's RLS on each change, so the existing
  `Social.tsx` subscription keeps working but is now membership-scoped. Minimal
  client change: set the JWT (below). `room_messages` is already in the
  `supabase_realtime` publication.
- **(ii) Private channels (Realtime Authorization).** Mark the channel
  `{ config: { private: true } }` and add a policy on `realtime.messages` for
  the topic. More robust/explicit but a larger client rework. Defer unless (i)
  proves insufficient.

### 4. Client wiring (frontend)
- After login, fetch the realtime token and apply it:
  `getSupabase().realtime.setAuth(token)` (and pass it when (re)creating the
  client). The client stops relying on the anon key for authorization.
- **JWT refresh (the main complexity):** the session is **30 days** but the
  Supabase JWT is **~1 hour**. Add a refresh loop — re-fetch the token shortly
  before `expires_at` and call `setAuth` again — or the subscription drops when
  the JWT expires. Handle: tab wake from sleep, network reconnect, and a failed
  refresh (fall back to REST-only, which the #230 display fix already supports).

## Sequencing
1. RLS lockdown (separate, urgent) — breaks anon realtime (accepted).
2. This bridge — restores realtime for authenticated users, membership-scoped.

## Effort estimate
Moderate. Backend JWT-mint endpoint + env wiring (small); RLS SELECT policy
(small); client setAuth (small); **JWT refresh loop + reconnect handling
(the real work)**. Reuses the existing Supabase realtime architecture — no
backend fan-out/broker, no client rebuild (contrast option (c)).

## Optional follow-up
If live reactions are wanted back (the dead `room_reactions` subscription is
being removed), publish `room_reactions` to `supabase_realtime` and add the same
membership-scoped SELECT policy. Until then, reactions update on
load/refresh via REST.

## Step 2e (shipped)

Built on the RLS step 2 plan (`docs/security/rls-step2-plan.md` §2.4, §6.1),
which refined this design in two ways: the token has its own issuer, and the
policy is anchored on `app_auth`, not `auth.uid()` (which casts `sub` to uuid
and raises on `user_<google id>`).

### What shipped

| Piece | Where |
| --- | --- |
| Migration: `app_auth.realtime_uid()` (trusts `iss = sapling-realtime` only), SECURITY DEFINER `app_auth.is_room_member_realtime(room_id)`, policy `room_messages_select_member` (SELECT, TO authenticated: member via a `sapling-api` OR a `sapling-realtime` token), SELECT grant to authenticated only where RLS is already on | `backend/db/migrations/20261108210944_rls_room_messages_realtime.sql` |
| Minting: `mint_realtime(sub)` → `(token, exp)`; claims `iss=sapling-realtime, sub, role=authenticated, aud=authenticated, iat, exp=iat+3600`; same key and signer as the user-scoped client (`SUPABASE_JWT_SIGNING_KEY`: oct JWK → HS256, EC P-256 JWK → ES256) | `backend/db/user_jwt.py` |
| Endpoint: `GET /api/auth/realtime-token` → `{token, expires_at}`, `Cache-Control: private, no-store`. 401/403 without a live approved session; 404 while `realtime_rls` is off for the student; 503 when the signing key is unset or unusable (fail closed, no anon/service fallback) | `backend/routes/auth.py` |
| Flag `realtime_rls` (`off`/`on`, default off, client-visible; env kill switch `SAPLING_FLAG_REALTIME_RLS=off`) | `backend/services/feature_flags.py` |
| Client: the Social screen (not the per-room `RoomChat`) holds ONE shared, ref-counted token lifecycle (`acquireRealtimeAuth`/`useRealtimeAuth`), so room and tab switches neither revert to anon nor re-mint; only the last release reverts with `setAuth()`, and every `setAuth` runs through one owner-guarded chain so an old revert never lands after a newer token. Nothing joins until flags are loaded. With the flag on, `room:<id>` and `presence:<id>` join only on an applied token: refresh 5 min before `expires_at` (and at once when a sleeping tab wakes past that point); an expiry timer reports not-authed AT `expires_at` whatever the fetches are doing (channels drop to REST-only), and the next token re-joins them (the auth `epoch` bumps on every re-entry). A channel Realtime errors, times out or closes re-joins after a token refresh with 1 s..30 s backoff, then re-fetches the latest page. Transient fetch failures retry at 30 s doubling to 5 min; 404 (flag off server-side) / 503 (no signing key) stop retrying and fall back to the anon subscription for the page session (logged once). Flag off: no token request, no `setAuth`, the same `.subscribe()` as before | `frontend/src/lib/realtimeAuth.ts`, `frontend/src/components/screens/Social.tsx` |
| Tests | `backend/tests/test_realtime_token.py` (hermetic), `backend/tests/integration/test_rls_policies_db.py` + `test_rls_lockdown_db.py` (SQL, step-2e sections), `frontend/src/lib/realtimeAuth.test.tsx`, `frontend/src/components/screens/Social.realtime.test.ts`, `frontend/src/components/screens/Social.realtimeAuth.test.tsx` |

One token per student, not per room: the policy does the scoping, and
Realtime re-evaluates it for every change and subscriber
(`realtime.apply_rls` sets `role` to the token's `role` claim and
`request.jwt.claims` to its claims before running the row through RLS, which is
what `app_auth.realtime_uid()` reads). A kicked or departed member stops
receiving the room's changes at once. A token lifted out of the browser is no
user anywhere except that one SELECT policy (`app_auth.uid()` still trusts
`sapling-api` only), and it holds no write privilege.

### Why it is inert until switched on

The migration does NOT enable RLS on `room_messages` and does NOT revoke anon
SELECT. Where RLS is off (local, CI, staging) the policy is never evaluated and
the anon `postgres_changes` lane is unchanged. Production has had RLS on with
zero policies since June (live chat delivers nothing there today); the policy
admits only tokens nothing mints until `realtime_rls` (or `db_user_scope`)
leaves `off`.

### Enable sequence (manual, per environment)

1. **Signing key the project's Realtime trusts.** Local/CI: the CLI default
   secret as an oct JWK (`backend/.env.local.example`), which local Realtime
   already verifies (its tenant `jwt_secret` is that secret; the bundled
   Realtime verifies HS256 and ES256 and requires `exp` and `role`, not
   `iss`). Staging/prod: the step-2d key (an ES256 key generated, imported as
   a standby key and rotated in; Realtime verifies it via the project JWKS),
   or the legacy HS256 secret as an oct JWK if the project is still on legacy
   keys. Set `SUPABASE_JWT_SIGNING_KEY` on the backend. **Needs Andres** (a
   secret, and a dashboard key rotation).
2. **Flag on for a slice** (admins, then a rollout), watching for 503s on
   `/api/auth/realtime-token` and Realtime `CHANNEL_ERROR`s. Rollback: flag
   off (clients return to the anon path on the next flags refresh).
3. **Flag on for everyone** (stored default `on`, no `off` rules), then run
   the study-room E2E journey against that environment's configuration.
4. **Close the anon path** (one transaction, as the migration role):
   ```sql
   BEGIN;
   GRANT SELECT ON public.room_messages TO authenticated;
   ALTER TABLE public.room_messages ENABLE ROW LEVEL SECURITY;
   REVOKE SELECT ON public.room_messages FROM anon;
   COMMIT;
   ```
   Production already has RLS on and no anon SELECT, so only the GRANT can
   matter there (and the migration already made it). From here a client
   still on the anon key gets no live chat; REST reads (service_role) are
   unaffected. Rollback: `GRANT SELECT ... TO anon; ALTER TABLE ... DISABLE
   ROW LEVEL SECURITY;` (not on production).
5. **Pin it** in a new migration (the same three statements, idempotent) so
   local/CI replay the end state; drop `room_messages` from `EXEMPT` in
   `backend/tests/integration/test_rls_lockdown_db.py` and replace its
   anon-SELECT test; graduate the flag (remove the off path from
   `Social.tsx`).

### What the E2E pass must check

`frontend/e2e/study-room.spec.ts` (live chat across two contexts):

- **Flag off** (default): unchanged; the spec must pass as is.
- **Flag on**: `SAPLING_FLAG_REALTIME_RLS=on` plus the local
  `SUPABASE_JWT_SIGNING_KEY` (oct JWK of the CLI default secret, from
  `backend/.env.local.example`) in the backend env. The spec's wait for the
  `Subscribed to PostgreSQL` frame on `room:<id>` must still resolve (now
  after the token is applied), and A→B / B→A propagation must pass. With RLS
  still off locally this proves the token is accepted by local Realtime and
  the client wiring works.
- **Flag on + RLS on** (optional, proves the policy end to end): after
  migrate, run the step-4 statements against the local DB, then the spec. A
  third, non-member context must NOT receive the room's inserts (not in the
  spec today; the SQL half is pinned by `test_rls_policies_db.py`
  `chat_world`).
