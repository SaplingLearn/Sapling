-- Learning loop PKG-04, A38 fix round 3: remember a combination-only failure.
-- A multi-concept drafting call whose output never validated is split and each
-- concept re-run alone (services/check_item_service.py). When every concept of
-- the split stored items alone, the failure was the combination's, so they are
-- marked `solo` and drafted alone on later passes (N calls, not 1 + N) while
-- source_fp is unchanged and updated_at is within
-- CHECK_ITEM_REDRAFT_FAILURE_TTL_DAYS. Deploy BEFORE the code: the code reads
-- and writes the column, and a missing column makes the bookkeeping fail open
-- (a WARNING; every concept drafted batched, as before).
ALTER TABLE check_item_draft_failures ADD COLUMN IF NOT EXISTS solo boolean NOT NULL DEFAULT false;
