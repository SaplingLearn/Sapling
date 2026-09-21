# Durable, observable document indexing (#482)

**Date:** 2026-09-21
**Issue:** #482 — RAG hardening: silent-empty observability, poisoned `embedding:None` rows,
durability inversion
**Sprint:** 13 — RAG privacy + correctness (AI redesign #643, phases 0–1)

## Scope correction: most of #482 as written is already done

The issue text dates from the #323 audit and was re-scoped on 2026-09-19, before phase 1 landed.
Verified against `origin/main` @ `6d0b80ca`:

| #482 item | State on main |
|---|---|
| Item 1 — silent-empty `print` in `retrieve_chunks` | **Done** (#501): module logger + `rag.retrieval_failed` / `rag.chunks_dropped` |
| Item 2 — failed batch upserted with `embedding: None` | **Done**: `rag_service` filters `embedding is not None` before upsert |
| `time.sleep(1.5)` inside the relevance gate | **Gone** (#644) |
| Logscan allowlist hides real indexing failures | **Gone** (#644) — `ALLOWLIST` is `()` with a comment forbidding re-adding |
| Function mode raises inside the indexer on purpose | **Gone** (#644) — `rag_service` owns the seam rule, quiet skip |

What remains is item 3, the durability inversion, plus the gaps found while verifying it. That is
this spec.

## What is actually broken

1. **No indexing status exists.** `index_status` has zero matches in `backend/`. A failed index is
   invisible: the user sees a successful upload and the document is simply absent from retrieval.
2. **Indexing is fire-and-forget.** `_spawn_post_roll` (`routes/documents.py:1222`) is
   `asyncio.create_task(asyncio.to_thread(fn, *args))`, and `_index_document_chunks` wraps its whole
   body in `except Exception: logger.exception(...)` (`:1218`). No retry, no backoff, no record.
3. **`/upload/sync` never indexes.** Its background tasks (`:716–718`) are study-guide cache, course
   context and achievements only. Gradebook syllabus uploads go through that route, so they never
   reach RAG at all.
4. **`extracted_text` is written inside the indexer** (`:1176`), not in `_persist_document`. The
   recovery path therefore depends on the thing that failed: if indexing never ran, a backfill has
   nothing to work from.
5. **`scripts/backfill_document_chunks.py` is invoked by nothing.** Confirmed; three separate
   comments in the codebase say so. Its `_already_indexed(doc_id)` is also unreliable, because on
   shared rows `doc_id` names only the last writer (#629).

## Decisions taken

**D1 — Durability comes from the status column, not DBOS.** `services/durable.py:87` defaults
`DBOS_ENABLED` to false and ADR 0011 states it "stays off in every deployed environment" pending a
real production incident. Building this on a DBOS workflow would buy nothing in production.
`documents.index_status` is the work queue; a sweeper drains it. DBOS remains untouched and
orthogonal.

**D2 — A periodic sweeper plus an admin re-index endpoint drain the queue.** A queue nothing drains
is precisely today's bug. The claim is an atomic `UPDATE ... RETURNING` behind a SQL function, so it
stays correct if Railway ever runs more than one instance.

**D3 — Existing rows get a derived status, once.** Truthfully, from what is actually in
`course_chunks`, rather than defaulting everything to `pending` and re-embedding work that is
already done. Re-running the classifier on already-indexed documents would also re-decide #630's
shareability with a non-deterministic model, which is not a thing to do casually.

**D4 (amendment, found during design) — the classifier's confidence must be persisted.**
`_persist_document` stores `shareability` (#630) but *not* `confidence`, and
`chunk_visibility.decide_visibility(user_id, shareability=..., confidence=...)` treats a missing
confidence as private. A re-drive that cannot read the original confidence would therefore silently
privatise a document that was correctly shared — the same shape of silent corpus loss as #628 and
#630, arriving through the recovery path this issue adds. The migration adds
`shareability_confidence`.

**D5 (amendment) — `_missing_column`'s retry must become a bounded loop.** The ship-code-before-
migration escape hatch at `routes/documents.py:398` strips exactly ONE column named by the PostgREST
error body and retries once. This migration adds several columns to the insert row; with more than
one absent, the single retry fails and every upload fails in exactly the window the hatch exists to
cover. Loop it, dropping each named column in turn, bounded by the number of droppable columns.
This is a targeted fix to code this change touches, not unrelated refactoring.

## Design

### 1. One indexing entry point, in a service

`_index_document_chunks` moves out of `routes/documents.py` into **`services/document_indexing.py`**:

```python
def index_document(doc_id: str, *, force: bool = False) -> IndexOutcome
```

It reads what it needs off the `documents` row rather than taking eight positional arguments — which
is what lets a sweeper re-drive the identical work three days later. Four callers share it: the
streaming post-roll, `/upload/sync`, the sweeper, and the admin endpoint.
`scripts/backfill_document_chunks.py` becomes a thin caller and loses its own unreliable
`_already_indexed`.

Everything it needs is reconstructible from the row:

| Input | Source |
|---|---|
| course code | `offering_id` → `services/academics.py::offering_course_id` → `courses.course_code` |
| `category` | `documents.category` |
| `shareability` | `documents.shareability` (#630) |
| `confidence` | `documents.shareability_confidence` — **new, D4** |
| `extracted_text` | `documents.extracted_text`, `decrypt_if_present` — **moved, see 2** |
| `doc_summary` | `documents.summary`, `decrypt_if_present` |
| `user_id` | `documents.user_id` |

Course resolution goes through `services/academics.py`, per CLAUDE.md; this layer never re-derives
term/offering mapping itself.

### 2. `extracted_text` moves to `_persist_document`

The single highest-value line of the change. `_persist_document` (`:432`) already receives the text
— it computes `char_count=len(extracted_text)` — so it writes it at insert time with
`encrypt_if_present`, and the indexer stops writing it. `index_document` reads it back with
`decrypt_if_present`. After this, a document that was never indexed is still fully recoverable.

### 3. Schema — one timestamp-prefixed migration

`CHECK`-constrained in the style of #629/#630:

| column | type | purpose |
|---|---|---|
| `index_status` | text | `pending` ¦ `indexing` ¦ `indexed` ¦ `partial` ¦ `failed` ¦ `skipped` |
| `index_attempts` | int, default 0 | bounded retry budget |
| `index_leased_at` | timestamptz | the sweeper's claim lease |
| `index_chunk_count` | int | #482's chunk count; feeds #645's coverage metric |
| `index_error` | text | last failure, **error class only — never user content** |
| `shareability_confidence` | real, `CHECK 0..1` | D4 |

`ADD COLUMN index_status ... DEFAULT 'skipped'` deliberately: the state between the migration
landing and the derivation backfill running must be **inert**, so the sweeper cannot grab a
historical row before anything has told the truth about it. The application sets `'pending'`
explicitly on insert.

#### State machine — explicit, because three callers drive it

`index_document` owns every transition; no caller writes `index_status` directly.

```
                 (upload persists row)
                          |
                          v
      skipped <--- not real model mode ---  pending
        ^                                     |
        | (#439 gate)                    claim / inline attempt
        |                                     v
        +--------------------------------  indexing
                                              |
             +--------------+-----------------+--------------+
             v              v                 v              v
          indexed        partial            failed        (crash)
        all chunks    some dropped      attempts >= MAX      |
             |              |                 |         lease expires
             |              +--------+--------+              |
             |                       v                       |
             +----------------> re-claimable <---------------+
                        (pending | partial | failed & attempts < MAX)
```

The sweeper claims `pending`, `partial` **and** `failed` while `index_attempts < MAX` — `partial`
is retried because dropped chunks are exactly the recoverable case. `indexed` and `skipped` are
never claimed. `indexing` is claimable only once its lease has expired.

**Concrete defaults** (env-overridable): sweep interval 300s, batch size 10, `MAX` attempts 3,
lease 600s, inline: 3 tries sleeping 1s then 4s between them.

**Every attempt is exactly one claim and one increment.** The sweeper claims in batches through
the SQL function; the upload paths and the admin endpoint claim their single row with a
conditional `PATCH ... WHERE index_status IN (pending, partial, failed)`. Both increment
`index_attempts`, so a document that crashes the worker is bounded to `MAX` attempts rather than
retried forever, and whichever caller flips a row to `indexing` first wins — the loser does nothing.
Fresh `pending` rows get a two-minute grace from the sweeper so it does not contend with the
upload's own inline attempt; correctness rests on the conditional claim, not on the grace.

**`force=True`** (the admin endpoint only) resets `index_attempts` to 0 and re-drives regardless of
current status, including `indexed`. It is the one path that can re-index an already-indexed
document, and it exists so an operator can recover from a bad decision without hand-editing rows.

`partial` is a real state rather than a rounding of `failed`: `rag_service` already drops chunks
whose embedding failed and emits `rag.chunks_dropped`, so "some chunks landed" is a condition that
exists today and is currently invisible.

### 4. The sweeper

A SQL function `claim_documents_for_indexing(max_attempts, lease_seconds, batch_size)` performs the
atomic `UPDATE ... RETURNING`, `REVOKE`d from `PUBLIC`/`anon`/`authenticated` and `GRANT`ed to
`service_role` — the shape `canopy_metrics()` established. It is an RPC rather than a PostgREST
PATCH because the lease cutoff is a `now() - interval` comparison and because the claim must be
atomic under more than one instance.

An asyncio task on the existing `main.py:89` `_lifespan` sweeps on an interval, alongside
`events_service.start_worker()`, and is torn down beside `events_service.shutdown()`.

Two gates: it does nothing outside real model mode (#439 — so function-mode E2E never sweeps), and
an env kill-switch. It is **on by default in real mode**; defaulting it off would repeat the fate of
the DBOS path this issue is about.

`POST /api/admin/documents/{id}/reindex` forces one document and `GET /api/admin/documents/unindexed`
is the "visible to admins" surface, both behind `require_admin` (`services/auth_guard.py:68`).
**Backend JSON only — no frontend in this issue.**

### 5. Retry, and what counts as transient

**Retry is driven by the count, not by exceptions** — corrected during implementation.
`rag_service.index_document_chunks` swallows embed failures per batch and returns a lower count, so
a transient Gemini 503 arrives as a *short count* and never as an exception; retry-on-exception
would never have fired for the most common failure. It also returns 0 both when the #439 seam
disabled embedding and when every embed failed. A new `index_document_chunks_detailed` returns
`(upserted, total, embedding_disabled, embed_error)`; the count-only form stays for callers that
just log it.

Exceptions that do escape — the upsert and the contributor-ledger write — are retried only when
transient: an `httpx.TransportError`, or a PostgREST 429 / 5xx. A `TypeError` like #628, or a 400
from a constraint, is a bug and fails on the first attempt rather than being retried into a rate
limit. New event types are registered in the pinned #117 taxonomy —
CLAUDE.md is explicit that `log_event` does not enforce membership, so an unregistered type is
simply invisible, which is how #501's first draft nearly shipped blind.

### 6. Derivation backfill

`scripts/backfill_document_index_status.py`, idempotent, `--apply`:

- chunks exist for `doc_id` → `indexed`, with `index_chunk_count`
- `extracted_text` present, no chunks → `pending` (the sweeper picks it up)
- no `extracted_text` → `failed`, `index_attempts` at max, so it is visible as unrecoverable and
  never retried

Prod lands 5 `indexed` / 0 `pending` / 2 `failed`. No embedding spend, no re-classification.

## Out of scope

- Any frontend surface for index status.
- Turning DBOS on, or changing ADR 0011's streaming-route asymmetry.
- Seeding the corpus — that is #645, in the same sprint.
- Re-enabling the relevance gate as a gate; #644 made it observe-only on measured evidence.

**Historical rows index private on a re-drive.** They have no stored confidence, and
`index_document` passes `None` rather than inventing one — CLAUDE.md's rule for every unknown
answer. This deliberately differs from `scripts/backfill_document_chunks.py`, which passed
`confidence=1.0` whenever a shareability was stored, on the premise that a stored decision had
already been gated. It had not: `_persist_document` stores the classifier's raw label and the 0.6
floor is applied only at index time, so that script would re-index a low-confidence document
**shared** that the live path had kept private. Task 8 routes the script through `index_document`,
which closes that. Derived-`indexed` rows are never re-driven automatically, so this bites only on an
explicit forced re-index.

## Risks

- **A re-drive re-decides privacy.** Mitigated by D4 plus reading the stored `shareability`; the
  classifier is never re-run on a re-drive.
- **Sweeper stampede after a long outage.** Mitigated by `batch_size` and `index_attempts`.
- **The lease leaks on a hard crash** (`indexing` forever). Mitigated by the lease cutoff: an
  `indexing` row older than `lease_seconds` is reclaimable.

## Testing

TDD throughout. Acceptance criteria map to tests:

- a simulated embed failure retries and ends `indexed`
- a permanent failure ends `failed` and appears in the admin list
- two concurrent claims never double-drive the same row
- `/upload/sync` uploads are indexed
- a document whose indexer never ran still has `extracted_text` to recover from
- function mode ends `skipped`, logs no traceback, and the logscan `ALLOWLIST` stays empty
- `_missing_column`'s retry survives two absent columns (D5)

Then the full gate: hermetic suite, `ruff check .`, migration replay from empty, Chapter 1
Playwright, and the oracles — the whole up→test→down cycle under one `flock` on
`/tmp/claude-1000/sapling-e2e-stack.lock`.
