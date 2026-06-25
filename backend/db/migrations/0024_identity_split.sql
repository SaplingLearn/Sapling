-- 0024: identity split — public profile moves out of `users` into `user_profiles`, and the
-- duplicated profile columns are removed from `user_settings`. One source of truth per field.
-- `users` is NOT dropped (social/gamification FK it); we slim it in place. No user data today.
-- 🔒 = column-encrypted (stays TEXT).

CREATE TABLE user_profiles (
    user_id        TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    name           TEXT,            -- 🔒
    first_name     TEXT,            -- 🔒
    last_name      TEXT,            -- 🔒
    username       TEXT UNIQUE,
    avatar_url     TEXT,
    bio            TEXT,            -- 🔒
    location       TEXT,            -- 🔒
    website        TEXT,
    year           TEXT,            -- free-text (class standing); no fixed set
    majors         TEXT[] NOT NULL DEFAULT '{}',
    minors         TEXT[] NOT NULL DEFAULT '{}',
    learning_style TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Slim `users` to identity + auth + activity. (Empty table -> USING casts are never evaluated.)
ALTER TABLE users DROP COLUMN IF EXISTS name;
ALTER TABLE users DROP COLUMN IF EXISTS first_name;
ALTER TABLE users DROP COLUMN IF EXISTS last_name;
ALTER TABLE users DROP COLUMN IF EXISTS username;
ALTER TABLE users DROP COLUMN IF EXISTS avatar_url;
ALTER TABLE users DROP COLUMN IF EXISTS bio;
ALTER TABLE users DROP COLUMN IF EXISTS location;
ALTER TABLE users DROP COLUMN IF EXISTS website;
ALTER TABLE users DROP COLUMN IF EXISTS year;
ALTER TABLE users DROP COLUMN IF EXISTS majors;
ALTER TABLE users DROP COLUMN IF EXISTS minors;
ALTER TABLE users DROP COLUMN IF EXISTS learning_style;

ALTER TABLE users ALTER COLUMN last_active_date TYPE DATE USING last_active_date::date;
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE users RENAME COLUMN room_id TO current_room_id;
ALTER TABLE users ADD CONSTRAINT users_current_room_id_fkey
    FOREIGN KEY (current_room_id) REFERENCES rooms(id) ON DELETE SET NULL;

-- Remove profile fields duplicated onto user_settings (now owned by user_profiles).
ALTER TABLE user_settings DROP COLUMN IF EXISTS display_name;
ALTER TABLE user_settings DROP COLUMN IF EXISTS username;
ALTER TABLE user_settings DROP COLUMN IF EXISTS bio;
ALTER TABLE user_settings DROP COLUMN IF EXISTS location;
ALTER TABLE user_settings DROP COLUMN IF EXISTS website;

-- OAuth token expiry as a real instant; add updated_at.
ALTER TABLE oauth_tokens ALTER COLUMN expires_at TYPE TIMESTAMPTZ USING expires_at::timestamptz;
ALTER TABLE oauth_tokens ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Triggers
DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_user_profiles_updated_at ON user_profiles;
CREATE TRIGGER trg_user_profiles_updated_at BEFORE UPDATE ON user_profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_user_settings_updated_at ON user_settings;
CREATE TRIGGER trg_user_settings_updated_at BEFORE UPDATE ON user_settings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_oauth_tokens_updated_at ON oauth_tokens;
CREATE TRIGGER trg_oauth_tokens_updated_at BEFORE UPDATE ON oauth_tokens
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
