-- E7 (#543 addendum Part 2): stop dropping event_type.
--
-- routes/quiz.py::submit_quiz derives a categorical reading of the attempt
-- from the score ratio — correct (>=0.7) / partial (>=0.4) / confusion — and
-- passes it into apply_graph_update, which then wrote `delta` and `reason`
-- and silently discarded it. The mastery log therefore recorded how far a
-- concept moved but never what kind of evidence moved it, so "recovering
-- from confusion" and "drifting down from partial credit" are the same row.
--
-- Deliberately a bare nullable TEXT, with no CHECK:
--
--   * every non-quiz writer (tutor mastery tools, the document pipeline,
--     notes extraction, manual adds) supplies no category at all, and NULL is
--     the honest value for "this writer doesn't classify" — not a default
--     that would make un-categorised events indistinguishable from confident
--     ones;
--   * a CHECK would pin today's three quiz labels into DDL, and the next
--     writer to classify its own events (the tutor is the obvious one) would
--     need a migration to add a value. The vocabulary belongs to the callers
--     while it is still moving; graph_service normalises and omits blanks.
--
-- Append-only table, additive column: existing rows keep NULL and every
-- existing reader (get_graph's 14-day learning_velocity + last-5 echo)
-- projects named columns, so none of them see a shape change.

-- IF NOT EXISTS per the repo's idempotent-DDL rule: a migration that half
-- applied must be re-runnable without hand-editing the ledger.
ALTER TABLE node_mastery_events
    ADD COLUMN IF NOT EXISTS event_type TEXT;
