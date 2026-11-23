-- Calendar visibility is separate from the shared Google authorization.
ALTER TABLE oauth_tokens
    ADD COLUMN IF NOT EXISTS calendar_events_enabled BOOLEAN NOT NULL DEFAULT true;

NOTIFY pgrst, 'reload schema';
