-- Ops-alert unsubscribes: an admin can stop the operational alerts, and a
-- broadcast/newsletter unsubscribe does not.
--
-- What this adds
-- --------------
-- public.email_alert_suppressions: addresses (as recipient_hash, like every
-- email table) that must get no more OPERATIONAL alerts
-- (services/spend_alerts.py). Set by the unsubscribe link and
-- List-Unsubscribe header those alerts carry
-- (/api/email/unsubscribe?scope=ops_alert); an operational send checks only
-- this table. Every other kind checks only public.email_suppressions, which
-- this migration leaves exactly as it is (services/email_service.py maps a
-- suppression scope to its table: 'all' -> email_suppressions, 'ops_alert'
-- -> email_alert_suppressions).
--
-- Why a table of its own and not a scope column on email_suppressions: the
-- backend still serving while a deploy migrates upserts email_suppressions
-- with on_conflict=recipient_hash, so changing that table's key would 500
-- every unsubscribe until the new backend is up. Nothing existing reads or
-- writes this table, so it can be applied at any time before the backend.
--
-- Columns mirror email_suppressions (20261022063145_email.sql).
-- Not encrypted: recipient_hash is already a keyed hash, reason is an enum.
--
-- Rollback (after rolling back the backend):
--   DROP TABLE IF EXISTS public.email_alert_suppressions;

CREATE TABLE IF NOT EXISTS public.email_alert_suppressions (
    recipient_hash  TEXT PRIMARY KEY,
    reason          TEXT NOT NULL CHECK (reason IN ('unsubscribe', 'bounce', 'complaint')),
    created_at      TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE public.email_alert_suppressions IS
    'Addresses (recipient_hash) that get no more operational (admin) alerts; email_suppressions covers every other kind.';

-- Service-only, like email_suppressions: the API is the only client.
ALTER TABLE public.email_alert_suppressions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.email_alert_suppressions FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.email_alert_suppressions TO service_role;
