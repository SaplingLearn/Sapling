# 0035 — Durable planning observations across learning sessions

Date: 2026-10-18
Status: Accepted for PR #673; existing production release gates remain in force.

## Context

ADR 0034 added conservative planning needs for valid failed practice, including
helped and release-recheck failures. A reproduced case starts at a 0.999 prior;
two wrong H2 checks leave the weighted BKT estimate near 0.9626, above the 0.95
readiness threshold. Current-session metadata blocks the prerequisite correctly,
but starting a new session previously discarded that local need and could offer
its dependent again. A due review does not make a simultaneous dependent ready.

Existing evidence journal rows lack the difficulty, repeated-item and synthetic
outcome provenance needed to reconstruct independent recovery safely. The journal
also has a legacy best-effort insertion policy after learner-state updates. A
read-only history adapter cannot recover a planning event that was never stored.

## Decision

- Add nullable `planning_observation` metadata to the existing append-only
  `node_mastery_events` journal through a new migration. Store strictly typed
  concept/question identities, difficulty and outcome/help provenance, never
  learner answers, references, goal prose or tutor messages.
- Attach provenance only to actual graded loop probe/check evidence. Reconcile
  it with the final canonical evidence after help-floor and duplicate/recheck
  adjustments. Neither an incomplete grade nor a client claim creates recovery
  evidence. Other evidence paths without this provenance remain unknown.
- For provenance-tagged grades, require a durable journal append before changing
  learner state or graph mastery. Retry the same event identity within the
  existing bounded insertion policy; never drop the new column as an optional
  compatibility fallback. A journal failure aborts this path instead of silently
  losing a prerequisite block. Untagged legacy paths retain their current policy.
- Read the user's journal in stable chronological order through the sanctioned
  database adapter, paging the complete result. Deduplicate first exposure across
  all owned evidence hashes before projecting the current course and concepts.
  A legacy/invalid first exposure still prevents a later replay from becoming
  fresh independent recovery. The canonical journal is the sole planning
  authority: a current-session snapshot cannot upgrade unknown/missing durable
  provenance or place an undated old failure after a newer durable recovery.
- Carry valid unresolved failures into later goal sessions. A later distinct,
  independent correct answer at the same or higher difficulty can clear the
  corresponding local planning need. Helped, repeated, easier, synthetic and
  unavailable outcomes cannot manufacture independent recovery. Do not change
  BKT mathematics, proficiency thresholds, help gates or historical records.
- Fail closed with a retryable error when durable goal-planning history cannot
  be read. Do not silently fall back to an old high posterior. Apply the migration
  before deploying code that writes this metadata.

## Consequences and limits

The journal append and subsequent learner/graph updates remain separate adapter
operations. This ordering protects the planning record; it does not create a
multi-table transaction. A failure after journal insertion remains an operational
partial-write failure requiring the existing recovery and integrity checks. The
journal may already contain the actual graded outcome even when a later state
write fails; a low posterior still prevents dependent readiness.

Historical NULL provenance is not backfilled or relabeled. It cannot be promoted
to planning evidence from weight, rung, a question-bank lookup or an undated
session snapshot. The durable failure/recovery guarantee applies to newly tagged
grades; this does not retrospectively certify legacy learning history.
This migration does not validate old grading decisions, generated questions,
difficulty calibration, prerequisite discovery or educational effectiveness.

Validation must cover the reproduced fresh-session unlock, later independent
recovery, replay/assistance/unknown exclusions, cross-user/course isolation,
paging, unavailable history, strict journal failures and a real-database
write/read round trip. Browser verification must use the resulting final source
version. Production launch and real-learner outcome requirements remain separate.
