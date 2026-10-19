-- 20260929050800_learning_loop_state_rev.sql
-- Learning loop, PKG-06 reopen (owner decision A38 06(q)): a compare-and-set
-- revision on sessions.loop_state. A streamed teach turn and /check/next can
-- overlap on one session; each save filters loop_state_rev=eq.<loaded> and
-- sets it to loaded + 1, so a stale writer updates zero rows (a conflict it
-- re-applies on the fresh state) instead of overwriting the other's changes.
-- 0 on every existing row. Deploy order: this migration BEFORE the code (the
-- store selects and filters on it). Existing table: RLS/grants unchanged.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS loop_state_rev bigint NOT NULL DEFAULT 0;
