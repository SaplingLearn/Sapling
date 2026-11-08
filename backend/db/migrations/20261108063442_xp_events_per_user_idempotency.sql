-- xp_events: idempotency is per student, not global.
--
-- 20260731193214_gamification created the ledger with
-- `idempotency_key TEXT NOT NULL UNIQUE`, but services/xp_service.py's
-- idempotency_key() never contained the user: an achievement's key is
-- `achievement_unlocked:achievement:<achievement_id>`, identical for every
-- student who earns that badge. So the first student ever to earn a badge was
-- paid its xp_reward and every later earner's insert hit the unique index —
-- which award_xp treats as "already paid" (409 → duplicate, awarded 0). The
-- badge was granted; the XP silently never was.
--
-- The key format is unchanged (heal reads source_id, existing rows keep their
-- keys); only the uniqueness scope moves to (user_id, idempotency_key). Within
-- one student every key that was unique stays unique, so per-student retry
-- protection is exactly as strong as before.
--
-- Students already denied are repaid by scripts/backfill_achievement_xp.py
-- (dry-run by default), run AFTER this migration. Not done here: it is a data
-- repair that has to go through award_xp to refresh the users.total_xp cache.
--
-- Idempotent: re-running finds the new constraint present and the old one
-- gone, and does nothing.

DO $$
DECLARE
    dupes bigint;
BEGIN
    -- The global UNIQUE makes a duplicate (user_id, idempotency_key) pair
    -- impossible in any environment built from these migrations. If one
    -- exists anyway, the old index is missing there (schema drift): stop and
    -- let a human decide, rather than silently deleting ledger rows that
    -- users.total_xp was computed from.
    SELECT count(*) INTO dupes FROM (
        SELECT 1 FROM xp_events
        GROUP BY user_id, idempotency_key
        HAVING count(*) > 1
    ) d;
    IF dupes > 0 THEN
        RAISE EXCEPTION
            'xp_events has % duplicate (user_id, idempotency_key) pair(s); '
            'resolve them before applying this migration', dupes;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'xp_events_user_id_idempotency_key_key'
          AND conrelid = 'xp_events'::regclass
    ) THEN
        ALTER TABLE xp_events
            ADD CONSTRAINT xp_events_user_id_idempotency_key_key
            UNIQUE (user_id, idempotency_key);
    END IF;
END $$;

-- The constraint the inline `UNIQUE` created (Postgres' default name).
ALTER TABLE xp_events DROP CONSTRAINT IF EXISTS xp_events_idempotency_key_key;

-- Belt and braces for a drifted environment: any other unique constraint, or
-- bare unique index, on idempotency_key ALONE would keep the bug alive under a
-- different name.
DO $$
DECLARE
    key_att smallint;
    r record;
BEGIN
    SELECT attnum INTO key_att FROM pg_attribute
    WHERE attrelid = 'xp_events'::regclass AND attname = 'idempotency_key';

    FOR r IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'xp_events'::regclass
          AND contype = 'u'
          AND conkey = ARRAY[key_att]
    LOOP
        EXECUTE format('ALTER TABLE xp_events DROP CONSTRAINT %I', r.conname);
    END LOOP;

    FOR r IN
        SELECT i.indexrelid::regclass AS idx FROM pg_index i
        WHERE i.indrelid = 'xp_events'::regclass
          AND i.indisunique
          AND i.indnkeyatts = 1
          AND i.indkey[0] = key_att
          AND NOT EXISTS (
              SELECT 1 FROM pg_constraint c WHERE c.conindid = i.indexrelid
          )
    LOOP
        EXECUTE format('DROP INDEX %s', r.idx);
    END LOOP;
END $$;
