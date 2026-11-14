-- legal_acceptances: which Terms of Service / Privacy Policy versions a
-- student accepted, and when.
--
-- Why
-- ---
-- Onboarding's last screen asks the student to accept the Terms and the Privacy
-- Policy, but nothing recorded it: the only trace was `users.onboarding_completed`,
-- which says neither which versions were shown nor when. POST
-- /api/onboarding/profile now sends the versions the student accepted
-- (`accepted_terms_version`, `accepted_privacy_version`), refuses anything but
-- the current ones (422 `legal_outdated`; services/legal.py holds them, pinned to
-- frontend/src/lib/legal/versions.ts by tests/test_legal_versions.py), and writes
-- one row per document here BEFORE it marks the account onboarded.
--
-- What this adds
-- --------------
-- public.legal_acceptances: one row per (user, document, version).
--   document    'terms' | 'privacy'
--   version     the document's "Last updated" date as the app knows it
--               (YYYY-MM-DD today; free text so a later scheme needs no DDL)
--   accepted_at the database clock at the first acceptance
-- Append-only: the backend only ever inserts, with ON CONFLICT DO NOTHING
-- (services/legal.py::record_acceptances), so a retried or concurrent submit
-- keeps the first row and its time. A new version of a document is a new row.
-- No 🔒 column: versions and times are not personal content.
--
-- Access: service-only (RLS bucket E, docs/security/rls-step2-plan.md): RLS
-- on, no policies, nothing granted to anon/authenticated. The backend writes it
-- under service_scope, like `users.onboarding_completed`.
--
-- Account tools: the admin wipe KEEPS these rows (account state, like the
-- profile, settings and OAuth tokens) and the cross-environment copy never
-- moves them (consent is given per environment, like the consent choices in
-- user_settings). A hard-deleted `users` row takes its rows with it (CASCADE);
-- the app's own account deletion is a soft delete and keeps them.
--
-- Idempotent (IF NOT EXISTS, guarded DO block), additive, touches no existing
-- data.
--
-- Reverse (by hand, as the migration role). Deploy code that no longer writes
-- the table first, or every onboarding submit fails:
--   DROP TABLE IF EXISTS public.legal_acceptances;

CREATE TABLE IF NOT EXISTS public.legal_acceptances (
    user_id     TEXT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    document    TEXT NOT NULL,
    version     TEXT NOT NULL,
    accepted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT legal_acceptances_pkey PRIMARY KEY (user_id, document, version),
    CONSTRAINT legal_acceptances_document_check CHECK (document IN ('terms', 'privacy')),
    CONSTRAINT legal_acceptances_version_check CHECK (version <> '')
);

COMMENT ON TABLE public.legal_acceptances IS
    'Terms / Privacy Policy versions each student accepted (onboarding), append-only. Service-only.';

-- ── access: service-only ────────────────────────────────────────────────────

ALTER TABLE public.legal_acceptances ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.legal_acceptances FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON TABLE public.legal_acceptances TO service_role;
    END IF;
END $$;
