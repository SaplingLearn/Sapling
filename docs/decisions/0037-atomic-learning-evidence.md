# 0037 — Atomic learning evidence and operation receipts

Date: 2026-10-19
Status: Accepted for PR #673; production promotion remains separately gated.

## Context

ADR 0035 made a tagged journal append mandatory before scalar learning updates,
but the append, learner state, graph mirror and prerequisite propagation were
separate writes. A later failure could leave a partial update. Two workers could
also calculate from the same posterior and overwrite one another. Keeping the
older unconditional writer for untagged quiz/review evidence would preserve that
race across the two paths.

## Decision

- Route every `Evidence` batch through the same transactional writer. Preserve
  the existing Python BKT, FSRS, weighting, counter and propagation calculations;
  SQL does not implement a second learning model. Untagged historical, quiz,
  review and posttest provenance remains NULL/unknown.
- Read an owner/course-scoped snapshot containing affected graph nodes, learner
  rows, prerequisite edges and prior same-session hash exposures. Return these
  as native JSON aggregates so PostgREST's row-response limit cannot truncate a
  large adjacency. Python prepares final learner rows, mirrors and ordered
  journal records without writing any of them.
- Commit the complete plan with `db.connection.rpc`. Under an owner advisory
  mutex, take a short SHARE lock on `graph_edges` before deterministic graph and
  learner row locks. This blocks legacy topology inserts, edits and deletes,
  including phantom edges, while comparing the exact prerequisite snapshot.
  Check database-maintained row versions and hash exposure counts before writes.
  Hash exposure is also owner-global across sessions/courses: a concurrent
  earlier event, including NULL-provenance history, prevents a second session
  from labelling the same question as an independent first exposure. This
  provenance reconciliation does not change the separate same-session BKT
  recheck weighting policy.
  Version triggers also detect concurrent metadata and derived-metric updates;
  evidence upserts never overwrite derived metric columns.
- One database transaction appends the evidence journal, writes learner state,
  updates graph mirrors/one-hop propagation and stores an immutable operation
  receipt. Any exception rolls back all those effects. No missing-migration
  downgrade, dropped journal, or unconditional scalar fallback remains on the
  evidence path.
- Bind an explicit trusted operation UUID to ordered semantic input, owner,
  course and retention settings. Event IDs are deterministic within that batch.
  Retrying a committed operation returns its original changes and posteriors;
  receipts also contain the ordered final typed planning observations from
  committed events, rather than caller-snapshotted independence flags.
  it never recalculates from a newer state. Reusing an identity with different
  input or a different prepared plan is a conflict. Distinct legitimate rechecks
  retain distinct operation identities and their conservative evidence weight.
- After an ambiguous acknowledgment, retry the identical operation and plan
  before rebuilding anything. Reconcile an immutable receipt if communication
  remains uncertain; a failed receipt read is not 'no evidence'. Explicit CAS,
  serialization, deadlock and lock-timeout rollbacks admit bounded fresh-snapshot
  retries. The coarse topology lock has a two-second lock timeout and ten-second
  statement timeout; it is a correctness choice with a contention cost, not an
  unlimited scalability claim.
- A checkpoint can freeze trusted `observed_at`. An uncommitted older operation
  is rejected when a touched state already contains later evidence. An
  evidence-only `evidence_touch_at` records direct and propagated updates even
  when propagation preserves `last_evidence_at` as a decay anchor; metrics
  writes do not move this fence. Legacy NULL touch times remain unknown, with
  no historical backfill or inference from general `updated_at`. It must not
  reappear as a new failure after newer recovery. An already committed receipt
  still replays before that ordering check. Compatibility callers without a
  timestamp use commit-order semantics; callers without an operation UUID get
  an invocation-local UUID, not a cross-request idempotency guarantee.
- Keep topology-only behavior. Reject tagged evidence mixed with topology
  mutations before any write. Existing untagged mixed payloads can create
  topology first and then commit evidence atomically: that earlier topology
  operation is not part of the evidence transaction.

## Consequences and limits

Apply the migration before serving the new writer. The RPCs and receipt table
are backend/service-role only, with ownership/course validation and no browser
role grants. The protocol carries IDs, typed outcome/provenance flags, numeric
state and concept metadata, never learner answers or assessment references.

This transaction ends at evidence/state/graph/receipt persistence. Session grade
checkpoint finalization, transcripts, close records, analytics caches and
achievements are separate operations. A durable session checkpoint can use the
receipt to finish without grading again; that route bridge requires its own
verification. An unknown acknowledgment is an explicit operational uncertainty,
not permission to invent learner evidence or reset history.

Hermetic transport tests do not establish PostgreSQL lock/rollback behavior;
the isolated real-database integration gate is required. Engineering integrity
does not validate item rubrics, diagnostic calibration or learning efficacy.

## Forward-only migration repair

The original `20261019131339_learning_evidence_transaction.sql` remains byte-for-byte immutable. Apply `20261019141950_learning_evidence_forward_repair.sql` before deploying the final writer/checkpoint consumers. It adds nullable evidence-only chronology and replaces the RPC definitions for strict whole-operation receipts and global exposure reconciliation; it does not recreate triggers/tables, delete events or backfill legacy provenance.
