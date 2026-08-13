-- #542 D1/D2: attempt lifecycle columns.
--
-- mastery_before/after: without them a replayed or audited submit can't
-- reconstruct what the student saw, and no history UI can show progression
-- (plaintext analytics scalars, same rationale as score/total in #521).
--
-- abandoned_at: the "abandoned" half of the derived status. Status is NEVER
-- stored — it is derived at read time (completed_at → completed,
-- abandoned_at → abandoned, else in_progress), so it cannot drift from the
-- timestamps that define it. The lazy per-user sweep (routes/quiz.py) stamps
-- abandoned_at on in-progress attempts older than the documented TTL.

ALTER TABLE quiz_attempts
    ADD COLUMN mastery_before DOUBLE PRECISION,
    ADD COLUMN mastery_after  DOUBLE PRECISION,
    ADD COLUMN abandoned_at   TIMESTAMPTZ;
