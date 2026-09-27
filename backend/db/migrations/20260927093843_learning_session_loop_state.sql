-- 20260927093843_learning_session_loop_state.sql
-- Learning loop series PKG-06: per-session ZPD loop state (spec §4, §9).
-- keyed by question_hash: {rung, attempts, first_shown_at, last_rung_at, attempted_at[]}; no free text.
-- top-level id lists added later: "revealed" (A23, H4 siblings shown), "probe", "plan", "sr", "review" (PKG-08/12).
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS loop_state jsonb NOT NULL DEFAULT '{}'::jsonb;
