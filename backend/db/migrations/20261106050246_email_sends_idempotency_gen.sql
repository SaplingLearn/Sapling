-- #763 review follow-up: which Resend Idempotency-Key the next attempt at a
-- dedupe key uses (email_service._idempotency_key).
--
-- An attempt whose outcome is UNKNOWN (transport error/timeout, a crash before
-- the status write, a 409 for a changed payload) leaves the generation alone,
-- so a re-claim reuses the key and Resend replays rather than re-delivers.
-- A DEFINITIVE provider failure (any other non-2xx response) bumps it, so the
-- next attempt is a fresh request and not a replay of the cached failure for
-- the rest of Resend's 24 h key window.
ALTER TABLE email_sends ADD COLUMN IF NOT EXISTS idempotency_gen INTEGER NOT NULL DEFAULT 0;
