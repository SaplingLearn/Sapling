-- Implicit-state-machine audit (umbrella PR #772, issues #756-#771).
--
-- ONE migration for the whole batch. It was written as eleven per-workstream
-- files; none had reached staging or production, so they were combined
-- before merge. Sections run in their original order, and each keeps its own
-- rationale. claim_documents_for_indexing is defined ONCE, in its final form
-- (the "#758 indexing: claim + reaper" section).
--
-- Data-changing statements (review before applying to a populated database):
--   * #764: deletes rooms with no members; moves ownership of a room whose
--     owner has left to its earliest remaining member.
--   * #760: rows both completed and abandoned keep completed_at when scored,
--     otherwise become abandoned (then the CHECK is validated).
--   * #771: drops users.current_room_id and courses.deleted_at (raises instead
--     of dropping if any course has deleted_at set).
--   * #766: rows with mastery_tier 'subject_root' (none expected) -> 'unexplored'.
--
-- Apply BEFORE deploying the #772 code.

-- ==========================================================================
-- #763 email: send lease + broadcast resume
-- (was 20261106042113_email_send_lease_broadcast_resume.sql)
-- ==========================================================================

-- Email state machines (#763): a lease on `queued` sends, and resumable,
-- honestly-reported broadcasts.

-- `email_sends.claimed_at`: when the current attempt claimed the key. A row
-- that has sat `queued` past email_service.STALE_QUEUED_AFTER (the process
-- died between the claim and the status write, or the status write itself
-- failed) is re-claimable instead of reading "duplicate" forever. Existing
-- rows take their creation time, so a `queued` row stranded before this
-- migration is already stale and recovers on its next send.
ALTER TABLE email_sends ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;
UPDATE email_sends SET claimed_at = coalesce(created_at, now()) WHERE claimed_at IS NULL;
ALTER TABLE email_sends ALTER COLUMN claimed_at SET DEFAULT now();

-- `email_broadcasts.heartbeat_at`: bumped by every progress write of the
-- background run. A `sending` broadcast whose heartbeat is older than
-- admin_email.STALE_SENDING_AFTER has no live run (a deploy or crash killed
-- it) and can be resumed from Admin → Email.
ALTER TABLE email_broadcasts ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;
UPDATE email_broadcasts SET heartbeat_at = coalesce(sent_at, created_at, now()) WHERE heartbeat_at IS NULL;
ALTER TABLE email_broadcasts ALTER COLUMN heartbeat_at SET DEFAULT now();

-- Honest outcomes: `partial` = some mail went out and some failed (or the run
-- stopped part-way), `skipped` = nothing was sent and nothing failed (no
-- RESEND_API_KEY, everyone suppressed/opted out, or an empty audience).
ALTER TABLE email_broadcasts DROP CONSTRAINT IF EXISTS email_broadcasts_status_check;
ALTER TABLE email_broadcasts ADD CONSTRAINT email_broadcasts_status_check
    CHECK (status IN ('sending', 'sent', 'partial', 'skipped', 'failed'));

-- ==========================================================================
-- #764 social: room bans + room delete cascade
-- (was 20261106042133_room_bans_and_room_cascade.sql)
-- ==========================================================================

-- #764 (state-machine audit, workstream G): room lifecycle.
--
-- 1. room_bans — a kick is a ban. Before this, kick_member only deleted the
--    room_members row, so the kicked student could rejoin at once with the
--    same invite code (or the public-join button). The kick now records a ban
--    row and both join paths (POST /rooms/join, POST /public-rooms/{id}/join)
--    refuse a banned user. Rows die with the room or the user.
--
-- 2. Rooms are now DELETED when their last member leaves (routes/social.py::
--    leave_room), which is what kills the invite code. The 0001 children of
--    `rooms` were created without ON DELETE, so a room with any message,
--    activity row, cached summary or member could not be deleted at all. They
--    become ON DELETE CASCADE so one `DELETE FROM rooms` is the whole,
--    atomic teardown. room_reactions already cascades off room_messages, and
--    users.current_room_id is already ON DELETE SET NULL (0024).
--    room_messages.reply_to_id becomes ON DELETE SET NULL: send_room_message
--    never checked that the replied-to message lives in the same room, so a
--    reply in ANOTHER room could otherwise pin a deleted room's message.
--
-- The FKs are found by (table, column, referenced table) rather than by their
-- default `<table>_<column>_fkey` names, because environments that predate the
-- baseline got these tables through dashboard DDL and the names are not
-- guaranteed. Idempotent: re-running drops and re-adds the same constraint.

CREATE TABLE IF NOT EXISTS room_bans (
    room_id    TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    banned_by  TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (room_id, user_id)
);

-- The API is the only client; nothing reaches this through anon/authenticated.
ALTER TABLE room_bans ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON room_bans FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON room_bans TO service_role;

DO $$
DECLARE
    spec RECORD;
    con  RECORD;
BEGIN
    FOR spec IN
        SELECT * FROM (VALUES
            ('room_members',   'room_id',     'rooms',         'id', 'CASCADE'),
            ('room_activity',  'room_id',     'rooms',         'id', 'CASCADE'),
            ('room_messages',  'room_id',     'rooms',         'id', 'CASCADE'),
            ('room_summaries', 'room_id',     'rooms',         'id', 'CASCADE'),
            ('room_messages',  'reply_to_id', 'room_messages', 'id', 'SET NULL')
        ) AS t(tbl, col, ref_tbl, ref_col, on_delete)
    LOOP
        IF to_regclass('public.' || spec.tbl) IS NULL THEN
            CONTINUE;
        END IF;

        FOR con IN
            SELECT c.conname
              FROM pg_constraint c
              JOIN pg_attribute a
                ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
             WHERE c.contype = 'f'
               AND c.conrelid = ('public.' || spec.tbl)::regclass
               AND c.confrelid = ('public.' || spec.ref_tbl)::regclass
               AND array_length(c.conkey, 1) = 1
               AND a.attname = spec.col
        LOOP
            EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT %I', spec.tbl, con.conname);
        END LOOP;

        EXECUTE format(
            'ALTER TABLE public.%I ADD CONSTRAINT %I FOREIGN KEY (%I) REFERENCES public.%I(%I) ON DELETE %s',
            spec.tbl, spec.tbl || '_' || spec.col || '_fkey', spec.col,
            spec.ref_tbl, spec.ref_col, spec.on_delete
        );
    END LOOP;
END $$;

-- 3. Backfill: bring rooms broken before #764 under the invariants the routes
--    now keep. A room whose owner is no longer a member passes to its
--    earliest remaining member; a room with no members at all is deleted (its
--    invite code was still live, and no endpoint lets anyone read it).
UPDATE rooms r
   SET owner_id = (
           SELECT m.user_id FROM room_members m
            WHERE m.room_id = r.id
            ORDER BY m.joined_at ASC NULLS LAST, m.user_id ASC
            LIMIT 1
       ),
       updated_at = now()
 WHERE EXISTS (SELECT 1 FROM room_members m WHERE m.room_id = r.id)
   AND NOT EXISTS (
           SELECT 1 FROM room_members m
            WHERE m.room_id = r.id AND m.user_id = r.owner_id
       );

DELETE FROM rooms r
 WHERE NOT EXISTS (SELECT 1 FROM room_members m WHERE m.room_id = r.id);

-- ==========================================================================
-- #770 gradescope: stored sync outcome
-- (was 20261106042134_gradescope_sync_state.sql)
-- ==========================================================================

-- #770 (state-machine audit L2): persist the Gradescope connection/sync outcome.
--
-- Before this, "connected" meant only "a gradescope_credentials row exists", and
-- the only recorded outcome was last_synced_at on success. An expired cookie
-- session kept reading as connected, and a failed sync left no trace.
--
--   needs_reauth     set when Gradescope rejects the STORED credentials (a sync
--                    or course listing got an auth failure); cleared by a fresh
--                    credential save or any later successful login. The status
--                    endpoint reports state='needs_reauth' while it is set.
--   last_attempt_at  when the last sync attempt finished (success or failure).
--   last_sync_error  stable machine code for the last sync attempt's failure,
--                    NULL when it succeeded. Codes only, never upstream text, so
--                    nothing user- or Gradescope-supplied lands in this column.
--
-- Additive and idempotent (IF NOT EXISTS / guarded constraint), so a replay from
-- empty and a re-run are both clean.

ALTER TABLE gradescope_credentials
    ADD COLUMN IF NOT EXISTS needs_reauth    BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_sync_error TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'gradescope_credentials_last_sync_error_chk'
  ) THEN
    ALTER TABLE gradescope_credentials
      ADD CONSTRAINT gradescope_credentials_last_sync_error_chk CHECK (
        last_sync_error IS NULL
        OR last_sync_error IN ('auth_failed', 'fetch_failed', 'write_failed', 'partial_write')
      );
  END IF;
END $$;

-- ==========================================================================
-- #758 RAG: chunk source ledger + deleted-document retrieval guard
-- (was 20261106042249_course_chunk_sources.sql)
-- ==========================================================================

-- #758: a deleted document leaves the RAG corpus.
--
-- `DELETE /api/documents/doc/{id}` only stamped `documents.deleted_at`, and
-- `match_course_chunks` never looks at `documents` at all — so a deleted upload,
-- private ones included, kept grounding the uploader's and (for shared rows)
-- every classmate's tutor and quizzes. Nothing could even say which chunks a
-- document had produced: chunk ids are content-addressed per course, so a row
-- deduped across uploads carries only its LAST writer in `course_chunks.doc_id`.
--
-- Two objects close it:
--   1. `course_chunk_sources`, the chunk <-> document ledger. It is what the
--      delete path (services/chunk_visibility.py::withdraw_document_chunks)
--      reads to find a document's chunks, and what tells it whether another
--      live document still produces the same text.
--   2. `match_course_chunks`, replaced with the same signature, now refuses a
--      chunk whose every recorded source document is deleted. Defence in depth:
--      the delete path withdraws the rows, and this keeps a withdrawal that
--      failed half-way (or a document deleted mid-index) out of retrieval.
--
-- Safe in either deploy order. Code ahead of this migration: writing a source
-- row 404s and is swallowed (best-effort, logged), the delete path finds its
-- candidates through `course_chunks.doc_id`, and retrieval is today's.
-- Migration ahead of code: nothing writes sources yet, the seed below covers
-- every existing row, and retrieval only gets stricter.

-- ── 1. the ledger ──────────────────────────────────────────────────────────
--
-- No foreign key to documents, ON PURPOSE. Documents are soft-deleted, so the
-- rows must outlive the deletion for (2) to see it; and should a document ever
-- be hard-deleted, an FK cascade would erase the only evidence that the chunk
-- came from it, turning it into an unsourced row (which retrieval serves, like
-- a catalog row). A source naming a document that no longer exists counts as
-- dead, which is the safe reading. Only services/document_indexing.py writes
-- here, and only for a real `documents` row.
--
-- The FK to course_chunks DOES cascade: when a chunk is withdrawn its sources
-- go with it.
CREATE TABLE IF NOT EXISTS course_chunk_sources (
    chunk_id   TEXT NOT NULL REFERENCES course_chunks(id) ON DELETE CASCADE,
    doc_id     TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chunk_id, doc_id)
);

-- The delete path reads one document's chunks; the PK covers (chunk_id, …).
CREATE INDEX IF NOT EXISTS idx_course_chunk_sources_doc
    ON course_chunk_sources (doc_id);

-- Seed from what the table already knows: the last writer of each document
-- row. Soft-deleted documents included — that is what takes chunks of
-- documents deleted BEFORE this migration out of retrieval the moment it runs.
-- Joined to documents so that a `doc_id` naming no document (a seeded fixture,
-- e.g. scripts/seed_quiz_fixture.py) stays unsourced rather than being read as
-- "every source is gone". Under-records co-uploaders of a deduped row, exactly
-- like the contributor seed in 20260920072705; the effect is a chunk withheld
-- when its last writer deletes while another live document still has the text
-- — the safe direction. scripts/backfill_course_chunk_sources.py re-derives the
-- full set from each live document's own text.
INSERT INTO course_chunk_sources (chunk_id, doc_id)
SELECT c.id, c.doc_id
  FROM course_chunks c
  JOIN documents d ON d.id = c.doc_id
 WHERE c.category IS DISTINCT FROM 'catalog'
ON CONFLICT DO NOTHING;

-- Backend-only, like every RAG table: the API is the one client.
ALTER TABLE course_chunk_sources ENABLE ROW LEVEL SECURITY;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON course_chunk_sources FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON course_chunk_sources TO service_role;
    END IF;
END $$;

-- ── 2. the retrieval RPC ───────────────────────────────────────────────────
--
-- CREATE OR REPLACE with the IDENTICAL signature, defaults and result columns
-- as 20260920072705: a changed signature would leave the old function as a
-- live overload (the shape #629 had to DROP to close), and PostgREST resolves
-- by argument names, so every caller keeps resolving to this one.
CREATE OR REPLACE FUNCTION match_course_chunks(
    query_embedding  VECTOR(768),
    match_count      INTEGER DEFAULT 5,
    filter_course_id TEXT DEFAULT NULL,
    filter_user_id   TEXT DEFAULT NULL
)
RETURNS TABLE (
    id         TEXT,
    course_id  TEXT,
    chunk_text TEXT,
    category   TEXT,
    similarity FLOAT
)
LANGUAGE sql STABLE
AS $$
    SELECT
        c.id,
        c.course_id,
        c.chunk_text,
        c.category,
        1 - (c.embedding <=> query_embedding) AS similarity
    FROM course_chunks c
    WHERE c.embedding IS NOT NULL
      AND (filter_course_id IS NULL OR c.course_id = filter_course_id)
      -- Unchanged from 20260920072705: NULL reader = shared rows only.
      AND (
        c.visibility = 'shared'
        OR (
          filter_user_id IS NOT NULL
          AND (
            c.uploader_id = filter_user_id
            OR EXISTS (
              SELECT 1 FROM course_chunk_contributors k
               WHERE k.chunk_id = c.id AND k.user_id = filter_user_id
            )
          )
        )
      )
      -- #758: a chunk with recorded sources is served only while at least one
      -- of them is a live document. A row with NO source (catalog text, a
      -- fixture) is unaffected.
      AND (
        NOT EXISTS (
          SELECT 1 FROM course_chunk_sources s WHERE s.chunk_id = c.id
        )
        OR EXISTS (
          SELECT 1
            FROM course_chunk_sources s
            JOIN documents d ON d.id = s.doc_id
           WHERE s.chunk_id = c.id
             AND d.deleted_at IS NULL
        )
      )
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
$$;

-- ==========================================================================
-- #760 quiz: completed XOR abandoned
-- (was 20261106042651_quiz_attempts_completed_xor_abandoned.sql)
-- ==========================================================================

-- #760 (state-machine audit, workstream D): an attempt is never BOTH
-- completed and abandoned.
--
-- Status is derived from the two stamps (completed_at → completed,
-- abandoned_at → abandoned, else in_progress — 20260813013547), so a row
-- carrying both is a state the lifecycle has no name for; the derived status
-- silently picks "completed". Every writer now claims conditionally on the
-- OTHER stamp being NULL (submit's claim since #537 G4's review, the abandon
-- route, the lazy sweep), so no current code path can produce one — this
-- makes the database say so too, for whatever writer comes next.
--
-- Existing rows. Before submit's claim also filtered on abandoned_at IS NULL,
-- a submit racing a Discard (or the sweep) in another tab could win both
-- claims, so a pre-existing violator is possible. Three steps, in one
-- transaction (db/migrate.py wraps each file in one):
--   1. ADD ... NOT VALID — enforced for every new write from here on, without
--      checking the old rows yet.
--   2. Repair the old rows. A row with a SCORE was really submitted (score,
--      mastery and XP were all paid out after the claim), so the abandon stamp
--      is the one that lost: clear it. A row with NO score never finished
--      grading (the completed-but-scoreless strand #760 also fixes), so it was
--      never a completed quiz — no XP is paid before the score lands — and it
--      reads as what the student did: abandoned. Clear completed_at.
--   3. VALIDATE — now cannot fail, and proves step 2 left nothing behind.
--
-- Idempotent: the duplicate_object guard skips step 1 on a re-run, step 2
-- matches no rows once applied, and VALIDATE on a validated constraint is a
-- no-op.
DO $$
BEGIN
    ALTER TABLE quiz_attempts
        ADD CONSTRAINT quiz_attempts_not_completed_and_abandoned
        CHECK (completed_at IS NULL OR abandoned_at IS NULL) NOT VALID;
EXCEPTION
    WHEN duplicate_object THEN NULL;  -- already present; nothing to do
END $$;

UPDATE quiz_attempts
   SET abandoned_at = NULL
 WHERE completed_at IS NOT NULL
   AND abandoned_at IS NOT NULL
   AND score IS NOT NULL;

UPDATE quiz_attempts
   SET completed_at = NULL
 WHERE completed_at IS NOT NULL
   AND abandoned_at IS NOT NULL
   AND score IS NULL;

ALTER TABLE quiz_attempts
    VALIDATE CONSTRAINT quiz_attempts_not_completed_and_abandoned;

-- ==========================================================================
-- #760 canopy_metrics: scored completions only
-- (was 20261106042716_canopy_quizzes_completed_scored.sql)
-- ==========================================================================

-- #760 (state-machine audit, workstream D): canopy `quizzes_completed`
-- counts SCORED attempts only.
--
-- Submit stamps completed_at with its atomic claim BEFORE grading, so until
-- #760 a submit that failed after the claim left a row completed-but-scoreless
-- — and canopy_metrics() counted it as a completed quiz. #760 makes the score
-- always land (or releases the claim), but rows stranded before it remain, and
-- Canopy keeps every reading forever (20260921055024's header), so the count
-- must not depend on that never happening. A persisted score is the evidence a
-- quiz was really finished — the same signal achievement_service's
-- quizzes_completed stat and agents/tools/quiz_history.py treat as completion.
--
-- The ONLY change from 20260921055024 is the `AND score IS NOT NULL` on the
-- quizzes_completed branch; the key list, windows and the rest of the body are
-- copied verbatim, so the contract (keys, nesting, integer types) is unchanged.
-- The window still nests (24h <= 7d <= 30d): the extra predicate is applied to
-- the one 30-day row set the narrower FILTERs cut from.
--
-- CREATE OR REPLACE keeps the function's owner and privileges; the REVOKE/GRANT
-- block is repeated anyway so this file states everything it relies on (the
-- same reasoning 20260921055024 gives for repeating v1's index).
CREATE OR REPLACE FUNCTION canopy_metrics()
RETURNS JSONB
LANGUAGE sql STABLE
SET search_path = public, pg_temp
AS $$
WITH
-- v1's definition, unchanged: distinct users with at least one attributed
-- `events` row. NULL is the anonymous/system actor (0035); '' mirrors
-- admin_analytics' truthiness test, so the two dashboards agree.
active AS (
    SELECT
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.created_at >= now() - interval '24 hours') AS d1,
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.created_at >= now() - interval '7 days')   AS d7,
        COUNT(DISTINCT e.user_id)                                                            AS d30
    FROM events e
    WHERE e.user_id IS NOT NULL
      AND e.user_id <> ''
      AND e.created_at >= now() - interval '30 days'
),
event_keys (event_type, key) AS (
    VALUES
        ('session.started',              'tutor_sessions'),
        ('chat.message_sent',            'chat_messages'),
        ('document.upload',              'documents_uploaded'),
        ('auth.login',                   'logins'),
        ('error.5xx',                    'errors_5xx'),
        ('error.4xx',                    'errors_4xx'),
        ('quiz.generation_failed',       'quiz_generation_failed'),
        ('quiz.context_write_failed',    'quiz_context_write_failed'),
        ('rag.retrieval_failed',         'rag_retrieval_failed'),
        ('rag.chunks_dropped',           'rag_chunks_dropped'),
        ('rag.visibility_resync_failed', 'rag_visibility_resync_failed')
),
-- LEFT JOIN: a type nothing emitted this month is a MEASURED zero and keeps its
-- key — but only while `events` is being written at all (the WHERE).
event_counts AS (
    SELECT
        k.key,
        COUNT(e.created_at) FILTER (WHERE e.created_at >= now() - interval '24 hours') AS d1,
        COUNT(e.created_at) FILTER (WHERE e.created_at >= now() - interval '7 days')   AS d7,
        COUNT(e.created_at)                                                            AS d30
    FROM event_keys k
    LEFT JOIN events e
           ON e.event_type = k.event_type
          AND e.created_at >= now() - interval '30 days'
    WHERE EXISTS (SELECT 1 FROM events x WHERE x.created_at >= now() - interval '30 days')
    GROUP BY k.key
),
llm AS (
    SELECT
        COUNT(*)                                                             AS calls_d30,
        COUNT(*) FILTER (WHERE u.created_at >= now() - interval '7 days')    AS calls_d7,
        COUNT(*) FILTER (WHERE u.created_at >= now() - interval '24 hours')  AS calls_d1,
        COUNT(u.cost_usd)                                                    AS priced_d30,
        COALESCE(SUM(u.total_tokens) FILTER (WHERE u.total_tokens > 0), 0)   AS tokens_d30,
        COALESCE(SUM(u.total_tokens) FILTER (WHERE u.total_tokens > 0
                 AND u.created_at >= now() - interval '7 days'), 0)          AS tokens_d7,
        COALESCE(SUM(u.total_tokens) FILTER (WHERE u.total_tokens > 0
                 AND u.created_at >= now() - interval '24 hours'), 0)        AS tokens_d1,
        COALESCE(SUM(u.cost_usd) FILTER (WHERE u.cost_usd > 0), 0)           AS usd_d30,
        COALESCE(SUM(u.cost_usd) FILTER (WHERE u.cost_usd > 0
                 AND u.created_at >= now() - interval '7 days'), 0)          AS usd_d7,
        COALESCE(SUM(u.cost_usd) FILTER (WHERE u.cost_usd > 0
                 AND u.created_at >= now() - interval '24 hours'), 0)        AS usd_d1
    FROM llm_usage u
    WHERE u.created_at >= now() - interval '30 days'
),
counts (key, d1, d7, d30) AS (
    SELECT key, d1, d7, d30 FROM event_counts

    UNION ALL
    SELECT 'signups',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM users
    WHERE created_at >= now() - interval '30 days' AND google_id IS NOT NULL

    UNION ALL
    SELECT 'approvals',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM admin_audit_log
    WHERE created_at >= now() - interval '30 days' AND action = 'user.approve'

    UNION ALL
    SELECT 'quizzes_started',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM quiz_attempts
    WHERE created_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'quizzes_completed',
           COUNT(*) FILTER (WHERE completed_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE completed_at >= now() - interval '7 days'),
           COUNT(*)
    FROM quiz_attempts
    WHERE completed_at >= now() - interval '30 days' AND score IS NOT NULL

    UNION ALL
    SELECT 'documents_processed',
           COUNT(*) FILTER (WHERE processed_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE processed_at >= now() - interval '7 days'),
           COUNT(*)
    FROM documents
    WHERE processed_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'notes_created',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM notes
    WHERE created_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'flashcards_created',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM flashcards
    WHERE created_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'xp_events',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM xp_events
    WHERE created_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'achievements_earned',
           COUNT(*) FILTER (WHERE earned_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE earned_at >= now() - interval '7 days'),
           COUNT(*)
    FROM user_achievements
    WHERE earned_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'room_messages',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM room_messages
    WHERE created_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'feedback',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM feedback
    WHERE created_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'issue_reports',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM issue_reports
    WHERE created_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'llm_calls', calls_d1, calls_d7, calls_d30
    FROM llm WHERE calls_d30 > 0

    UNION ALL
    SELECT 'llm_tokens', tokens_d1, tokens_d7, tokens_d30
    FROM llm WHERE calls_d30 > 0

    -- ROUND(numeric) rounds half away from zero, which for these non-negative
    -- sums is the contract's half-up. It is monotone, so the cents nest
    -- because the dollars do.
    UNION ALL
    SELECT 'llm_cost_cents',
           ROUND(usd_d1 * 100)::BIGINT, ROUND(usd_d7 * 100)::BIGINT, ROUND(usd_d30 * 100)::BIGINT
    FROM llm WHERE priced_d30 > 0
)
SELECT jsonb_build_object(
    'active_users',
        (SELECT jsonb_build_object('24h', d1, '7d', d7, '30d', d30) FROM active),
    'counts',
        (SELECT COALESCE(
                    jsonb_object_agg(key, jsonb_build_object('24h', d1, '7d', d7, '30d', d30)),
                    '{}'::jsonb)
         FROM counts),
    'totals', jsonb_build_object(
        'users',               (SELECT COUNT(*) FROM users
                                WHERE google_id IS NOT NULL AND deleted_at IS NULL),
        'users_pending',       (SELECT COUNT(*) FROM users
                                WHERE google_id IS NOT NULL AND deleted_at IS NULL
                                  AND NOT is_approved),
        'documents',           (SELECT COUNT(*) FROM documents  WHERE deleted_at IS NULL),
        'notes',               (SELECT COUNT(*) FROM notes      WHERE deleted_at IS NULL),
        'flashcards',          (SELECT COUNT(*) FROM flashcards),
        'rooms',               (SELECT COUNT(*) FROM rooms),
        'rag_chunks',          (SELECT COUNT(*) FROM course_chunks),
        'rag_document_chunks', (SELECT COUNT(*) FROM course_chunks
                                WHERE category IS DISTINCT FROM 'catalog')
    )
);
$$;

REVOKE ALL ON FUNCTION canopy_metrics() FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION canopy_metrics() FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION canopy_metrics() TO service_role;
    END IF;
END $$;

NOTIFY pgrst, 'reload schema';

-- ==========================================================================
-- #766 graph: atomic mastery delta
-- (was 20261106042903_graph_node_mastery_atomic.sql)
-- ==========================================================================

-- #766: graph_nodes mastery updates become one atomic statement; the tier
-- CHECK loses a value that is never stored.
--
-- 1. apply_mastery_delta
--    services/graph_service.py::apply_graph_update read mastery_score and
--    times_studied in Python, added the delta, and wrote score, tier and
--    times_studied back by id: a blind read-modify-write. Two concurrent
--    writers on one node (a quiz submit and a tutor turn, two tabs) both read
--    the same `before` and the later write erased the earlier delta and its
--    times_studied increment. The append-only node_mastery_events log (0023)
--    kept the events, but the scalar the whole app reads drifted from them.
--
--    This function locks the row, applies the clamped delta, recomputes the
--    tier and increments times_studied in one transaction, and returns the
--    before/after it actually applied, so concurrent deltas compose.
--
--    The tier thresholds are PARAMETERS, not literals: config.py
--    (MASTERY_*_MIN) stays their one home, and the caller passes them. A
--    threshold change therefore takes effect on the next write of each node;
--    rows nobody studies keep their old stored tier until
--    scripts/backfill_mastery_tiers.py (dry-run by default) recomputes them.
--
--    'unexplored' still covers both "never studied" and "studied, score below
--    the struggling floor"; times_studied = 0 is the discriminator. Splitting
--    the tier would ripple through the CHECK, the frontend tier mirror
--    (Learn.tsx::tierForScore) and every tier filter, so it stays documented
--    rather than split.
--
-- 2. 'subject_root' leaves the CHECK
--    It is a synthetic tier graph_service.get_graph stamps on the per-course
--    hub node it builds in the response payload; no writer ever persists it.
--    Allowing it in storage only let a bad write through. Any such row (none
--    are expected) is reset to 'unexplored' first so the new constraint
--    validates; the backfill script then recomputes it from its score.

CREATE OR REPLACE FUNCTION apply_mastery_delta(
    p_node_id        TEXT,
    p_user_id        TEXT,
    p_delta          DOUBLE PRECISION,
    p_mastered_min   DOUBLE PRECISION,
    p_learning_min   DOUBLE PRECISION,
    p_struggling_min DOUBLE PRECISION
)
RETURNS TABLE (before_score DOUBLE PRECISION, after_score DOUBLE PRECISION, new_tier TEXT)
LANGUAGE plpgsql
VOLATILE
AS $$
DECLARE
    v_before DOUBLE PRECISION;
    v_after  DOUBLE PRECISION;
    v_tier   TEXT;
BEGIN
    -- FOR UPDATE: a concurrent writer waits here and then reads the score the
    -- first one committed, instead of the stale one it would have read.
    SELECT g.mastery_score INTO v_before
      FROM graph_nodes g
     WHERE g.id = p_node_id AND g.user_id = p_user_id
       FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;  -- deleted (or not this user's): no row, the caller skips it
    END IF;

    v_after := GREATEST(0.0, LEAST(1.0, v_before + COALESCE(p_delta, 0.0)));
    v_tier := CASE
        WHEN v_after >= p_mastered_min   THEN 'mastered'
        WHEN v_after >= p_learning_min   THEN 'learning'
        WHEN v_after >= p_struggling_min THEN 'struggling'
        ELSE 'unexplored'
    END;

    UPDATE graph_nodes g
       SET mastery_score   = v_after,
           mastery_tier    = v_tier,
           times_studied   = g.times_studied + 1,
           last_studied_at = now()
     WHERE g.id = p_node_id;

    before_score := v_before;
    after_score  := v_after;
    new_tier     := v_tier;
    RETURN NEXT;
END;
$$;

REVOKE ALL ON FUNCTION apply_mastery_delta(
    TEXT, TEXT, DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION
) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format(
                'REVOKE ALL ON FUNCTION apply_mastery_delta(TEXT, TEXT, DOUBLE PRECISION, '
                'DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION apply_mastery_delta(
            TEXT, TEXT, DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION
        ) TO service_role;
    END IF;
END;
$$;

-- 2. Drop 'subject_root' from the stored tier vocabulary.
UPDATE graph_nodes SET mastery_tier = 'unexplored' WHERE mastery_tier = 'subject_root';

DO $$
DECLARE
    c TEXT;
BEGIN
    -- The 0023 inline CHECK is auto-named; find it by what it checks rather
    -- than trusting the generated name.
    FOR c IN
        SELECT con.conname
          FROM pg_constraint con
         WHERE con.conrelid = 'graph_nodes'::regclass
           AND con.contype = 'c'
           AND pg_get_constraintdef(con.oid) LIKE '%mastery_tier%'
    LOOP
        EXECUTE format('ALTER TABLE graph_nodes DROP CONSTRAINT %I', c);
    END LOOP;
END;
$$;

ALTER TABLE graph_nodes
    ADD CONSTRAINT graph_nodes_mastery_tier_check
    CHECK (mastery_tier IN ('unexplored', 'struggling', 'learning', 'mastered'));

-- ==========================================================================
-- #758 indexing: explicit 'exhausted' terminal state
-- (was 20261106043300_document_index_terminal_state.sql)
-- ==========================================================================

-- #758: the indexing queue's terminal state is stored, not inferred.
--
-- Three defects in the #482 state machine (20260921063714 + 20260921073000):
--
-- 1. "Terminal" was `index_attempts >= max_attempts`, and max_attempts is the
--    INDEX_MAX_ATTEMPTS env var. Raising it silently re-queued every row the
--    sweeper had given up on; lowering it stranded `failed` rows that nothing
--    would ever retry or report. The admin list could only DERIVE "exhausted".
--    Now: an explicit 'exhausted' status, written by the application when an
--    attempt spends the last of the budget (or fails in a way no retry can
--    fix), and by the reaper below.
--
-- 2. A crash on the LAST attempt left the row 'indexing' with attempts = max.
--    The claim requires attempts < max, so neither it nor the inline claim
--    could ever retake it: 'indexing' forever, invisible as a failure, until an
--    admin happened to force it. The claim now reaps such a row to 'exhausted'
--    (error 'lease_expired') once its lease has run out — and, for the same
--    reason, any 'failed'/'partial' row already at the budget.
--
-- 3. 'skipped' was both the column DEFAULT (the migration's "do not touch"
--    marker for historical rows) and a real outcome. Any insert path that
--    omitted index_status landed silently in a terminal state nothing would
--    ever index. New rows now default to 'pending' — the queue the sweeper
--    drains — so an omission is indexed, or visibly fails, instead of
--    vanishing. Existing rows keep their value: the historical 'skipped' rows
--    are still scripts/backfill_document_index_status.py's to label.
--
-- The claim also clears index_error, as the application's own claim
-- (_claim_one) always has, so an 'indexing' row never carries the previous
-- attempt's error class.
--
-- Deploy order: this migration BEFORE the code (as `make promote` does). Code
-- ahead of it writes 'exhausted' into a CHECK that does not admit it; that
-- write fails, is logged, and leaves the row 'indexing' until its lease
-- expires and the old claim re-drives it — the pre-#758 behaviour, not a loss.

ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_index_status_check;
ALTER TABLE documents ADD CONSTRAINT documents_index_status_check
    CHECK (index_status IN
        ('pending', 'indexing', 'indexed', 'partial', 'failed', 'skipped', 'exhausted'));

ALTER TABLE documents ALTER COLUMN index_status SET DEFAULT 'pending';

-- The queue index skipped finished rows; a given-up row is finished too.
DROP INDEX IF EXISTS idx_documents_index_queue;
CREATE INDEX IF NOT EXISTS idx_documents_index_queue
    ON documents (index_status, index_attempts)
    WHERE index_status NOT IN ('indexed', 'skipped', 'exhausted');

-- claim_documents_for_indexing: defined once, in the
-- "#758 indexing: claim + reaper" section below.

-- ==========================================================================
-- #771 platform: drop dead state columns
-- (was 20261106043825_drop_dead_state_columns.sql)
-- ==========================================================================

-- #771 (workstream M): dead state left behind by the 0020/0024 redesign.
--
-- users.current_room_id — renamed from users.room_id in 0024, and nothing has
-- written (or read) it since: room membership is room_members. Dropping it
-- also drops users_current_room_id_fkey. Any value still in it predates 0024
-- and is meaningless.
ALTER TABLE users DROP COLUMN IF EXISTS current_room_id;

-- courses.deleted_at — created by 0020 for a catalog soft-delete that was
-- never built: no code, script or SQL function ever sets it, and its one
-- reader (topic_checklist_service.resolve_scope) is removed in the same
-- change. Refuse rather than silently un-hide if someone DID set it by hand.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'courses'
           AND column_name = 'deleted_at'
    ) AND EXISTS (SELECT 1 FROM courses WHERE deleted_at IS NOT NULL) THEN
        RAISE EXCEPTION
            'courses.deleted_at is set on some rows; decide what those courses '
            'should be before dropping the column (#771)';
    END IF;
END $$;
ALTER TABLE courses DROP COLUMN IF EXISTS deleted_at;

-- documents.processed_at STAYS, documented: a documents row is only inserted
-- once processing has finished (routes/documents.py), so today it always
-- equals created_at. It is still the public meaning the canopy_metrics()
-- `documents_processed` counts key on (20260921055024) and the documents API
-- returns it (frontend Document.processed_at); keeping it lets processing
-- become asynchronous later without a contract change.
COMMENT ON COLUMN documents.processed_at IS
    'When processing finished. Rows are inserted only after processing, so this equals created_at today; canopy_metrics() documents_processed counts on it (#771).';

-- ==========================================================================
-- #758 indexing: claim + reaper (final definition)
-- (was 20261106050224_document_index_reap_pending.sql)
-- ==========================================================================

-- #758 review: the reaper must also take an over-budget `pending` row.
--
-- The terminal-state section above made `claim_documents_for_indexing` reap rows whose budget is
-- spent and that nothing is running, but only 'partial', 'failed' and
-- lease-expired 'indexing'. A 'pending' row can carry index_attempts > 0:
-- services/document_indexing.py::_restore refunds a sweeper claim that could
-- not embed back to 'pending' with attempts - 1. If an operator then lowers
-- INDEX_MAX_ATTEMPTS to or below that count, the row is neither claimable (the
-- claim requires attempts < max) nor reaped, so it stays 'pending' for good:
-- out of retrieval, absent from the "exhausted" view, retried by nothing.
-- Now it is reaped to 'exhausted' with error 'attempts_exhausted'.
--
-- The full reap + claim, superseding 20260921073000's definition. Same
-- signature (PostgREST resolves by argument names; a changed one would leave
-- the old body as a live overload). Two statements, the reap then the claim:
-- a VOLATILE SQL function runs each under a fresh snapshot, so the claim sees
-- the reap's writes.
CREATE OR REPLACE FUNCTION claim_documents_for_indexing(
    max_attempts  INT,
    lease_seconds INT,
    batch_size    INT
)
RETURNS TABLE (id TEXT)
LANGUAGE sql
VOLATILE
AS $$
    -- Reap: a row whose budget is spent and that nothing is running is
    -- terminal. index_leased_at is left as it was, so an attempt that merely
    -- outlived its lease and then finishes still holds the row (its write is
    -- conditional on that lease) and records its real outcome over this one.
    UPDATE documents r
       SET index_status = 'exhausted',
           index_error  = CASE r.index_status
                              WHEN 'indexing' THEN 'lease_expired'
                              WHEN 'pending'  THEN 'attempts_exhausted'
                              ELSE r.index_error END
     WHERE r.deleted_at IS NULL
       AND r.index_attempts >= max_attempts
       AND (
               r.index_status IN ('partial', 'failed')
               -- A `pending` row over the budget: the claim's
               -- `index_attempts < max_attempts` excludes it, so without this
               -- it waited forever, out of retrieval and never reported.
            OR r.index_status = 'pending'
            OR (r.index_status = 'indexing'
                AND r.index_leased_at < now() - make_interval(secs => lease_seconds))
           );

    UPDATE documents d
       SET index_status    = 'indexing',
           index_leased_at = now(),
           index_attempts  = d.index_attempts + 1,
           index_error     = NULL
     WHERE d.id IN (
         SELECT c.id
           FROM documents c
          WHERE c.deleted_at IS NULL
            AND c.index_attempts < max_attempts
            AND (
                    -- A fresh upload belongs to its own inline attempt for
                    -- its first two minutes (unchanged).
                    (c.index_status = 'pending'
                     AND c.created_at < now() - interval '2 minutes')
                    -- A retry waits lease_seconds after the last attempt began.
                 OR (c.index_status IN ('partial', 'failed')
                     AND (c.index_leased_at IS NULL
                          OR c.index_leased_at < now() - make_interval(secs => lease_seconds)))
                    -- A crash-stranded attempt, once its lease has run out.
                 OR (c.index_status = 'indexing'
                     AND c.index_leased_at
                         < now() - make_interval(secs => lease_seconds))
                )
          ORDER BY c.index_leased_at NULLS FIRST, c.created_at
          LIMIT batch_size
          FOR UPDATE SKIP LOCKED
     )
 RETURNING d.id;
$$;

-- CREATE OR REPLACE keeps the function's privileges; restated so this file is
-- correct on its own (same guarded idiom as the two before it).
REVOKE ALL ON FUNCTION claim_documents_for_indexing(INT, INT, INT) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format(
                'REVOKE ALL ON FUNCTION claim_documents_for_indexing(INT, INT, INT) FROM %I',
                r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION claim_documents_for_indexing(INT, INT, INT)
            TO service_role;
    END IF;
END $$;

-- ==========================================================================
-- #763 email: idempotency generation
-- (was 20261106050246_email_sends_idempotency_gen.sql)
-- ==========================================================================

-- #763 review follow-up: which Resend Idempotency-Key the next attempt at a
-- dedupe key uses (email_service._idempotency_key).
--
-- An attempt whose outcome is UNKNOWN (transport error/timeout, a crash before
-- the status write, a 409 for a changed payload) leaves the generation alone,
-- so a re-claim reuses the key and Resend replays rather than re-delivers.
-- A DEFINITIVE provider failure (any other non-2xx response) bumps it, so the
-- next attempt is a fresh request and not a replay of the cached failure for
-- the rest of Resend's 24 h key window.
ALTER TABLE email_sends ADD COLUMN IF NOT EXISTS idempotency_gen INTEGER NOT NULL DEFAULT 0;
