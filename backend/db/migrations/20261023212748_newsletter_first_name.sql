-- First name on a waitlist entry, for greeting them by name in the "you're in"
-- email. Only known when the entry came from an unapproved Google sign-in
-- (/pending → Join the waitlist); the landing form collects an email alone.
--
-- 🔒 Column-encrypted (services/encryption.py, ENCRYPTION_KEY) like every other
-- name in the schema: it is only ever read back by id, never queried by value.
ALTER TABLE newsletter_emails
    ADD COLUMN IF NOT EXISTS first_name TEXT;
