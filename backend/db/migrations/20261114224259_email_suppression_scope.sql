-- Scoped email suppressions: an admin can stop the ops alerts, and a
-- broadcast/newsletter unsubscribe does not.
--
-- What this adds
-- --------------
-- public.email_suppressions.scope: what a suppression stops
-- (services/email_service.py::suppression_scope).
--   'all'       every kind of email but the operational (admin) alerts. Every
--               existing row (unsubscribes so far) is this, the default.
--   'ops_alert' the operational alerts only (services/spend_alerts.py), set
--               by the unsubscribe link and List-Unsubscribe header those
--               alerts carry (/api/email/unsubscribe?scope=ops_alert).
-- An operational send checks only the 'ops_alert' row; every other kind
-- checks only 'all'. One address can hold both, so the key becomes
-- (recipient_hash, scope).
--
-- Deploy order: apply BEFORE the backend that writes `scope`: its upsert
-- names `on_conflict=recipient_hash,scope`, which needs this primary key.
--
-- Not encrypted: recipient_hash is already a keyed hash, scope is an enum.
--
-- Rollback (after rolling back the backend):
--   DELETE FROM public.email_suppressions WHERE scope <> 'all';
--   ALTER TABLE public.email_suppressions DROP CONSTRAINT email_suppressions_pkey;
--   ALTER TABLE public.email_suppressions ADD CONSTRAINT email_suppressions_pkey PRIMARY KEY (recipient_hash);
--   ALTER TABLE public.email_suppressions DROP COLUMN scope;

ALTER TABLE public.email_suppressions
    ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'all';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'email_suppressions_scope_check'
           AND conrelid = 'public.email_suppressions'::regclass
    ) THEN
        ALTER TABLE public.email_suppressions
            ADD CONSTRAINT email_suppressions_scope_check CHECK (scope IN ('all', 'ops_alert'));
    END IF;
END $$;

ALTER TABLE public.email_suppressions DROP CONSTRAINT IF EXISTS email_suppressions_pkey;
ALTER TABLE public.email_suppressions
    ADD CONSTRAINT email_suppressions_pkey PRIMARY KEY (recipient_hash, scope);

COMMENT ON COLUMN public.email_suppressions.scope IS
    'What the suppression stops: all = every kind but the operational (admin) alerts; ops_alert = those alerts only.';

-- Service-only, as before (the API is the only client).
ALTER TABLE public.email_suppressions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.email_suppressions FROM anon, authenticated;
