-- Open access (docs/design/open-access-gate.md): the waitlist requirement as
-- the `open_access` feature flag (services/feature_flags.py).
--
-- `users.open_access_at` marks an account that came in through the open gate
-- (`open_access` on) without an admin approving it: `is_approved` stays false,
-- and access is COMPUTED as
--     is_approved OR (open_access is on AND open_access_at IS NOT NULL)
-- (services/open_access.py), so flipping the flag writes nothing and closing
-- the gate puts these accounts back on the waitlist at once. It is what tells
-- an open-access entrant apart from an account an admin removed (both have
-- is_approved = false); Remove access and Allowlist revoke clear it.
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS open_access_at TIMESTAMPTZ;

-- The flag's config row, OFF: the waitlist stays required until an admin
-- opens it at /api/admin/flags. SAPLING_FLAG_OPEN_ACCESS=off is the kill
-- switch (it also replaces the old ALLOWED_EMAIL_DOMAINS=invalid.invalid
-- "refuse every new sign-in" lever: with the gate closed, no one new gets in
-- without an approval).
INSERT INTO feature_flags (key, default_variant) VALUES ('open_access', 'off')
ON CONFLICT (key) DO NOTHING;
