# 0014: Adaptive quiz iteration — spaced repetition + difficulty + history

- Status: accepted
- Date: 2026-05-03
- Refines: 0005, 0013

## Context

ADR 0013 closed out refactor #2 with three known gaps called out under
"What it doesn't do (yet)":

1. No spaced repetition. The agent biased toward weakest-mastery
   concepts but ignored `last_studied_at`, so a stale 0.85-mastery
   concept never got revisited until it decayed.
2. No within-session adaptive difficulty. The agent honored the
   user-requested `difficulty` literally, even after the student had
   bombed the last three attempts on the same concept.
3. No quiz-attempt history on the agent path. The legacy fallback
   path read `quiz_context_service.get_quiz_context` and stuffed it
   into the prompt template; the agent path didn't see it at all, so
   the agent couldn't write distractors that mirrored *this* student's
   prior errors.

This ADR records the small follow-up that closes those three gaps
without disturbing the wire format, the fallback contract, or the
agent's output schema.

## Decision

Add one new tool, `read_recent_quiz_attempts(concept_node_id)`, and
update the quiz agent's system prompt to (a) weight `last_reviewed_at`
when picking concepts (spaced repetition) and (b) modulate the
difficulty mix based on `recent_attempts.accuracy` (adaptive
difficulty). Tool registration order is intentional: graph reads first
(weakest-first concept list), then class misconceptions, then this
student's history on the target concept.

Prompt version bumps from `17ab80b30316` (refactor #2 ship) to
`358613666dbc`. Logfire traces continue to tag every quiz run with the
active version.

## What shipped

- `backend/agents/tools/quiz_history.py` — `read_recent_quiz_attempts`
  pure-async + `_tool` wrapper. Returns `QuizHistory(summary,
  recent_attempts)`:
  - `summary` is the LLM-generated digest from `quiz_context`
    (the rolling per-(user, concept) notes service —
    `_coerce_summary` accepts the legacy string shape, the
    `{summary: ...}` dict shape, and the `{misconceptions, weak_areas}`
    fallback shape, so prompt-version drift on the post-submit
    background job doesn't break this read).
  - `recent_attempts` is the last 5 *completed* `quiz_attempts` rows
    (newest first), with `accuracy = score/total` precomputed.
    `completed_at = NOT NULL` filter excludes the in-flight row that
    `routes/quiz.py:generate_quiz` writes before submission.
- `backend/agents/quiz.py` — registers the new tool, expands the
  system prompt with explicit spaced-repetition + adaptive-difficulty
  rules. Concept-selection rules now combine three signals (mastery,
  staleness, recent accuracy); difficulty rules are bounded to one
  step in either direction so the agent can't override the user's
  requested difficulty by more than that.
- `backend/routes/quiz.py` — `_quiz_via_agent` user message now nudges
  the agent to call the new tool with the target concept_node_id.
  No wire-format change.
- `backend/tests/test_quiz_history_tool.py` — pins shape coercion,
  accuracy math, the `completed_at IS NOT NULL` filter, and the
  silent-degrade-on-DB-error contract (failures must not propagate;
  the agent can still generate a quiz without history, just less
  adaptive).
- `backend/tests/test_quiz_agent_imports.py` — extended to assert the
  new tool is registered.

## Why this isn't a fourth refactor

The refactor #2 plan in ADR 0005 explicitly carved out a path for
"adaptive quiz history" as a future iteration on the same agent —
not a separate refactor. This ships under that carve-out:

- No new agent. `quiz_agent` gains one tool and a longer prompt.
- No new route. `_quiz_via_agent`'s user message is the only change
  on the route side.
- No wire-format change. `_agent_question_to_wire` is untouched, so
  `submitQuiz` / `scoreQuiz` flows on the frontend are unaffected.
- No fallback-contract change. The legacy `_legacy_generate_quiz`
  path already reads `quiz_context_service`, so its behavior is
  unchanged.

If the agent's adaptive behavior turns out to be wrong (too
aggressive, ignores the rules, etc.), rollback is one tool removal +
one prompt revert.

## What we deliberately didn't do

- **Decay-formula spaced repetition.** The prompt uses "older than
  ~7 days" as a soft signal rather than a Leitner / SM-2 style
  formula. We don't have enough data yet to tune a curve, and the
  agent's "stale concepts get revived" intent is the load-bearing
  property — the exact threshold can move.
- **Cross-concept session history.** The new tool scopes to one
  `concept_node_id` (the target). A future iteration could surface
  cross-concept patterns ("student keeps confusing recursion with
  iteration") — but that needs a new aggregation layer, not just a
  read.
- **Tool consolidation.** We considered merging `read_concepts_for_user`
  + `read_recent_quiz_attempts` into one fat tool. Kept them split:
  the concept list is course-wide (one call covers the whole quiz),
  history is concept-scoped (one call per target). Different shapes,
  different cardinalities — splitting keeps each tool's contract
  small and testable.

## Eval coverage

The existing replay-mode eval set in `tests/evals/quiz_generation.py`
exercises the agent end-to-end. Adaptive-difficulty + spaced-
repetition behaviors are inherently prompt-driven (the LLM decides
how aggressively to apply them), so unit tests pin only the tool's
I/O contract. Live-mode evals (run with `SAPLING_EVAL_MODE=live`) are
the right place to catch prompt regressions — the unit tests don't
try.

## Rollback

Single-revert clean: revert the commit and the new tool import +
registration disappear, the prompt reverts to `17ab80b30316`, and the
route's user message reverts to the refactor-#2 wording. The
`quiz_history.py` file is new and pure-leaf (no other module imports
it), so its presence after rollback is harmless even if the revert
isn't perfectly clean.
