-- backend/db/migrations/0032_add_gradescope_credentials.sql
--
-- Stores per-user Gradescope auth material, encrypted at rest via
-- services/encryption.py (encrypt_if_present / decrypt_if_present).
-- auth_mode 'cookies' matches frontend's GradescopeAuthMode type
-- (frontend/src/lib/api.ts).

CREATE TABLE IF NOT EXISTS gradescope_credentials (
    user_id                      UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    auth_mode                    TEXT NOT NULL CHECK (auth_mode IN ('password', 'cookies')),
    encrypted_email              TEXT,
    encrypted_password           TEXT,
    encrypted_gradescope_session TEXT,
    encrypted_signed_token       TEXT,
    last_synced_at               TIMESTAMPTZ,
    last_error                   TEXT,
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Adjust `users(id)` above if your users table has a different name/PK.