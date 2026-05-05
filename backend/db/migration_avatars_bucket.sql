-- Create the `avatars` storage bucket used by:
--   • backend/services/storage_service.py::upload_avatar
--     (path: avatars/{user_id}/avatar.{ext})
--   • backend/services/storage_service.py::upload_cosmetic_asset
--     (path: cosmetics/{cosmetic_id}.{ext})
--
-- Settings derived from the validators in storage_service.py:
--   • public = true so the public-URL read path
--     (/storage/v1/object/public/avatars/...) works for <img src>
--     without auth — required because browsers can't send the
--     service-role key.
--   • file_size_limit = 5 MB to match MAX_AVATAR_SIZE in
--     backend/config.py:35.
--   • allowed_mime_types matches ALLOWED_CONTENT_TYPES in
--     backend/services/storage_service.py:9.
--
-- Existence of this bucket was the underlying cause of all the
-- avatar-upload failures reported in issue #75 and chased through
-- PRs #84, #86, and #87. Without it, every upload hit Supabase
-- Storage's "Bucket not found" 404. Run this once per environment
-- (Supabase project) when bootstrapping. ON CONFLICT makes it
-- idempotent — safe to re-run.

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'avatars',
    'avatars',
    true,
    5242880,  -- 5 MB
    ARRAY['image/jpeg', 'image/png', 'image/webp', 'image/gif']
)
ON CONFLICT (id) DO NOTHING;
