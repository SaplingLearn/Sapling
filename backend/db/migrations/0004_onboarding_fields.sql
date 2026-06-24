-- Migration: Add onboarding profile columns to users table
-- Safe to run multiple times (idempotent)

ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS year TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS majors TEXT[] DEFAULT '{}';
ALTER TABLE users ADD COLUMN IF NOT EXISTS minors TEXT[] DEFAULT '{}';
ALTER TABLE users ADD COLUMN IF NOT EXISTS learning_style TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN NOT NULL DEFAULT false;
