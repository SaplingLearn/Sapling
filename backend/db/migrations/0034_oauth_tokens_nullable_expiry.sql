-- 0034: allow oauth_tokens.expires_at to be NULL.
--
-- Google's token endpoint occasionally omits expires_in; the code (both the
-- sign-in callback in routes/auth.py and the calendar connect/refresh paths
-- in routes/calendar.py, #407) models that as expires_at = NULL. The column
-- has carried NOT NULL since the 0001 baseline (0024 only retyped it to
-- TIMESTAMPTZ), so those writes would trip a constraint violation and 500 —
-- and in the refresh path lose the freshly-minted access_token in the same
-- PATCH. Readers already treat a missing/NULL expiry as "no known expiry"
-- (routes/calendar.py:69 guards with .get()).

ALTER TABLE oauth_tokens ALTER COLUMN expires_at DROP NOT NULL;
