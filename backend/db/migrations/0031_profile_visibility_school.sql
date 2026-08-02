-- 0031: allow the 'school' profile-visibility tier
--
-- The Settings UI has always offered three visibility tiers
-- (public / school / private, frontend Settings.tsx), but user_settings only
-- permitted ('public','private') (0001 baseline, re-declared in 0005). Selecting
-- "school" therefore hit the CHECK constraint and 500'd, so the tier was
-- unreachable. #342 makes it load-bearing: the school directory
-- (GET /api/social/students) is now scoped to the viewer's school and honors
-- this setting, so 'school' has to be a storable value.
--
-- The baseline CHECK is an inline column constraint, so Postgres auto-named it
-- user_settings_profile_visibility_check. Drop it (if present) and re-add a
-- widened, explicitly-named constraint.

ALTER TABLE user_settings
    DROP CONSTRAINT IF EXISTS user_settings_profile_visibility_check;

ALTER TABLE user_settings
    ADD CONSTRAINT user_settings_profile_visibility_check
    CHECK (profile_visibility IN ('public', 'school', 'private'));
