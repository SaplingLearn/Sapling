# db/identity-code — identity split (user_profiles)

Branch: `db/identity-code` (off `db/academics-code`). Slice of the DB modular redesign.

## Contract recap

- API boundary keeps the ABSTRACT `course_id`. Term/semester is a second axis. KG keys on
  abstract `course_id`; class artifacts key on `offering_id`/`enrollment_id`. (Mostly irrelevant
  to identity — this slice touches no course/enrollment logic.)
- All DB via `db/connection.py::table()`. Encryption via `services/encryption.py`:
  `encrypt_if_present` at write, `decrypt_if_present` at read. 🔒 columns stay TEXT.

## Schema (migration `db/migrations/0024_identity_split.sql`, already applied)

New table `user_profiles` (1:1 with `users`, PK `user_id` → `users.id`):
`name`🔒, `first_name`🔒, `last_name`🔒, `username` (UNIQUE), `avatar_url`, `bio`🔒,
`location`🔒, `website`, `year`, `majors TEXT[]`, `minors TEXT[]`, `learning_style`,
`created_at`, `updated_at`.

`users` DROPPED: name, first_name, last_name, username, avatar_url, bio, location, website,
year, majors, minors, learning_style. `users.last_active_date` → DATE; +`updated_at`;
`room_id` → `current_room_id`.

`user_settings` DROPPED: display_name, username, bio, location, website (now owned by
user_profiles — one source of truth).

`oauth_tokens.expires_at` → TIMESTAMPTZ; +`updated_at`.

**One source of truth:** every profile field lives ONLY on `user_profiles`. No field is written
to both `users` and `user_profiles`, nor duplicated onto `user_settings`.

## Encryption boundary (unchanged semantics, moved to user_profiles)

🔒 columns on `user_profiles`: `name`, `first_name`, `last_name`, `bio`, `location`.
- WRITE: `encrypt_if_present(value)` before upsert/update into `user_profiles`.
- READ: `decrypt_if_present(row[col])` after select from `user_profiles`, including before
  returning to clients / injecting into prompts.
- `users.email` stays 🔒 on `users` (NOT moved). `username`/`avatar_url`/`website`/`year`/
  `majors`/`minors`/`learning_style` are plaintext (not 🔒).

## File-by-file change map (current → new)

### routes/auth.py (my scope: the profile-FIELD writes)
- `get_me` (`/me`): SELECT `username,name,avatar_url` currently from `users`. NEW: SELECT
  `id,is_approved,onboarding_completed` from `users`; fetch `username,name,avatar_url` from
  `user_profiles` (decrypt `name`).
- `google_callback` existing-user branch: currently `users.update({name, first_name, last_name,
  avatar_url, email, last_sign_in_at})`. NEW: `users.update({email, last_sign_in_at})` only;
  upsert `user_profiles` (on_conflict=user_id) with encrypted name/first_name/last_name +
  avatar_url.
- `google_callback` new-user branch: currently `users.insert({id,name,first_name,last_name,
  email,google_id,avatar_url,auth_provider,last_sign_in_at})`. NEW: `users.insert({id,email,
  google_id,auth_provider,last_sign_in_at})`; insert `user_profiles` row with encrypted
  name/first_name/last_name + avatar_url + username NULL.
- `oauth_tokens.upsert`: `expires_at` is now TIMESTAMPTZ. Keep `creds.expiry.isoformat()`
  when present, but pass `None` (not `""`) when absent — `""` is not a valid timestamptz.

### routes/profile.py (my scope: profile-FIELD read/writes; NOT the enrollment school-read)
- `_get_user_or_404`: split into (a) `users` SELECT `id,email,streak_count,created_at` and
  (b) `user_profiles` SELECT the profile fields; merge into one dict; decrypt
  `name/first_name/last_name/email/bio/location`. Returns same shape as today so downstream
  `get_public_profile` is unchanged. (Keeps the issue-#75 column-contract intent: only SELECT
  columns that exist on each table.)
- `_get_or_create_settings` + `_SETTINGS_COLS`: drop `username,display_name,bio,location,
  website` from the settings SELECT and the bio/location decrypt loop (those columns no longer
  exist on `user_settings`).
- `check_username`: lookup `username` on `user_profiles` (not `users`).
- `get_public_profile`: unchanged logic — reads from the merged `_get_user_or_404` dict. The
  `enrollments` school-read stays exactly as academics left it (out of scope).
- `update_profile`: write profile fields to `user_profiles` only (ensure-row via upsert/
  insert-if-missing). Drop the parallel `updates_settings` writes for username/bio/location/
  website/display_name. Username uniqueness check moves to `user_profiles`.
- `upload_user_avatar`: persist `avatar_url` to `user_profiles` (not `users`).
- helper `_get_or_create_profile(user_id)` added to centralize the user_profiles
  ensure-row + decrypt.

### routes/onboarding.py (my scope: ONLY the profile-field write; NOT the enrollment loop)
- `save_onboarding_profile`: the `users.update({name,first_name,last_name,year,majors,minors,
  learning_style})` block moves to a `user_profiles` upsert (encrypt name/first_name/last_name).
  `onboarding_completed=True` STAYS on `users` (it's an auth/status flag, not a profile field).
  The course/enrollment loop (`resolve_offering`, `enrollments`) is untouched (academics owns it).

### models/__init__.py (my scope)
- `UpdateProfileBody`: keep `username/bio/location/website`; drop `display_name` (no longer a
  user_settings field — display name is the profile `name`). Add nothing else.
- `SettingsResponse`: drop `display_name,username,bio,location,website` (moved off
  user_settings). These models are documentation-only (not used as `response_model`), but kept
  consistent with the schema.
- `PublicProfileResponse`: unchanged (it already describes the merged public profile shape).

### tests/test_profile_routes.py (my scope — update for new layout)
- Update factories so `users`/`user_profiles`/`user_settings` are separate mocks and the
  profile fields come from `user_profiles`.
- `TestGetUserOr404SelectColumns`: split assertion — `users` SELECT must only contain slimmed
  columns; `user_profiles` SELECT carries the profile fields. Rewrite the schema sets.
- `TestUpdateProfile.test_updates_user_fields`: assert the write lands on `user_profiles`.
- `TestUploadAvatar`: assert `avatar_url` persisted to `user_profiles`.
- Add a test asserting a `user_profiles` row is ensured when missing.

### tests/test_onboarding_routes.py (touched because it asserts the moved write)
- `TestSaveOnboardingProfile`: assert name/first_name/last_name/year/majors/minors/
  learning_style land on `user_profiles` (not `users`); `onboarding_completed` stays on `users`.

## Test list

- `tests/test_profile_routes.py` — full file, updated for user_profiles.
- `tests/test_onboarding_routes.py` — `TestSaveOnboardingProfile` updated.
- `tests/test_auth_domain.py` — unaffected (domain allowlist only); must stay green.
- Whole suite: `$PY -m pytest tests/ -q` stays at baseline (722 passed; the 2 pre-existing
  `test_storage_service.py` failures are env-config, not mine).

## Out of scope (do NOT touch)

- The `enrollments` school-read in `profile.py::get_public_profile` and the enrollment loop in
  `onboarding.py` — academics owns these (already committed on this base).
- `services/academics.py`, `graph_service.py`, `course_context_service.py`.
- Other readers of `users.name`/profile fields in OTHER domains' files: `routes/social.py`,
  `routes/quiz.py`, `routes/learn.py`, `services/users_search.py`,
  `services/graph_service.py::ensure_user_exists`. These will need their own slices to read from
  `user_profiles`; their tests mock `table()` so they stay green here. **Cross-domain dependency
  noted** — flagged for the social/quiz/learn/graph slices.
