-- newsletter_emails.approved_at: timestamp an admin approved an email for the
-- newsletter allowlist (NULL = pending). The admin allowlist endpoints
-- (POST /api/admin/allowlist/approve and /revoke in routes/admin.py) read and
-- write this column.
--
-- Drift fix: prod had this column added out-of-band (it exists there), but it was
-- never captured as a migration, so environments built purely from migrations
-- (staging, CI, fresh DBs) were missing it — which 500s the allowlist endpoints.
-- IF NOT EXISTS makes this a safe no-op where the column already exists (prod).
ALTER TABLE newsletter_emails
  ADD COLUMN IF NOT EXISTS approved_at timestamptz;

-- Manual run notes:
-- 1. Apply on staging first (python -m db.migrate with the staging SUPABASE_DB_URL).
-- 2. On prod the column already exists, so this only records the migration.
-- 3. NULL approved_at = not yet approved; /allowlist/approve stamps it, /revoke nulls it.
