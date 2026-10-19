# ADR 0038: Recover an explicit grade without a second assessment

Status: implemented; release acceptance remains subject to the actual database,
browser, migration and pilot gates in the engineering-readiness record.

## Problem

A grader could finish and flush evidence before the session's observation CAS
was acknowledged. A crash at that boundary stranded the original result; the
old stale-claim rule eventually skipped it. Regrading would risk double BKT,
memory and diagnostic credit. Ending through the legacy route could also set
`ended_at` after a close rejected an in-flight grade.

## Decision

For actual check/probe submissions, bind the grading claim UUID to the Evidence
operation and freeze the trusted observation time. After the final help-floor
read, persist an authenticated encrypted checkpoint before dispatching its
Evidence transaction. It contains the original submitted answer, exact typed
Evidence and code-side continuation, not the course rubric or reference answer.
The envelope binds user, session, course, question, kind, goal revision and
operation. Validation canonicalizes Evidence and rejects unexpected nested
continuation fields. Invalid ciphertext has no plaintext or partial fallback;
errors do not expose the private validation input.

An acknowledged checkpoint remains pending across worker loss, lease age and
question withdrawal. Explicit retry restores that same operation; a changed
request body cannot replace or regrade it. Before writing Evidence, a conditional
session CAS verifies current claim, phase, goal and `ended_at`/`close_json` fences.
Atomic operation receipts then reconcile ambiguous acknowledgments. Only the
original claim may materialize the session continuation, attempt counters and
diagnosis. It removes its checkpoint in that same CAS. A lost final ACK therefore
cannot admit another grade.

The server returns only `pending_grade: {kind, question_hash}` to the browser.
The accessible recovery action posts to the existing explicit answer endpoint;
it does not replay automatically. Normal teaching, goal changes, question
activation and close cannot abandon the pending result. Late tutor completion
is fenced as well as new requests. The legacy end route propagates a busy close
and defers an unacknowledged close instead of writing `ended_at` or awarding XP.

## Authoritative observation and chronology

The original grader result is frozen, while exposure provenance is finalized
under the Evidence writer's owner serialization. A second session may have seen
the same question meanwhile. Session diagnosis and goal observations therefore
use the receipt's final canonical observation, not the checkpoint's optimistic
`previously_seen`/`independent` flags. Receipt posteriors identify the committed
operation's result, not a later read of another session's state.

An uncommitted old observation cannot be applied after newer direct or
propagated Evidence touched its target. A known superseded result retires the
pose without fabricating a diagnostic observation; the student can request a
fresh check. Completed receipts still replay before this ordering fence.
Legacy uncheckpointed callers retain commit-order semantics; no missing history
is invented or backfilled as independent evidence.

## Scope and remaining operational limits

This makes the assessed Evidence batch atomic and the session continuation
recoverable; it does not put transcript writes, optional misconception rollups,
model billing or the entire application in one database transaction. A lost ACK
after the final session save can omit an optional rollup; it cannot duplicate
the authoritative assessment. Corrupt checkpoints fail closed and need an
authorized repair, rather than silent deletion or a second grader call.

New browser/DB tests must exercise cold-worker recovery before and after actual
Evidence commit, pending-state withdrawal and close, duplicate retry, final
canonical exposure and mobile interaction. Hermetic tests alone do not prove
these deployment boundaries. Human rubric review and learning efficacy remain
separate from engineering correctness.
