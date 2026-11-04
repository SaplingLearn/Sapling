-- Transactional + broadcast email over Resend (services/email_service.py).
--
-- Recipient ADDRESSES are never stored in these tables. Every row keys on
-- `recipient_hash` = HMAC-SHA256(lower(trim(email))) under a key derived from
-- SESSION_SECRET (email_service.recipient_hash), so a dump of these tables
-- names nobody, and the waitlist (plaintext by ADR 0026) and the encrypted
-- users.email can still be joined against them in Python.

-- One row per admin-composed broadcast. Counts are bumped by the background
-- sender as it goes, so the admin page can show progress.
CREATE TABLE IF NOT EXISTS email_broadcasts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject          TEXT NOT NULL,
    body             TEXT NOT NULL,
    audience         TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'sending'
                     CHECK (status IN ('sending', 'sent', 'failed')),
    recipient_count  INTEGER NOT NULL DEFAULT 0,
    sent_count       INTEGER NOT NULL DEFAULT 0,
    skipped_count    INTEGER NOT NULL DEFAULT 0,
    failed_count     INTEGER NOT NULL DEFAULT 0,
    created_by       TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ DEFAULT now(),
    sent_at          TIMESTAMPTZ
);

-- The send ledger. `dedupe_key` UNIQUE is the "never twice" guarantee: a send
-- claims its key with INSERT … ON CONFLICT DO NOTHING before it talks to the
-- provider, and a key that is already claimed is never sent again (e.g. an
-- allowlist revoke followed by a re-approve does not re-send "you're in").
CREATE TABLE IF NOT EXISTS email_sends (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind                 TEXT NOT NULL,
    dedupe_key           TEXT NOT NULL UNIQUE,
    recipient_hash       TEXT NOT NULL,
    status               TEXT NOT NULL
                         CHECK (status IN ('queued', 'sent', 'skipped', 'failed', 'suppressed')),
    provider_message_id  TEXT,
    error                TEXT,
    broadcast_id         UUID REFERENCES email_broadcasts(id) ON DELETE SET NULL,
    created_at           TIMESTAMPTZ DEFAULT now(),
    sent_at              TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS email_sends_broadcast_id_idx ON email_sends (broadcast_id);

-- Addresses that must never be mailed again, of any kind.
CREATE TABLE IF NOT EXISTS email_suppressions (
    recipient_hash  TEXT PRIMARY KEY,
    reason          TEXT NOT NULL CHECK (reason IN ('unsubscribe', 'bounce', 'complaint')),
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- The API is the only client; nothing reaches these through anon/authenticated.
ALTER TABLE email_broadcasts ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_sends ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_suppressions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON email_broadcasts, email_sends, email_suppressions FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON email_broadcasts, email_sends, email_suppressions TO service_role;

-- When the welcome email went out (routes/auth.py claims it with a conditional
-- `welcomed_at IS NULL` update on the first approved sign-in). Every account
-- that is ALREADY approved is backfilled, so deploying this never mails a
-- welcome to an existing student; pending accounts stay NULL and get one when
-- they first get in.
ALTER TABLE users ADD COLUMN IF NOT EXISTS welcomed_at TIMESTAMPTZ;

UPDATE users
   SET welcomed_at = coalesce(last_sign_in_at, created_at, now())
 WHERE is_approved
   AND welcomed_at IS NULL;
