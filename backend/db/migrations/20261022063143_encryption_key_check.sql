-- One-row key canary: a known plaintext sealed under this environment's
-- ENCRYPTION_KEY. services/encryption_canary.py checks it at boot, so a backend
-- holding a DIFFERENT key (a laptop pointed at prod's SUPABASE_URL, a staging
-- key pasted into a prod deploy) refuses to start instead of writing rows the
-- real environment can never decrypt. The first backend to boot seeds it.
-- Rotating ENCRYPTION_KEY means re-encrypting every 🔒 column AND deleting this
-- row so the new key re-seeds it.
CREATE TABLE IF NOT EXISTS encryption_key_check (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    canary TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Backend-only, like every other table the API owns.
ALTER TABLE encryption_key_check ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON encryption_key_check FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON encryption_key_check TO service_role;
