-- Migration: Newsletter email signups
-- Run once in Supabase SQL editor

CREATE TABLE IF NOT EXISTS newsletter_emails (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    email       text        NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS newsletter_emails_email_idx ON newsletter_emails (email);
