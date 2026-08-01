-- 0045: detect (and document) the trigger loss 0044 can cause on a catalog
-- that holds admin-created achievements.
--
-- ── The hazard ──────────────────────────────────────────────────────────────
-- 0044 rebuilds triggers with:
--
--     DELETE FROM achievement_triggers t
--      USING achievements a
--      WHERE t.achievement_id = a.id AND a.status = 'live';
--
-- then re-inserts triggers for the 30 slugs in its own VALUES list. That DELETE
-- is scoped to `status = 'live'` on the assumption that the live catalog is
-- exactly the ten 0007 seeds it demotes one statement earlier. It is not
-- scoped to those slugs.
--
-- POST /api/admin/achievements has shipped for a while and creates rows that
-- default to status = 'live'. Any achievement an admin created through the
-- wiki therefore had its triggers deleted and NOT re-inserted — leaving a
-- live, visible badge that nothing can ever award, while routes/profile.py
-- still renders its progress bar. Silent: no error, no log line.
--
-- ── Why this migration cannot repair it ─────────────────────────────────────
-- The triggers were DELETEd. achievement_triggers is not append-only and has
-- no history, tombstone or audit trail, so the (trigger_type, threshold) pairs
-- an admin configured are simply gone — there is nothing in the database to
-- reconstruct them from. A data-only repair is not expressible. Re-adding the
-- triggers is a human decision (which stat? which threshold?) and belongs in
-- the admin wiki, not in a guessed-at migration.
--
-- So this migration is DETECTION + DOCUMENTATION only. It mutates nothing and
-- is a no-op on any catalog that only ever held the seeded slugs — which is
-- every environment where no admin used the wiki before 0044 ran.
--
-- Deliberately NOT auto-demoting the affected rows to 'draft': that would
-- reliably hide the broken badges from users, but grant_achievement 409s on a
-- draft, so it would also silently break an admin who created a badge to hand
-- out manually. Surfacing beats guessing.
--
-- ── Operator pre-flight, BEFORE deploying 0044 to an environment ────────────
--   SELECT slug, status FROM achievements;
-- If that returns only the ten 0007 seeds plus the thirty 0044 slugs, nothing
-- was or will be lost and this migration prints nothing.
--
-- ── Operator repair, if the check below warns ───────────────────────────────
--   1. The named slugs are live badges with no triggers.
--   2. In the admin wiki, either re-add each badge's trigger(s), or Unpublish
--      it until its triggers are back.
--   3. Nobody lost a badge: user_achievements rows were never touched, by
--      0044 or by this migration.

DO $$
DECLARE
    orphaned TEXT;
BEGIN
    SELECT string_agg(a.slug, ', ' ORDER BY a.slug)
      INTO orphaned
      FROM achievements a
     WHERE a.status = 'live'
       AND NOT EXISTS (
           SELECT 1 FROM achievement_triggers t
            WHERE t.achievement_id = a.id
       );

    IF orphaned IS NOT NULL THEN
        RAISE WARNING
            '0045: % live achievement(s) have no triggers and can never be '
            'earned: %. 0044''s trigger rebuild deletes triggers for ALL live '
            'achievements, so any badge created through the admin wiki lost '
            'them. Re-add the triggers in the wiki, or unpublish the badge. '
            'No user_achievements rows were affected.',
            (SELECT count(*) FROM achievements a
              WHERE a.status = 'live'
                AND NOT EXISTS (SELECT 1 FROM achievement_triggers t
                                 WHERE t.achievement_id = a.id)),
            orphaned;
    END IF;
END $$;
