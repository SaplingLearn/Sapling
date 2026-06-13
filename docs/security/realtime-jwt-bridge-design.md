# Realtime option (a) — JWT-mint bridge (design, #231)

**Status: DESIGN for review. Build AFTER the RLS lockdown lands** — this is the
piece that restores `room_messages` realtime under RLS. Not built yet.

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
