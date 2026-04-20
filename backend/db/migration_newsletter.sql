-- Migration: newsletter_emails table
-- Stores emails submitted via the newsletter/beta signup modal.

CREATE TABLE IF NOT EXISTS newsletter_emails (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email      text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Index for fast lookup by email
CREATE INDEX IF NOT EXISTS newsletter_emails_email_idx ON newsletter_emails (email);
