# chat_tutor "before" cassettes (#149 comparison set)

Recorded 2026-07-30 against the PRE-#149 code (5-tool agent, original
preamble, no GRAPH CONTEXT seed block — `SAPLING_EVAL_NO_SEED=1`), with the
TutorRetrieval fixture seam already in place so the runs were Supabase-free.

Purpose: the committed "before" half of the #149 score comparison. The live
`chat_tutor/` directory holds the "after" cassettes the committed baselines
gate on. To reproduce the delta, swap this directory in as
`cassettes/chat_tutor` and replay.

Per-evaluator mean over these 16 cases (final evaluator set):
ExpositoryHasStructure 0.812, GraphToolUsed 0.938, GroundedConcept 0.812,
MasteryUpdateEmitted 0.688, NonEmpty / SocraticEndsWithQuestion /
TeachBackProbes / NoToolMisuse 1.000. After: 1.000 / 1.000 / 0.875 / 1.000 /
(unchanged 1.000s) — see ADR 0023.

Not read by `run_all.py`; safe to delete once the comparison has served its
purpose.
