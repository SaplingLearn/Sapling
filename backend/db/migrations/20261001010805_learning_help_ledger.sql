-- Learning loop series PKG-14 (review fix round, owner decision 1, spec §13 A93):
-- the per-student HELP LEDGER, on half A's learning_reveals table.
--
-- kind = 'help':  question_hash got help at `rung` (0..LADDER_MAX_RUNG = 6):
--                 a hint rung above H0 (any session or surface), an H4 sibling
--                 payload (recorded at RUNG_NO_CREDIT_MIN = 4 on the sibling),
--                 an H6 release / worked solution / deterministic reference.
--                 Written as the help is served, never at turn end.
-- kind = 'posed': the student was shown question_hash's prompt (a loop check,
--                 a probe item, a review item, a post-test pose). `graded_at`
--                 is set once the item is graded; every ungraded posed item is
--                 in the served-text scan set (bounded by LOOP_SCAN_POSED_MAX).
-- 'reveal' and 'unscanned' keep half A's meaning (20260930031644).
--
-- Every grade's floor is the MAX help ever recorded for (student, item), a
-- 'reveal' counting as RUNG_NO_CREDIT_MIN — re-read inside the grading claim,
-- right before the one evidence write. Append-only except `graded_at`; hashes,
-- ids, rungs and timestamps only — never item or tutor text. Idempotent.
ALTER TABLE learning_reveals ADD COLUMN IF NOT EXISTS rung smallint;
ALTER TABLE learning_reveals ADD COLUMN IF NOT EXISTS graded_at timestamptz;

ALTER TABLE learning_reveals DROP CONSTRAINT IF EXISTS learning_reveals_kind_check;
ALTER TABLE learning_reveals ADD CONSTRAINT learning_reveals_kind_check
  CHECK (kind IN ('reveal', 'unscanned', 'help', 'posed'));

-- half A's "(kind = 'reveal') = (question_hash IS NOT NULL)" becomes: only an
-- 'unscanned' marker has no question hash
ALTER TABLE learning_reveals DROP CONSTRAINT IF EXISTS learning_reveals_check;
ALTER TABLE learning_reveals DROP CONSTRAINT IF EXISTS learning_reveals_hash_check;
ALTER TABLE learning_reveals ADD CONSTRAINT learning_reveals_hash_check
  CHECK ((kind = 'unscanned') = (question_hash IS NULL));

ALTER TABLE learning_reveals DROP CONSTRAINT IF EXISTS learning_reveals_rung_check;
ALTER TABLE learning_reveals ADD CONSTRAINT learning_reveals_rung_check
  CHECK ((kind = 'help') = (rung IS NOT NULL) AND (rung IS NULL OR rung BETWEEN 0 AND 6));

ALTER TABLE learning_reveals DROP CONSTRAINT IF EXISTS learning_reveals_graded_check;
ALTER TABLE learning_reveals ADD CONSTRAINT learning_reveals_graded_check
  CHECK (graded_at IS NULL OR kind = 'posed');

CREATE INDEX IF NOT EXISTS learning_reveals_user_hash ON learning_reveals (user_id, question_hash);
CREATE INDEX IF NOT EXISTS learning_reveals_posed_open
  ON learning_reveals (user_id, at DESC) WHERE kind = 'posed' AND graded_at IS NULL;

-- RLS and the backend-only grants are table-level (20260930031644) and unchanged.
NOTIFY pgrst, 'reload schema';
