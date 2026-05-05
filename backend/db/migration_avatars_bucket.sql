-- Create the `avatars` storage bucket used by:
--   • backend/services/storage_service.py::upload_avatar
--     (path: avatars/{user_id}/avatar.{ext})
--   • backend/services/storage_service.py::upload_cosmetic_asset
--     (path: cosmetics/{cosmetic_id}.{ext})
--
-- NOTE: as of the lifespan handler in backend/main.py, the backend
-- itself calls `ensure_bucket_exists` on startup against this bucket
-- with the same settings, so new environments self-bootstrap. This
-- file is kept as the canonical SQL doc + manual fallback for
-- environments where running the backend isn't an option (e.g.,
-- inspecting bucket settings via the SQL editor, or restoring a
-- bucket that was deliberately deleted).
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
-- Idempotent — ON CONFLICT (id) DO NOTHING means re-running this on
-- an already-bootstrapped environment is a no-op.

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'avatars',
    'avatars',
    true,
    5242880,  -- 5 MB
    ARRAY['image/jpeg', 'image/png', 'image/webp', 'image/gif']
)
ON CONFLICT (id) DO NOTHING;
