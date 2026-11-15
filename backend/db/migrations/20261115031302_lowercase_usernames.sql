-- Usernames are lowercased on write now (routes/profile.py::update_profile),
-- and both the availability check and the write's uniqueness check compare
-- case-insensitively (`_username_holders`). This brings the handles stored
-- before that change into line: each mixed-case username is lowercased —
-- but ONLY when no other row already holds the same name in some other case.
--
-- A collision is left exactly as it is, for a person to settle: `user_profiles
-- .username` is UNIQUE case-SENSITIVELY, so 'Alice' and 'alice' (or 'Alice'
-- and 'ALICE') could both be stored, and lowercasing either would either
-- violate that constraint or silently merge two people's handles. Both twins
-- are skipped, not just one, so neither student's handle changes under them.
-- The app already treats such a name as taken for anyone but its holders.
--
-- No unique index on lower(username) here: case twins may exist in any
-- environment (the case-sensitive UNIQUE never prevented them), and an index
-- would fail the migration there. Add it in a later migration once every
-- environment reports no twins:
--   SELECT lower(username), count(*) FROM user_profiles
--   WHERE username IS NOT NULL GROUP BY 1 HAVING count(*) > 1;
UPDATE user_profiles AS p
SET username = lower(p.username)
WHERE p.username IS NOT NULL
  AND p.username <> lower(p.username)
  AND NOT EXISTS (
      SELECT 1
      FROM user_profiles AS q
      WHERE q.user_id <> p.user_id
        AND lower(q.username) = lower(p.username)
  );
