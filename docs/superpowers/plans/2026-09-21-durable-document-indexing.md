# Durable, Observable Document Indexing (#482) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make document indexing recoverable and visible — a failed or crashed index leaves a truthful status that a sweeper re-drives, instead of a healthy-looking `documents` row whose content is permanently absent from retrieval.

**Architecture:** `documents.index_status` becomes the work queue. One shared entry point, `services/document_indexing.py::index_document(doc_id)`, owns every status transition and is called by four callers (streaming post-roll, `/upload/sync`, a lifespan sweeper, an admin endpoint). The sweeper claims rows through an atomic SQL function so the design survives more than one instance. DBOS is untouched — ADR 0011 keeps it off in every deployed environment, so it cannot be the durability mechanism.

**Tech Stack:** FastAPI, Supabase/PostgREST via `db/connection.py`, Pydantic AI agents, pytest with mocked Supabase, raw-DDL migrations via `python -m db.migrate`.

**Spec:** `docs/superpowers/specs/2026-09-21-durable-document-indexing-design.md`

## Global Constraints

- All Supabase access goes through `db/connection.py::table()` / `rpc()`. No `httpx` clients, no `supabase` import.
- Schema changes are append-only migrations in `backend/db/migrations/`, UTC-timestamp-prefixed (`date -u +%Y%m%d%H%M%S`). Never edit an applied migration.
- `documents.extracted_text` and `documents.summary` are encrypted columns: `encrypt_if_present` at write, `decrypt_if_present` at read (including before prompts).
- Course resolution goes through `services/academics.py`; the HTTP boundary keeps the abstract `course_id`.
- New event types MUST be registered in the pinned #117 taxonomy in `services/events_service.py` — `log_event` does not enforce membership, so an unregistered type is silently invisible.
- Code below `agents/_providers.py` must never construct a raw `google.genai.Client` without a `model_mode()` gate (#439).
- `functools.lru_cache` only for deterministic per-process reads with an invalidation story (#98).
- The logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` MUST stay `()`. If function mode would log a traceback, make it stop logging one — never allowlist it.
- Status enum, verbatim: `pending`, `indexing`, `indexed`, `partial`, `failed`, `skipped`.
- Defaults, verbatim: sweep interval 300s, batch size 10, MAX attempts 3, lease 600s, inline backoff 3 tries at 1s/4s/16s.
- Run backend commands from `backend/` using the primary checkout's `venv`.

---

### Task 1: Migration — index columns, confidence, and the atomic claim function

**Files:**
- Create: `backend/db/migrations/<UTC>_document_index_status.sql`
- Test: `backend/tests/test_document_index_status_migration.py`

**Interfaces:**
- Consumes: nothing.
- Produces: columns `documents.index_status`, `index_attempts`, `index_leased_at`, `index_chunk_count`, `index_error`, `shareability_confidence`; SQL function `claim_documents_for_indexing(max_attempts int, lease_seconds int, batch_size int) RETURNS TABLE (id uuid)`.

- [ ] **Step 1: Write the failing test**

The migration is DDL, so the hermetic test asserts the *invariants the rest of the plan depends on* are present in the file — the live schema is proven by migration replay from empty in the E2E gate (Task 9).

```python
"""The #482 migration's invariants. The live schema is proven by migration
replay from empty in the E2E lane; this guards the properties that a later
edit could silently drop."""
import pathlib
import re

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_document_index_status.sql"))
    assert len(hits) == 1, f"expected exactly one index-status migration, got {hits}"
    return hits[0].read_text()


def test_every_status_value_is_in_the_check_constraint():
    sql = _migration()
    for value in ("pending", "indexing", "indexed", "partial", "failed", "skipped"):
        assert f"'{value}'" in sql, f"{value} missing from the migration"


def test_new_columns_default_to_an_inert_state():
    # 'skipped' deliberately: between this migration and the derivation
    # backfill, the sweeper must not claim a historical row.
    sql = _migration()
    assert re.search(r"index_status\s+text\s+NOT NULL\s+DEFAULT\s+'skipped'", sql)


def test_claim_function_is_not_exposed_to_the_anon_key():
    # PostgREST would otherwise expose it to the anon key the frontend ships.
    sql = _migration()
    assert "REVOKE ALL ON FUNCTION claim_documents_for_indexing" in sql
    assert "GRANT EXECUTE ON FUNCTION claim_documents_for_indexing" in sql
    assert "service_role" in sql


def test_claim_is_atomic_and_skips_locked_rows():
    sql = _migration()
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "RETURNING" in sql


def test_confidence_is_range_checked():
    sql = _migration()
    assert "shareability_confidence" in sql
    assert re.search(r"shareability_confidence\s*>=\s*0", sql)
    assert re.search(r"shareability_confidence\s*<=\s*1", sql)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_document_index_status_migration.py -v`
Expected: FAIL — `expected exactly one index-status migration, got []`

- [ ] **Step 3: Write the migration**

Generate the prefix with `date -u +%Y%m%d%H%M%S`. Model the REVOKE/GRANT block on `20260921041555_canopy_active_users.sql`.

```sql
-- #482: documents.index_status is the indexing work queue.
--
-- Durability deliberately does NOT come from DBOS here. ADR 0011 keeps
-- DBOS_ENABLED off in every deployed environment pending a real production
-- incident, so a DBOS workflow would buy nothing in production. The status
-- column plus a sweeper works with DBOS off, which is where we actually are.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS index_status  text NOT NULL DEFAULT 'skipped',
    ADD COLUMN IF NOT EXISTS index_attempts int NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS index_leased_at timestamptz,
    ADD COLUMN IF NOT EXISTS index_chunk_count int,
    ADD COLUMN IF NOT EXISTS index_error text,
    -- #630 stored `shareability` but not the confidence it was judged at, and
    -- decide_visibility() reads a missing confidence as PRIVATE. Without this
    -- column a re-drive silently privatises a correctly shared document —
    -- the same silent corpus loss as #628, arriving through the recovery path.
    ADD COLUMN IF NOT EXISTS shareability_confidence real;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'documents_index_status_check'
    ) THEN
        ALTER TABLE documents ADD CONSTRAINT documents_index_status_check
            CHECK (index_status IN
                ('pending','indexing','indexed','partial','failed','skipped'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'documents_shareability_confidence_check'
    ) THEN
        ALTER TABLE documents ADD CONSTRAINT documents_shareability_confidence_check
            CHECK (shareability_confidence IS NULL
                   OR (shareability_confidence >= 0.0
                       AND shareability_confidence <= 1.0));
    END IF;
END $$;

-- The sweeper only ever reads rows that are not finished.
CREATE INDEX IF NOT EXISTS idx_documents_index_queue
    ON documents (index_status, index_attempts)
    WHERE index_status <> 'indexed';

-- Atomic claim. An UPDATE ... RETURNING behind SKIP LOCKED, so two instances
-- can never drive the same document, and a lease that has expired is
-- reclaimable (a hard crash would otherwise strand a row in 'indexing').
CREATE OR REPLACE FUNCTION claim_documents_for_indexing(
    max_attempts  int,
    lease_seconds int,
    batch_size    int
)
RETURNS TABLE (id uuid)
LANGUAGE sql
VOLATILE
AS $$
    UPDATE documents d
       SET index_status   = 'indexing',
           index_leased_at = now(),
           index_attempts  = d.index_attempts + 1
     WHERE d.id IN (
         SELECT c.id
           FROM documents c
          WHERE c.deleted_at IS NULL
            AND c.index_attempts < max_attempts
            AND (
                    -- A fresh 'pending' row belongs to the upload's own inline
                    -- attempt for its first two minutes; claiming it sooner just
                    -- contends with the post-roll (correctness does not depend on
                    -- this -- the inline path's conditional claim does -- it only
                    -- avoids wasted work).
                    (c.index_status = 'pending'
                     AND c.created_at < now() - interval '2 minutes')
                 OR c.index_status IN ('partial', 'failed')
                 OR (c.index_status = 'indexing'
                     AND c.index_leased_at
                         < now() - make_interval(secs => lease_seconds))
                )
          ORDER BY c.index_leased_at NULLS FIRST, c.created_at
          LIMIT batch_size
          FOR UPDATE SKIP LOCKED
     )
 RETURNING d.id;
$$;

REVOKE ALL ON FUNCTION claim_documents_for_indexing(int, int, int) FROM PUBLIC;
DO $$
DECLARE r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format(
                'REVOKE ALL ON FUNCTION claim_documents_for_indexing(int,int,int) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION claim_documents_for_indexing(int,int,int) TO service_role;
    END IF;
END $$;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && venv/bin/python -m pytest tests/test_document_index_status_migration.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/db/migrations/*_document_index_status.sql backend/tests/test_document_index_status_migration.py
git commit -m "feat(482): documents.index_status schema and the atomic claim function"
```

---

### Task 2: `_missing_column`'s retry must survive more than one absent column

**Files:**
- Modify: `backend/routes/documents.py:398` (`_missing_column`), `:480-495` (the retry in `_persist_document`)
- Test: `backend/tests/test_documents_routes.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_persist_document` tolerates N absent droppable columns instead of exactly one.

**Why this task exists:** the hatch drops exactly ONE column named by the PostgREST error body and retries once. Task 3 adds three more columns to that insert. With two absent, the single retry fails and every upload fails — in exactly the window the hatch exists to cover. This is the third bug in this escape hatch (it first shipped reading `str(exc)`, which never matched).

- [ ] **Step 1: Write the failing test**

```python
def test_persist_document_drops_each_absent_column_in_turn(monkeypatch):
    """Two absent columns must not defeat the ship-before-migration hatch."""
    absent = {"shareability_confidence", "index_status"}
    seen_payloads = []

    class _Resp:
        def __init__(self, col):
            self.text = (
                '{"code":"PGRST204","message":'
                f'"Could not find the \'{col}\' column of \'documents\'"}}'
            )

    class _Err(Exception):
        def __init__(self, col):
            super().__init__("Client error '400 Bad Request' for url ...")
            self.response = _Resp(col)

    def fake_insert(row):
        seen_payloads.append(dict(row))
        for col in absent:
            if col in row:
                raise _Err(col)
        return [row]

    # ... wire fake_insert through the documents table mock, then:
    doc_id, full_row = documents._persist_document(
        user_id="u1", offering_id="o1", filename="f.pdf",
        result=_result_fixture(), request_id="req-1",
    )

    assert doc_id
    # request_id must survive: dropping it breaks X-Request-ID replay detection
    # and a client retry would persist a duplicate document.
    assert seen_payloads[-1].get("request_id") == "req-1"
    assert "shareability_confidence" not in seen_payloads[-1]
    assert "index_status" not in seen_payloads[-1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_documents_routes.py -k drops_each_absent -v`
Expected: FAIL — the second `_Err` propagates out of the single retry.

- [ ] **Step 3: Replace the single retry with a bounded loop**

```python
    # Bounded by the number of droppable columns, so a genuinely broken insert
    # still raises instead of looping. Each pass drops only the column the
    # error BODY names -- never a blanket strip, which would take request_id
    # with it and break X-Request-ID replay detection (#132/#154).
    droppable = {"shareability", "request_id", "index_status",
                 "index_attempts", "shareability_confidence", "extracted_text"}
    for _ in range(len(droppable) + 1):
        try:
            inserted = table("documents").insert(row)
            break
        except Exception as exc:
            column = _missing_column(exc)
            if column is None or column not in row:
                raise
            logger.warning(
                "documents insert rejected %r as absent — retrying without it. "
                "The migration that adds it has not run in this environment.",
                column,
            )
            row.pop(column, None)
    else:
        raise RuntimeError("documents insert kept naming absent columns")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && venv/bin/python -m pytest tests/test_documents_routes.py -v`
Expected: PASS, including the pre-existing `TestUploadIdempotency` cases.

- [ ] **Step 5: Commit**

```bash
git add backend/routes/documents.py backend/tests/test_documents_routes.py
git commit -m "fix(482): let the ship-before-migration hatch drop more than one column"
```

---

### Task 3: Persist `extracted_text`, `shareability_confidence`, and `index_status='pending'` at insert

**Files:**
- Modify: `backend/routes/documents.py:432` (`_persist_document`) and both call sites (`:660-715` sync, `:1030-1040` streaming)
- Test: `backend/tests/test_documents_routes.py`

**Interfaces:**
- Consumes: Task 2's looping retry.
- Produces: `_persist_document(..., extracted_text: str | None = None)`; the inserted row carries `extracted_text` (encrypted), `shareability_confidence`, `index_status='pending'`, `index_attempts=0`.

**Why this task exists:** `extracted_text` is written *inside* the indexer today (`:1176`), so the recovery path depends on the thing that failed.

- [ ] **Step 1: Write the failing tests**

```python
def test_persist_document_stores_extracted_text_encrypted():
    """The recovery path must not depend on the indexer having run."""
    doc_id, row = _persist_with(extracted_text="gradient descent notes")
    stored = _last_insert_payload()
    assert stored["extracted_text"] != "gradient descent notes"   # encrypted
    assert decrypt_if_present(stored["extracted_text"]) == "gradient descent notes"


def test_persist_document_stores_the_classifier_confidence():
    """decide_visibility reads a missing confidence as private (#630), so a
    re-drive without this silently privatises a correctly shared document."""
    _persist_with(confidence=0.91)
    assert _last_insert_payload()["shareability_confidence"] == 0.91


def test_persist_document_enqueues_the_row_for_indexing():
    _persist_with()
    payload = _last_insert_payload()
    assert payload["index_status"] == "pending"
    assert payload["index_attempts"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_documents_routes.py -k "extracted_text or confidence or enqueues" -v`
Expected: FAIL — `KeyError: 'extracted_text'`

- [ ] **Step 3: Implement**

Add `extracted_text: str | None = None` to the signature, and to the `row` dict:

```python
        # #482: written HERE, not in the indexer. The indexer used to persist
        # this, which made the recovery path depend on the thing that failed:
        # if indexing never ran, a backfill had nothing to work from.
        "extracted_text": encrypt_if_present(extracted_text),
        "shareability_confidence": getattr(result.classification, "confidence", None),
        "index_status": "pending",
        "index_attempts": 0,
```

Update the docstring (it currently says `char_count` is "not persisted on the row"). Pass `extracted_text=extracted_text` at both call sites.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && venv/bin/python -m pytest tests/test_documents_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routes/documents.py backend/tests/test_documents_routes.py
git commit -m "feat(482): persist extracted_text and the classifier confidence at insert"
```

---

### Task 4: `services/document_indexing.py` — the one entry point

**Files:**
- Create: `backend/services/document_indexing.py`
- Modify: `backend/services/events_service.py` (register event types in the #117 taxonomy)
- Test: `backend/tests/test_document_indexing.py`

**Interfaces:**
- Consumes: Task 1's columns; `rag_service.index_document_chunks(course_code, doc_id, uploader_id, chunks, *, visibility, category)`; `chunk_visibility.decide_visibility(user_id, *, shareability, confidence)`; `academics.offering_course_id(offering_id)`; `chunker.chunk_for_category(text, category)`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class IndexOutcome:
      status: str          # one of the six enum values
      chunk_count: int = 0
      error: str | None = None   # error CLASS name only, never user content

  def index_document(doc_id: str, *, force: bool = False,
                     claimed: bool = False) -> IndexOutcome
  ```
  `claimed=True` means the caller (the sweeper) already claimed the row through
  `claim_documents_for_indexing`, which set `indexing` + lease and incremented
  `index_attempts`. `claimed=False` (the upload paths, the admin endpoint) makes
  `index_document` perform its OWN single-row conditional claim first --
  `PATCH ... WHERE id=X AND index_status IN (pending, partial, failed)` setting
  `indexing`, the lease, and `index_attempts + 1`. **Every attempt is exactly one
  claim and exactly one increment**, whichever caller drove it; that is what
  bounds a worker-crashing document to MAX attempts instead of retrying forever.
  If the conditional claim updates zero rows, another caller won the row and
  `index_document` returns without doing anything.

- [ ] **Step 1: Write the failing tests**

```python
def test_reads_everything_off_the_row(fake_documents_row):
    """A sweeper three days later must reconstruct the same work."""
    out = index_document("doc-1")
    assert out.status == "indexed"
    assert out.chunk_count == 3


def test_transient_embed_failure_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}
    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _TransientGeminiError("503 backend unavailable")
        return 3
    monkeypatch.setattr(rag_service, "index_document_chunks", flaky)
    monkeypatch.setattr(document_indexing, "_BACKOFF_SECONDS", (0, 0, 0))
    out = index_document("doc-1")
    assert out.status == "indexed"
    assert calls["n"] == 3


def test_a_bug_fails_loudly_on_the_first_attempt(monkeypatch):
    """#628 was a TypeError. Retrying a bug three times only burns rate limit."""
    calls = {"n": 0}
    def broken(*a, **kw):
        calls["n"] += 1
        raise TypeError("can't multiply sequence by non-int")
    monkeypatch.setattr(rag_service, "index_document_chunks", broken)
    out = index_document("doc-1")
    assert out.status == "failed"
    assert calls["n"] == 1
    assert out.error == "TypeError"


def test_dropped_chunks_end_partial_not_indexed(monkeypatch):
    monkeypatch.setattr(rag_service, "index_document_chunks", lambda *a, **kw: 2)
    # the row chunks into 3
    out = index_document("doc-1")
    assert out.status == "partial"
    assert out.chunk_count == 2


def test_function_mode_is_a_quiet_skip(monkeypatch, caplog):
    """Acceptance criterion: an explicit designed no-op, never a traceback the
    logscan oracle has to allowlist."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    out = index_document("doc-1")
    assert out.status == "skipped"
    assert "Traceback" not in caplog.text


def test_missing_extracted_text_is_terminal(fake_row_without_text):
    out = index_document("doc-2")
    assert out.status == "failed"
    assert out.error == "no_extracted_text"


def test_confidence_is_read_from_the_row_not_reclassified(monkeypatch):
    """A re-drive must reproduce #630's decision, never re-run the classifier."""
    seen = {}
    monkeypatch.setattr(
        chunk_visibility, "decide_visibility",
        lambda uid, *, shareability, confidence: seen.update(
            shareability=shareability, confidence=confidence) or "shared")
    index_document("doc-1")
    assert seen == {"shareability": "course_material", "confidence": 0.91}


def test_losing_the_conditional_claim_does_nothing(monkeypatch):
    """The inline post-roll and the sweeper can both see a pending row. Whoever
    flips it to 'indexing' first wins; the loser must not index it again."""
    calls = {"n": 0}
    monkeypatch.setattr(document_indexing, "_claim_one", lambda doc_id: False)
    monkeypatch.setattr(rag_service, "index_document_chunks",
                        lambda *a, **kw: calls.__setitem__("n", calls["n"] + 1) or 3)
    out = index_document("doc-1")
    assert calls["n"] == 0
    assert out.status == "indexing"   # someone else holds it


def test_an_inline_attempt_counts_against_the_budget(monkeypatch):
    """A document that crashes the worker must not retry forever: the inline
    attempt increments index_attempts exactly as a sweeper claim would."""
    claimed = []
    monkeypatch.setattr(document_indexing, "_claim_one",
                        lambda doc_id: claimed.append(doc_id) or True)
    index_document("doc-1")
    assert claimed == ["doc-1"]


def test_a_sweeper_claimed_row_is_not_claimed_twice(monkeypatch):
    claimed = []
    monkeypatch.setattr(document_indexing, "_claim_one",
                        lambda doc_id: claimed.append(doc_id) or True)
    index_document("doc-1", claimed=True)
    assert claimed == []


def test_already_indexed_is_a_noop_unless_forced(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(rag_service, "index_document_chunks",
                        lambda *a, **kw: calls.__setitem__("n", calls["n"] + 1) or 3)
    index_document("doc-indexed")
    assert calls["n"] == 0
    index_document("doc-indexed", force=True)
    assert calls["n"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_document_indexing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.document_indexing'`

- [ ] **Step 3: Implement**

Move the body of `routes/documents.py::_index_document_chunks` into the new module, reworked to read off the row and own the transitions. Shape:

```python
_TERMINAL = {"indexed", "skipped"}
_BACKOFF_SECONDS = (1, 4, 16)
_TRANSIENT = ("429", "500", "502", "503", "504", "timeout", "unavailable",
              "deadline", "rate limit")


def _is_transient(exc: Exception) -> bool:
    """Only a transient REMOTE failure is worth retrying. A TypeError is a bug
    (#628 was one) and retrying it three times only burns rate limit."""
    if isinstance(exc, (TypeError, ValueError, KeyError, AttributeError)):
        return False
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _TRANSIENT)


def index_document(doc_id: str, *, force: bool = False) -> IndexOutcome:
    row = _load(doc_id)
    if row is None:
        return _finish(doc_id, IndexOutcome("failed", error="no_such_document"))
    if row.get("index_status") in _TERMINAL and not force:
        return IndexOutcome(row["index_status"], row.get("index_chunk_count") or 0)
    if force:
        _reset_attempts(doc_id)
    if model_mode() != "real":
        # #439/#644: rag_service owns the seam rule and embeds nothing outside
        # real mode. Recording it as a DESIGNED no-op is what keeps the logscan
        # ALLOWLIST empty -- the entry that used to cover this also hid #628.
        return _finish(doc_id, IndexOutcome("skipped"))

    text = decrypt_if_present(row.get("extracted_text"))
    if not text:
        return _finish(doc_id, IndexOutcome("failed", error="no_extracted_text"))
    ...
```

Register the new event types in `services/events_service.py`, both in the docstring table and the pinned tuple:

```
rag.index_failed              error     doc_id, status, error_type, attempts
rag.index_recovered           usage     doc_id, attempts, chunk_count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && venv/bin/python -m pytest tests/test_document_indexing.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/document_indexing.py backend/services/events_service.py backend/tests/test_document_indexing.py
git commit -m "feat(482): one indexing entry point that owns its status transitions"
```

---

### Task 5: Wire both upload routes to the shared entry point

**Files:**
- Modify: `backend/routes/documents.py` — delete `_index_document_chunks` (:1146-1218), change the post-roll tuple (:1044-1049), add the `/upload/sync` background task (:716-718)
- Test: `backend/tests/test_documents_routes.py`

**Interfaces:**
- Consumes: `services.document_indexing.index_document`.
- Produces: both upload routes enqueue indexing.

- [ ] **Step 1: Write the failing tests**

```python
def test_sync_upload_indexes_the_document(client, captured_background_tasks):
    """Gradebook syllabus uploads go through /upload/sync and have never
    reached RAG at all."""
    client.post("/api/documents/upload/sync", files=_a_pdf())
    assert any(t.func is index_document for t in captured_background_tasks)


def test_streaming_upload_still_indexes_via_the_post_roll(monkeypatch):
    seen = []
    monkeypatch.setattr(documents, "index_document", lambda d, **k: seen.append(d))
    _consume_stream(client.post("/api/documents/upload", files=_a_pdf()))
    assert len(seen) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_documents_routes.py -k "sync_upload_indexes or post_roll" -v`
Expected: FAIL — no indexing task on the sync route.

- [ ] **Step 3: Implement**

Post-roll tuple becomes `("index_document", index_document, doc_id)`. Sync route gains `background_tasks.add_task(index_document, doc_id)` after `_persist_document`. Delete the old function and its now-unused imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && venv/bin/python -m pytest tests/test_documents_routes.py -v && venv/bin/ruff check .`
Expected: PASS, ruff clean (catches the orphaned imports).

- [ ] **Step 5: Commit**

```bash
git add backend/routes/documents.py backend/tests/test_documents_routes.py
git commit -m "feat(482): index /upload/sync uploads too, through the shared entry point"
```

---

### Task 6: The sweeper

**Files:**
- Create: `backend/services/index_sweeper.py`
- Modify: `backend/main.py:89` (`_lifespan`) — start beside `events_service.start_worker()`, stop beside `events_service.shutdown()`
- Test: `backend/tests/test_index_sweeper.py`

**Interfaces:**
- Consumes: `db.connection.rpc("claim_documents_for_indexing", {...})`; `document_indexing.index_document`.
- Produces: `sweep_once() -> int` (documents re-driven), `start_sweeper()`, `stop_sweeper()`.

- [ ] **Step 1: Write the failing tests**

```python
def test_sweep_re_drives_each_claimed_document(monkeypatch):
    monkeypatch.setattr(index_sweeper, "rpc",
                        lambda fn, params: [{"id": "d1"}, {"id": "d2"}])
    driven = []
    monkeypatch.setattr(index_sweeper, "index_document",
                        lambda d, **kw: driven.append((d, kw)))
    assert index_sweeper.sweep_once() == 2
    # claimed=True: the claim function already incremented index_attempts,
    # so a second claim here would double-count and halve the retry budget.
    assert driven == [("d1", {"claimed": True}), ("d2", {"claimed": True})]


def test_sweep_passes_the_configured_bounds(monkeypatch):
    seen = {}
    monkeypatch.setattr(index_sweeper, "rpc",
                        lambda fn, params: seen.update(fn=fn, **params) or [])
    index_sweeper.sweep_once()
    assert seen["fn"] == "claim_documents_for_indexing"
    assert seen["max_attempts"] == 3
    assert seen["lease_seconds"] == 600
    assert seen["batch_size"] == 10


def test_sweep_is_inert_outside_real_model_mode(monkeypatch):
    """Function-mode E2E must never sweep."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    called = []
    monkeypatch.setattr(index_sweeper, "rpc", lambda *a, **k: called.append(1) or [])
    assert index_sweeper.sweep_once() == 0
    assert called == []


def test_kill_switch_disables_the_sweeper(monkeypatch):
    monkeypatch.setenv("INDEX_SWEEPER_ENABLED", "false")
    assert index_sweeper.sweeper_enabled() is False


def test_sweeper_is_on_by_default_in_real_mode(monkeypatch):
    """A queue nothing drains is the bug being fixed; defaulting off would
    repeat the fate of the DBOS path (ADR 0011)."""
    monkeypatch.delenv("INDEX_SWEEPER_ENABLED", raising=False)
    monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
    assert index_sweeper.sweeper_enabled() is True


def test_one_document_failing_does_not_abort_the_batch(monkeypatch):
    monkeypatch.setattr(index_sweeper, "rpc",
                        lambda fn, p: [{"id": "d1"}, {"id": "d2"}])
    def half_broken(doc_id, **kw):
        if doc_id == "d1":
            raise RuntimeError("boom")
    monkeypatch.setattr(index_sweeper, "index_document", half_broken)
    assert index_sweeper.sweep_once() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_index_sweeper.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
SWEEP_INTERVAL_SECONDS = int(os.getenv("INDEX_SWEEP_INTERVAL_SECONDS", "300"))
MAX_ATTEMPTS = int(os.getenv("INDEX_MAX_ATTEMPTS", "3"))
LEASE_SECONDS = int(os.getenv("INDEX_LEASE_SECONDS", "600"))
BATCH_SIZE = int(os.getenv("INDEX_SWEEP_BATCH", "10"))


def sweeper_enabled() -> bool:
    if os.getenv("INDEX_SWEEPER_ENABLED", "true").lower() != "true":
        return False
    return model_mode() == "real"
```

`sweep_once()` claims via `rpc`, drives each id through `index_document` inside a per-document
`try/except` that logs and continues, and returns the count that succeeded. The loop runs in a
thread (`asyncio.to_thread`) because PostgREST calls are synchronous — same reason the post-roll
does.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && venv/bin/python -m pytest tests/test_index_sweeper.py tests/test_main*.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/index_sweeper.py backend/main.py backend/tests/test_index_sweeper.py
git commit -m "feat(482): a lifespan sweeper that drains the indexing queue"
```

---

### Task 7: Admin visibility and forced re-index

**Files:**
- Modify: `backend/routes/admin_analytics.py` (follow its existing `require_admin` pattern) or create `backend/routes/admin_documents.py` + mount in `backend/main.py:150-169`
- Test: `backend/tests/test_admin_documents.py`

**Interfaces:**
- Consumes: `document_indexing.index_document`; `auth_guard.require_admin`.
- Produces: `GET /api/admin/documents/unindexed`, `POST /api/admin/documents/{id}/reindex`.

- [ ] **Step 1: Write the failing tests**

```python
def test_unindexed_requires_admin(client_as_student):
    assert client_as_student.get("/api/admin/documents/unindexed").status_code == 403


def test_unindexed_lists_stuck_documents(client_as_admin, seeded_failed_doc):
    body = client_as_admin.get("/api/admin/documents/unindexed").json()
    row = next(r for r in body["documents"] if r["id"] == seeded_failed_doc)
    assert row["index_status"] == "failed"
    assert row["index_attempts"] == 3


def test_unindexed_never_returns_document_text(client_as_admin, seeded_failed_doc):
    body = client_as_admin.get("/api/admin/documents/unindexed").json()
    assert "extracted_text" not in body["documents"][0]
    assert "summary" not in body["documents"][0]


def test_reindex_forces_an_already_indexed_document(client_as_admin, monkeypatch):
    seen = {}
    monkeypatch.setattr(admin_documents, "index_document",
                        lambda d, **kw: seen.update(doc=d, **kw))
    r = client_as_admin.post("/api/admin/documents/doc-1/reindex")
    assert r.status_code == 200
    assert seen == {"doc": "doc-1", "force": True}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_admin_documents.py -v`
Expected: FAIL — 404 on both routes.

- [ ] **Step 3: Implement**

Select only the scalar index columns plus `file_name` and `created_at`. Never select `extracted_text`, `summary` or `concept_notes` — the encrypted columns have no business on an ops list. Page the read (`page_all`) per the 206-truncation rule.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && venv/bin/python -m pytest tests/test_admin_documents.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routes/admin_documents.py backend/main.py backend/tests/test_admin_documents.py
git commit -m "feat(482): admin surface for stuck documents and forced re-index"
```

---

### Task 8: Derivation backfill, and make the old backfill a thin caller

**Files:**
- Create: `backend/scripts/backfill_document_index_status.py`
- Modify: `backend/scripts/backfill_document_chunks.py` (drop `_already_indexed`, call `index_document`)
- Test: `backend/tests/test_backfill_document_index_status.py`, `backend/tests/test_backfill_document_chunks.py`

**Interfaces:**
- Consumes: `document_indexing.index_document`.
- Produces: `derive_status(doc_row, chunk_count) -> tuple[str, int]`; CLI `--apply` / dry-run default.

- [ ] **Step 1: Write the failing tests**

```python
def test_document_with_chunks_is_indexed():
    assert derive_status({"extracted_text": "x"}, chunk_count=31) == ("indexed", 31)


def test_document_with_text_but_no_chunks_is_pending():
    assert derive_status({"extracted_text": "x"}, chunk_count=0) == ("pending", 0)


def test_document_without_text_is_terminally_failed():
    """Prod has 2 of these. They must be visible, and never retried."""
    status, _ = derive_status({"extracted_text": None}, chunk_count=0)
    assert status == "failed"


def test_dry_run_writes_nothing(monkeypatch):
    writes = []
    monkeypatch.setattr(backfill, "_update", lambda *a, **k: writes.append(a))
    backfill.main(["--dry-run"])
    assert writes == []


def test_backfill_is_idempotent(monkeypatch):
    first = backfill.main(["--apply"])
    second = backfill.main(["--apply"])
    assert second.changed == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_backfill_document_index_status.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Count chunks per `doc_id` from `course_chunks` in ONE paged read, not a query per document. `_already_indexed` is deleted rather than fixed: on shared rows `doc_id` names only the last writer (#629), so it can never be reliable.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && venv/bin/python -m pytest tests/test_backfill_document_index_status.py tests/test_backfill_document_chunks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/backfill_document_index_status.py backend/scripts/backfill_document_chunks.py backend/tests/
git commit -m "feat(482): derive index_status for existing documents, once and truthfully"
```

---

### Task 9: Full gate

- [ ] **Step 1: Hermetic suite and lint**

```bash
cd backend && venv/bin/python -m pytest tests/ -q && venv/bin/ruff check .
```
Expected: all pass, ruff clean. Do NOT export `SAPLING_MODEL_MODE` for this run — it fails ~17 mode/guard tests.

- [ ] **Step 2: Update the docs the change invalidates**

`CLAUDE.md` repo map (new `services/document_indexing.py`, `services/index_sweeper.py`, `routes/admin_documents.py`), and `docs/architecture.md`'s "Known sharp edges" entry about the durability inversion — which this change closes.

- [ ] **Step 3: One flock'd E2E cycle**

```bash
flock /tmp/claude-1000/sapling-e2e-stack.lock bash -c '
  set -e
  make e2e-up
  export SAPLING_MODEL_MODE=function SAPLING_FUNCTION_HANDLERS=1
  cd frontend && npx playwright test; cd ..
  cd backend && venv/bin/python -m e2e_oracles; cd ..
  make e2e-down'
```
Expected: journeys green, oracles 0 findings, migration replay from empty clean. ONE flock for the whole cycle — a separately-flocked teardown deadlocks.

- [ ] **Step 4: `/code-review high`, then fix what it finds**

Delete `test-results/` and `e2e/results/` first — stale red artifacts make the review call a good fix falsified.

- [ ] **Step 5: Open the PR**

Body states the scope correction (most of #482 already landed), the five decisions, and the ops note: this migration must be applied before the code, like #629's.
