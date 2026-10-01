-- 20260926231744_learning_loop_beta.sql
-- Learning loop series PKG-00: per-user opt-in for the new tutor loop.
-- Paired with the LEARNING_LOOP_ENABLED env var (config.py); both must be
-- true for learning.gate.learning_loop_active() to return True.
ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS learning_loop_beta boolean NOT NULL DEFAULT false;
