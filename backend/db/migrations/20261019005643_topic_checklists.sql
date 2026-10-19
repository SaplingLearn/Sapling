-- Apply before deploying the Topic Checklist API. Contents contain private
-- material-derived text and are AES-GCM encrypted by services/encryption.py.
CREATE TABLE IF NOT EXISTS topic_checklists (
    enrollment_id TEXT PRIMARY KEY REFERENCES enrollments(id) ON DELETE CASCADE,
    input_hash TEXT NOT NULL,
    content TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Name-derived keys keep checkmarks stable when a refreshed outline reorders
-- topics. Removing an enrollment removes both its outline and its progress.
CREATE TABLE IF NOT EXISTS topic_checklist_progress (
    enrollment_id TEXT NOT NULL REFERENCES topic_checklists(enrollment_id) ON DELETE CASCADE,
    topic_key TEXT NOT NULL,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (enrollment_id, topic_key)
);

-- The API authenticates Sapling sessions; clients never access these directly.
ALTER TABLE topic_checklists ENABLE ROW LEVEL SECURITY;
ALTER TABLE topic_checklist_progress ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON topic_checklists, topic_checklist_progress FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON topic_checklists, topic_checklist_progress TO service_role;
