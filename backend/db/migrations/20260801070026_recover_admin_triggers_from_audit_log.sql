-- 0046: supersede 0045's guidance and actually repair the trigger loss 0044
-- caused on admin-created achievements.
--
-- Formerly 0046_recover_admin_triggers_from_audit_log.sql, renamed at the timestamp
-- cutover (#509). Bare 0043/0044/0045/0046 references in this file and
-- its siblings are those original sequential numbers.
--
-- ── Correcting the record ───────────────────────────────────────────────────
-- 0045 states:
--
--     "achievement_triggers is not append-only and has no history, tombstone
--      or audit trail, so the (trigger_type, threshold) pairs an admin
--      configured are simply gone — there is nothing in the database to
--      reconstruct them from."
--
-- That is WRONG, and its operator instruction ("re-add each badge's trigger in
-- the wiki") therefore asked an operator to reconstruct exact values from
-- memory when the exact values were sitting on disk the whole time.
--
-- Every admin-created trigger was written through routes/admin.py's trigger
-- endpoints, and all three of them call log_admin_action:
--
--   POST   /api/admin/achievements/triggers              -> 'trigger.create'
--          payload {achievement_id, trigger_type, trigger_threshold},
--          target_id = the new trigger's id
--   PATCH  /api/admin/achievements/triggers/{id}         -> 'trigger.update'
--          payload = the changed subset of {trigger_type, trigger_threshold}
--          (never achievement_id — UpdateAchievementTriggerBody has no such
--          field), target_id = the trigger's id
--   DELETE /api/admin/achievements/triggers/{id}         -> 'trigger.delete'
--          no payload, target_id = the trigger's id
--
-- admin_audit_log (0010_admin_portal.sql) is append-only in practice and was
-- never touched by 0044. So the latest configured state of every admin-created
-- trigger is recoverable by replaying its events in created_at order:
-- achievement_id from the create, trigger_type/trigger_threshold from the most
-- recent event that carried each field, and gone if a delete followed.
--
-- 0044's DELETE went through raw SQL, not the API, so it logged nothing — the
-- last audit event for a wiped trigger is its create/update, never a delete.
-- A trigger an admin deliberately deleted through the wiki DOES have a
-- trigger.delete tombstone and is correctly NOT resurrected here.
--
-- ── Why this migration repairs rather than documents ────────────────────────
-- Replaying an audit log into live data is a real decision, so the guards are
-- the argument:
--
--   * The values are EXACT, not inferred. This is not a guess at "which stat,
--     which threshold" — it is the row the admin last saved.
--   * It only ever touches an achievement that is status = 'live' AND has ZERO
--     achievement_triggers rows. It cannot overwrite, duplicate or contradict
--     any trigger that currently exists, and it cannot touch a draft.
--   * It is idempotent twice over: the zero-triggers guard makes a second run
--     a no-op, and rows are restored under their ORIGINAL trigger id with
--     ON CONFLICT (id) DO NOTHING, so admin_audit_log.target_id keeps pointing
--     at a live row.
--   * A no-op on any environment that never lost anything, which is every
--     environment where no admin used the wiki before 0044 ran.
--
-- The alternative — documentation only — was rejected because 0045 already
-- tried it and the guidance never reached anyone: its sole output is a
-- server-side RAISE WARNING, and db/migrate.py registered no psycopg notice
-- handler, so the message was discarded before the operator could read it.
-- (That is fixed in the same change as this migration; see below.) Leaving a
-- second migration that also only prints would repeat the mistake, and the
-- alternative to repairing is a live badge that silently awards nothing.
--
-- Not fixed here, deliberately: an achievement whose triggers predate the
-- admin API (seeded by 0007/0044 migrations, never logged) has nothing to
-- replay. Those all still hold their triggers, since 0044 re-inserted them, so
-- they are not in the affected set. Any that somehow are get NAMED in the
-- report below rather than guessed at.
--
-- ── Manual recovery query, for an operator who wants to inspect first ───────
-- The SELECT inside the DO block below is the query. To preview without
-- writing anything, run it standalone:
--
--   WITH ev AS (
--       SELECT target_id AS trigger_id, action, payload, created_at, id AS event_id
--         FROM admin_audit_log
--        WHERE target_type = 'trigger'
--          AND action IN ('trigger.create','trigger.update','trigger.delete')
--          AND target_id IS NOT NULL
--   ),
--   created AS (
--       SELECT DISTINCT ON (trigger_id) trigger_id,
--              payload->>'achievement_id' AS achievement_id
--         FROM ev WHERE action = 'trigger.create'
--        ORDER BY trigger_id, created_at, event_id
--   ),
--   typ AS (
--       SELECT DISTINCT ON (trigger_id) trigger_id,
--              payload->>'trigger_type' AS trigger_type
--         FROM ev
--        WHERE action IN ('trigger.create','trigger.update')
--          AND payload->>'trigger_type' IS NOT NULL
--        ORDER BY trigger_id, created_at DESC, event_id DESC
--   ),
--   thr AS (
--       SELECT DISTINCT ON (trigger_id) trigger_id,
--              (payload->>'trigger_threshold')::int AS trigger_threshold
--         FROM ev
--        WHERE action IN ('trigger.create','trigger.update')
--          AND payload->>'trigger_threshold' IS NOT NULL
--        ORDER BY trigger_id, created_at DESC, event_id DESC
--   )
--   SELECT a.slug, c.trigger_id, t.trigger_type, h.trigger_threshold
--     FROM created c
--     JOIN typ t USING (trigger_id)
--     JOIN thr h USING (trigger_id)
--     JOIN achievements a ON a.id = c.achievement_id::uuid
--    WHERE NOT EXISTS (SELECT 1 FROM ev d
--                       WHERE d.trigger_id = c.trigger_id
--                         AND d.action = 'trigger.delete')
--      AND a.status = 'live'
--      AND NOT EXISTS (SELECT 1 FROM achievement_triggers t2
--                       WHERE t2.achievement_id = a.id);
--
-- No user_achievements row is read or written by any of this: nobody gains or
-- loses a badge they already hold.

DO $$
DECLARE
    restored  INT := 0;
    still_bad TEXT;
BEGIN
    WITH ev AS (
        -- The uuid guards keep a malformed audit row from aborting the whole
        -- migration on a failed cast. In practice they never bite: both ids are
        -- written by the API only after PostgREST accepted the row, so a bad
        -- value never reaches log_admin_action.
        SELECT l.target_id AS trigger_id, l.action, l.payload,
               l.created_at, l.id AS event_id
          FROM admin_audit_log l
         WHERE l.target_type = 'trigger'
           AND l.action IN ('trigger.create', 'trigger.update', 'trigger.delete')
           AND l.target_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    ),
    created AS (
        -- One create per trigger id (the id is minted by the insert), so this
        -- is the only source of achievement_id.
        SELECT DISTINCT ON (trigger_id) trigger_id,
               payload->>'achievement_id' AS achievement_id
          FROM ev
         WHERE action = 'trigger.create'
           AND payload->>'achievement_id' ~*
               '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
         ORDER BY trigger_id, created_at, event_id
    ),
    typ AS (
        -- Latest event that carried trigger_type. PATCH logs only the changed
        -- subset, so a partial update must not blank the other column.
        -- event_id is a deterministic tiebreaker for same-instant events.
        SELECT DISTINCT ON (trigger_id) trigger_id,
               payload->>'trigger_type' AS trigger_type
          FROM ev
         WHERE action IN ('trigger.create', 'trigger.update')
           AND payload->>'trigger_type' IS NOT NULL
         ORDER BY trigger_id, created_at DESC, event_id DESC
    ),
    thr AS (
        SELECT DISTINCT ON (trigger_id) trigger_id,
               (payload->>'trigger_threshold')::int AS trigger_threshold
          FROM ev
         WHERE action IN ('trigger.create', 'trigger.update')
           AND payload->>'trigger_threshold' ~ '^-?[0-9]+$'
         ORDER BY trigger_id, created_at DESC, event_id DESC
    ),
    alive AS (
        SELECT c.trigger_id, c.achievement_id, t.trigger_type, h.trigger_threshold
          FROM created c
          JOIN typ t USING (trigger_id)
          JOIN thr h USING (trigger_id)
         WHERE NOT EXISTS (
               SELECT 1 FROM ev d
                WHERE d.trigger_id = c.trigger_id
                  AND d.action = 'trigger.delete'
           )
    ),
    ins AS (
        INSERT INTO achievement_triggers
            (id, achievement_id, trigger_type, trigger_threshold)
        SELECT al.trigger_id::uuid, a.id, al.trigger_type, al.trigger_threshold
          FROM alive al
          JOIN achievements a ON a.id = al.achievement_id::uuid
         WHERE a.status = 'live'
           -- The whole safety story: never touch an achievement that has any
           -- trigger today. Evaluated against the pre-statement snapshot, so a
           -- badge with two restorable triggers gets both.
           AND NOT EXISTS (
               SELECT 1 FROM achievement_triggers t2
                WHERE t2.achievement_id = a.id
           )
        ON CONFLICT (id) DO NOTHING
        RETURNING 1
    )
    SELECT count(*) INTO restored FROM ins;

    -- Anything still live with no triggers is unearnable whatever the cause:
    -- its triggers were only ever seeded by SQL (nothing to replay), or an
    -- admin deliberately deleted them through the wiki and left the badge
    -- published (correctly not resurrected above). Name it instead of guessing
    -- at it — this residue is what 0045's manual procedure is the right answer
    -- for.
    SELECT string_agg(a.slug, ', ' ORDER BY a.slug)
      INTO still_bad
      FROM achievements a
     WHERE a.status = 'live'
       AND NOT EXISTS (
           SELECT 1 FROM achievement_triggers t WHERE t.achievement_id = a.id
       );

    IF restored > 0 THEN
        RAISE NOTICE
            '0046: restored % achievement trigger(s) from admin_audit_log '
            '(0044 deleted them; 0045 wrongly called them unrecoverable). '
            'No user_achievements rows were touched.', restored;
    END IF;

    IF still_bad IS NOT NULL THEN
        RAISE WARNING
            '0046: these live achievement(s) still have NO triggers and can '
            'never be earned: %. admin_audit_log holds no restorable trigger '
            'for them — either their triggers were seeded by SQL rather than '
            'the admin API, or an admin deleted them deliberately through the '
            'wiki (deliberate deletions are not resurrected). Re-add their '
            'trigger(s) in the wiki, or unpublish the badge. No '
            'user_achievements rows were touched.', still_bad;
    END IF;

    IF restored = 0 AND still_bad IS NULL THEN
        RAISE NOTICE '0046: nothing to repair — every live achievement has triggers.';
    END IF;
END $$;
