-- Study hub Daily Goal: the student's target study minutes per day.
-- Read and written by routes/study.py (GET /daily, PATCH /daily-goal). The
-- existing users.daily_goal_xp is an XP target for gamification and stays as is;
-- the Study screen measures minutes, so it gets its own column.
-- user_settings already carries owner-only RLS policies (20261108094129), which
-- cover a new column without changes.
ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS daily_goal_minutes INT NOT NULL DEFAULT 30;

ALTER TABLE user_settings
    DROP CONSTRAINT IF EXISTS user_settings_daily_goal_minutes_range;
ALTER TABLE user_settings
    ADD CONSTRAINT user_settings_daily_goal_minutes_range
    CHECK (daily_goal_minutes BETWEEN 5 AND 600);
