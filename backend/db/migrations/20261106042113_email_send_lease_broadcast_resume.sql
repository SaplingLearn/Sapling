-- Email state machines (#763): a lease on `queued` sends, and resumable,
-- honestly-reported broadcasts.

-- `email_sends.claimed_at`: when the current attempt claimed the key. A row
-- that has sat `queued` past email_service.STALE_QUEUED_AFTER (the process
-- died between the claim and the status write, or the status write itself
-- failed) is re-claimable instead of reading "duplicate" forever. Existing
-- rows take their creation time, so a `queued` row stranded before this
-- migration is already stale and recovers on its next send.
ALTER TABLE email_sends ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;
UPDATE email_sends SET claimed_at = coalesce(created_at, now()) WHERE claimed_at IS NULL;
ALTER TABLE email_sends ALTER COLUMN claimed_at SET DEFAULT now();

-- `email_broadcasts.heartbeat_at`: bumped by every progress write of the
-- background run. A `sending` broadcast whose heartbeat is older than
-- admin_email.STALE_SENDING_AFTER has no live run (a deploy or crash killed
-- it) and can be resumed from Admin → Email.
ALTER TABLE email_broadcasts ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;
UPDATE email_broadcasts SET heartbeat_at = coalesce(sent_at, created_at, now()) WHERE heartbeat_at IS NULL;
ALTER TABLE email_broadcasts ALTER COLUMN heartbeat_at SET DEFAULT now();

-- Honest outcomes: `partial` = some mail went out and some failed (or the run
-- stopped part-way), `skipped` = nothing was sent and nothing failed (no
-- RESEND_API_KEY, everyone suppressed/opted out, or an empty audience).
ALTER TABLE email_broadcasts DROP CONSTRAINT IF EXISTS email_broadcasts_status_check;
ALTER TABLE email_broadcasts ADD CONSTRAINT email_broadcasts_status_check
    CHECK (status IN ('sending', 'sent', 'partial', 'skipped', 'failed'));
