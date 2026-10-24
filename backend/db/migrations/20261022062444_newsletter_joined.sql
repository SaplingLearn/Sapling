-- Waitlist → joined tracking for Admin → Allowlist.
--
-- users.email is AES-GCM encrypted with a per-call nonce, so a waitlist row
-- cannot be matched to its account by a query. The Google sign-in callback has
-- the plaintext email in hand and stamps these when an approved account signs
-- in for the first time (routes/auth.py::_mark_waitlist_joined).
ALTER TABLE newsletter_emails
    ADD COLUMN IF NOT EXISTS joined_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS joined_at TIMESTAMPTZ;
