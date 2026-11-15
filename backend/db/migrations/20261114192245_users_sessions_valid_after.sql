-- Server-side session revocation.
--
-- What this adds
-- --------------
-- public.users.sessions_valid_after: a session token whose `iat` (issued-at,
-- unix seconds) is earlier than this timestamp is refused by the auth guard
-- (services/auth_guard.py::get_session_user_id, read through its short-TTL
-- account cache). Sign-out (POST /api/auth/logout, called by the frontend
-- session BFF before it clears the cookie) sets it to now(), so a copied
-- `sapling_session` cookie stops working at once instead of living until its
-- `exp`. NULL (the default, and every existing row) means the account never
-- signed out: nothing is revoked.
--
-- Deploy order: apply BEFORE the backend that reads it. The guard selects the
-- column on every account read; without it every authenticated request would
-- answer 503.
--
-- Not encrypted: a timestamp, like last_sign_in_at.
--
-- Rollback:
--   ALTER TABLE public.users DROP COLUMN IF EXISTS sessions_valid_after;
-- (only after rolling back the backend that reads it).

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS sessions_valid_after TIMESTAMPTZ;

COMMENT ON COLUMN public.users.sessions_valid_after IS
    'Sessions issued (token iat) before this time are revoked; set to now() by sign-out. NULL: none revoked.';
