-- The daily leftover-credential sweep (backend/services/account_purge_sweeper.py
-- ::sweep_leftover_credentials) is ON by default: it finishes the credential
-- removal a failed account delete left behind, which was due at the delete.
-- It deletes OAuth/Gradescope rows and revokes tokens at Google every pass,
-- so it has a switch of its own: admins switch it off at /api/admin/flags;
-- SAPLING_FLAG_CREDENTIAL_SWEEP=off overrides it from the environment.
INSERT INTO feature_flags (key, default_variant) VALUES ('credential_sweep', 'on')
ON CONFLICT (key) DO NOTHING;
