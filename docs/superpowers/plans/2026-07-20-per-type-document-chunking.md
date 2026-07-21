# Per-type Document Chunking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route documents to different chunking strategies based on their classified `category` — a sentence-window "prose" chunker for continuous writing, the existing block chunker for structured markdown.

**Architecture:** Add `chunk_prose(text)` and a `chunk_for_category(text, category)` dispatch to `services/chunker.py`. The dispatch sends `reading`/`assignment`/`study_guide` to `chunk_prose` and everything else to the unchanged `chunk_document`. The document ingest path and the backfill script already know each document's `category`; they call the dispatch instead of `chunk_document` directly.

**Tech Stack:** Python 3, pytest. No new dependencies.

## Global Constraints

- Chunk boundaries MUST be deterministic — chunk IDs are derived from chunk text, so identical input must always produce identical chunks (no randomness, no model calls in the chunker). (ADR 0019)
- Reuse the existing module-level constants `_MIN_WORDS = 50` and `_MAX_WORDS = 400` in `services/chunker.py`; do not redefine them.
- `chunk_document` must remain behaviorally unchanged — structured categories keep today's output exactly.
- All Supabase access goes through `db/connection.py::table()`.
- Run all commands from `backend/`.

## Prose category set (verbatim)

```python
_PROSE_CATEGORIES = {"reading", "assignment", "study_guide"}
```
Everything else (`syllabus`, `lecture_notes`, `slides`, `other`, and any unknown value) routes to `chunk_document`.

## File Structure

- `backend/services/chunker.py` — MODIFY. Add `_PROSE_TARGET_WORDS`, `_PROSE_OVERLAP_WORDS`, `_PROSE_CATEGORIES`, `_split_sentences`, `chunk_prose`, `chunk_for_category`. `chunk_document`, `_word_count`, `_split_at_sentence` unchanged.
- `backend/tests/test_chunker.py` — MODIFY. Add prose + dispatch tests alongside the existing block tests.
- `backend/routes/documents.py` — MODIFY (~lines 1061, 1074). Import and call `chunk_for_category` instead of `chunk_document`.
- `backend/tests/test_document_indexing.py` — MODIFY. Update the two existing tests to patch `chunk_for_category`; add a dispatch-passthrough assertion.
- `backend/scripts/backfill_document_chunks.py` — MODIFY (~lines 79, 120). Select `category` and route through `chunk_for_category`.

---

### Task 1: Prose chunker + category dispatch in `services/chunker.py`

**Files:**
- Modify: `backend/services/chunker.py`
- Test: `backend/tests/test_chunker.py`

**Interfaces:**
- Consumes: existing `_word_count(text) -> int`, `_split_at_sentence(text, max_words) -> list[str]`, constants `_MIN_WORDS`, `_MAX_WORDS`.
- Produces:
  - `chunk_prose(text: str) -> list[str]`
  - `chunk_for_category(text: str, category: str) -> list[str]`
  - `_split_sentences(text: str) -> list[str]`
  - constants `_PROSE_TARGET_WORDS = 200`, `_PROSE_OVERLAP_WORDS = 40`, `_PROSE_CATEGORIES = {"reading", "assignment", "study_guide"}`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_chunker.py`:

```python
from services.chunker import chunk_prose, chunk_for_category, chunk_document


def _prose(n):
    """n distinct sentences, each 10 unique tokens + a period.

    Every token is unique to its sentence, so any token shared between two
    chunks proves a whole sentence overlaps them."""
    return " ".join(
        f"alpha{i} bravo{i} charlie{i} delta{i} echo{i} "
        f"foxtrot{i} golf{i} hotel{i} india{i} juliet{i}."
        for i in range(n)
    )


def test_prose_empty_returns_empty():
    assert chunk_prose("") == []
    assert chunk_prose("   ") == []


def test_prose_short_text_is_single_chunk():
    text = "Photosynthesis converts light into chemical energy. It happens in chloroplasts."
    result = chunk_prose(text)
    assert len(result) == 1
    assert "photosynthesis" in result[0].lower()


def test_prose_no_blank_lines_splits_into_multiple_chunks():
    # ~600 words of continuous prose with NO double-newline boundaries.
    result = chunk_prose(_prose(60))
    assert len(result) >= 2


def test_prose_chunks_respect_max_words():
    for chunk in chunk_prose(_prose(60)):
        assert len(chunk.split()) <= _MAX_WORDS_BUFFER


def test_prose_adjacent_chunks_overlap():
    chunks = chunk_prose(_prose(60))
    assert len(chunks) >= 2
    for a, b in zip(chunks, chunks[1:]):
        shared = set(a.split()) & set(b.split())
        assert shared, "expected at least one overlapping sentence between adjacent chunks"


def test_prose_is_deterministic():
    text = _prose(45)
    assert chunk_prose(text) == chunk_prose(text)


def test_prose_no_tiny_trailing_chunk():
    # 21 sentences (~210 words): the leftover after the first ~200-word window
    # is small and must be absorbed, never emitted as a sub-50-word chunk.
    for chunk in chunk_prose(_prose(21)):
        assert len(chunk.split()) >= _MIN_WORDS_FLOOR


def test_dispatch_prose_categories_use_prose_chunker():
    text = _prose(40)
    for cat in ("reading", "assignment", "study_guide"):
        assert chunk_for_category(text, cat) == chunk_prose(text)


def test_dispatch_structured_categories_use_block_chunker():
    text = "Block one about sorting.\n\nBlock two about graphs.\n\nBlock three about trees."
    for cat in ("slides", "lecture_notes", "syllabus", "other", "unknown_value"):
        assert chunk_for_category(text, cat) == chunk_document(text)
```

Add these two constants near the top of `backend/tests/test_chunker.py` (below the imports) so the assertions read clearly:

```python
_MAX_WORDS_BUFFER = 420   # _MAX_WORDS (400) + small slack for a boundary sentence
_MIN_WORDS_FLOOR = 50     # matches chunker._MIN_WORDS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_chunker.py -q`
Expected: FAIL with `ImportError: cannot import name 'chunk_prose'` (and `chunk_for_category`).

- [ ] **Step 3: Implement the prose chunker and dispatch**

In `backend/services/chunker.py`, add `import re` at the top of the file (below the module docstring). Then add the following after `_split_at_sentence` (keep `chunk_document` where it is):

```python
_PROSE_TARGET_WORDS = 200
_PROSE_OVERLAP_WORDS = 40
_PROSE_CATEGORIES = {"reading", "assignment", "study_guide"}

# Split on whitespace that follows sentence-ending punctuation.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    """Split prose into sentences, collapsing all whitespace first.

    Prose (essays, problem-set writeups) has sparse blank lines, so we
    normalize newlines away and segment on sentence punctuation instead of
    on blocks. Deterministic: fixed regex, no model calls.
    """
    normalized = " ".join(text.split())
    if not normalized:
        return []
    return [s for s in _SENTENCE_BOUNDARY.split(normalized) if s]


def chunk_prose(text: str) -> list[str]:
    """Chunk continuous prose into overlapping sentence windows.

    Packs sentences greedily into ~_PROSE_TARGET_WORDS windows, carries a
    ~_PROSE_OVERLAP_WORDS overlap into the next window so ideas straddling a
    boundary appear in both, hard-caps any window at _MAX_WORDS, and absorbs a
    too-small trailing remainder into the final window. Deterministic.
    """
    if not text or not text.strip():
        return []

    sentences = _split_sentences(text)
    if not sentences:
        return []

    counts = [_word_count(s) for s in sentences]
    n = len(sentences)

    # Whole document fits in one window -> single chunk.
    if sum(counts) <= _PROSE_TARGET_WORDS:
        return [" ".join(sentences)]

    chunks: list[str] = []
    start = 0
    while start < n:
        # Grow the window until we reach the word target (or run out).
        end = start
        words = 0
        while end < n and words < _PROSE_TARGET_WORDS:
            words += counts[end]
            end += 1

        # If the leftover tail is too small to stand alone, absorb it here
        # rather than emit a sub-_MIN_WORDS chunk.
        remaining = sum(counts[end:])
        if 0 < remaining < _MIN_WORDS:
            end = n

        piece = " ".join(sentences[start:end])
        if _word_count(piece) > _MAX_WORDS:
            chunks.extend(_split_at_sentence(piece, _MAX_WORDS))
        else:
            chunks.append(piece)

        if end >= n:
            break

        # Step back to create overlap for the next window. Guarantee forward
        # progress: next window always starts at least one sentence past `start`.
        overlap = 0
        next_start = end
        while next_start - 1 > start and overlap < _PROSE_OVERLAP_WORDS:
            next_start -= 1
            overlap += counts[next_start]
        start = next_start

    return [c for c in chunks if c.strip()]


def chunk_for_category(text: str, category: str) -> list[str]:
    """Route to the chunking strategy for a document's classified category.

    Continuous-prose categories use the sentence-window chunker; structured
    markdown (and any unrecognized category) uses the block chunker.
    """
    if category in _PROSE_CATEGORIES:
        return chunk_prose(text)
    return chunk_document(text)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_chunker.py -q`
Expected: PASS (all existing block tests plus the new prose/dispatch tests).

- [ ] **Step 5: Lint**

Run: `ruff check services/chunker.py tests/test_chunker.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/services/chunker.py backend/tests/test_chunker.py
git commit -m "feat(rag): add prose chunker and per-category chunking dispatch"
```

---

### Task 2: Route the ingest pipeline through `chunk_for_category`

**Files:**
- Modify: `backend/routes/documents.py` (import ~line 1061; call ~line 1074)
- Test: `backend/tests/test_document_indexing.py`

**Interfaces:**
- Consumes: `services.chunker.chunk_for_category(text, category) -> list[str]` (Task 1).
- Produces: no new public interface; `_index_document_chunks` now dispatches on the `category` it already receives.

- [ ] **Step 1: Update the failing tests**

In `backend/tests/test_document_indexing.py`, the two existing tests patch `services.chunker.chunk_document`; the code will now call `chunk_for_category`. Replace the patch target and the call assertion.

In `test_happy_path_indexes_chunks_when_no_catalog_embedding`, change:

```python
            patch("services.chunker.chunk_document", return_value=chunks) as mock_chunk,
```
to:
```python
            patch("services.chunker.chunk_for_category", return_value=chunks) as mock_chunk,
```

and change the call assertion:

```python
        mock_chunk.assert_called_once_with("some extracted text")
```
to (the test passes `category="lecture_notes"`):
```python
        mock_chunk.assert_called_once_with("some extracted text", "lecture_notes")
```

In `test_empty_chunks_short_circuits_before_indexing`, change:

```python
            patch("services.chunker.chunk_document", return_value=[]),
```
to:
```python
            patch("services.chunker.chunk_for_category", return_value=[]),
```

Then add a new test to the `TestIndexDocumentChunks` class proving the category is threaded through:

```python
    def test_category_is_passed_to_chunker(self):
        """The document's category must reach the chunker so prose docs get
        the prose strategy."""
        with (
            patch(
                "routes.documents.table",
                side_effect=_mock_table_for(
                    courses_rows=[{"course_code": "ENG-201"}],
                    course_chunks_rows=[],
                ),
            ),
            patch(
                "services.chunker.chunk_for_category",
                return_value=["one chunk of prose"],
            ) as mock_chunk,
            patch("services.rag_service.index_document_chunks", return_value=1),
        ):
            _index_document_chunks(
                doc_id="doc-3",
                course_id="course-uuid-1",
                user_id="user-1",
                extracted_text="an essay body",
                category="assignment",
            )

        mock_chunk.assert_called_once_with("an essay body", "assignment")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_document_indexing.py -q`
Expected: FAIL — the patched `chunk_for_category` isn't called yet (code still calls `chunk_document`), so `mock_chunk.assert_called_once_with(...)` fails / `AssertionError`.

- [ ] **Step 3: Wire the dispatch into `_index_document_chunks`**

In `backend/routes/documents.py`, change the local import (~line 1061):

```python
    from services.chunker import chunk_document
```
to:
```python
    from services.chunker import chunk_for_category
```

and change the call (~line 1074):

```python
        chunks = chunk_document(extracted_text)
```
to:
```python
        chunks = chunk_for_category(extracted_text, category)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_document_indexing.py -q`
Expected: PASS (all three tests in `TestIndexDocumentChunks`).

- [ ] **Step 5: Lint**

Run: `ruff check routes/documents.py tests/test_document_indexing.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/routes/documents.py backend/tests/test_document_indexing.py
git commit -m "feat(rag): route document ingest through per-category chunker"
```

---

### Task 3: Route the backfill script through `chunk_for_category`

**Files:**
- Modify: `backend/scripts/backfill_document_chunks.py` (import ~line 42; select ~line 79; call ~line 120)

**Interfaces:**
- Consumes: `services.chunker.chunk_for_category` (Task 1).
- Produces: no new interface — the backfill now matches the live pipeline's per-category behavior instead of chunking every historical doc as a block.

**Note:** `scripts/seed_quiz_fixture.py` intentionally keeps `chunk_document` — its fixtures are hand-authored structured markdown with `\n\n` block breaks, and `tests/test_seed_quiz_fixture.py` asserts `chunk_document` is called per-file. Do not change it.

- [ ] **Step 1: Add `category` to the document query**

In `backend/scripts/backfill_document_chunks.py`, change the select (~line 78):

```python
    docs = table("documents").select(
        "id,file_name,user_id,offering_id,extracted_text",
        filters={"extracted_text": "not.is.null", "deleted_at": "is.null"},
    )
```
to:
```python
    docs = table("documents").select(
        "id,file_name,user_id,offering_id,extracted_text,category",
        filters={"extracted_text": "not.is.null", "deleted_at": "is.null"},
    )
```

- [ ] **Step 2: Update the import**

Change (~line 42):

```python
from services.chunker import chunk_document  # noqa: E402
```
to:
```python
from services.chunker import chunk_for_category  # noqa: E402
```

- [ ] **Step 3: Route the chunking call by category**

Change (~line 120):

```python
            chunks = chunk_document(extracted)
```
to:
```python
            chunks = chunk_for_category(extracted, doc.get("category") or "other")
```

- [ ] **Step 4: Verify the script imports cleanly (no live DB needed)**

Run: `python -c "import scripts.backfill_document_chunks"`
Expected: no output, exit 0 (module imports without error).

- [ ] **Step 5: Lint**

Run: `ruff check scripts/backfill_document_chunks.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/backfill_document_chunks.py
git commit -m "feat(rag): route chunk backfill through per-category chunker"
```

---

### Task 4: Full-suite regression check

**Files:** none (verification only).

- [ ] **Step 1: Run the chunking-related suites together**

Run: `python -m pytest tests/test_chunker.py tests/test_document_indexing.py tests/test_seed_quiz_fixture.py -q`
Expected: PASS — including `test_seed_quiz_fixture.py`, confirming the untouched fixture path still calls `chunk_document` per file.

- [ ] **Step 2: Run the broader RAG suite**

Run: `python -m pytest tests/test_rag_service.py tests/test_document_indexing.py -q`
Expected: PASS.

---

## Out of scope (do not implement here)

- **Tutor answer-behavior rule** — the "never give a student the answer / never complete an assignment" instruction is a separate, system-prompt-only change (`PREAMBLE_TEMPLATE` in `routes/learn.py` and the quiz prompt in `backend/prompts/`). It does not depend on this work and is tracked in the design doc's separate note.
- **Distinguishing assignment prompts from student solutions** — no classifier change.
- **Re-indexing existing prose docs** — changing prose boundaries changes chunk IDs; stale rows are harmless (last-writer-wins metadata). Running `scripts/backfill_document_chunks.py` (Task 3) after deploy will refresh docs that were never indexed; a full re-index of already-indexed docs is optional and not part of this plan.

## Self-Review

- **Spec coverage:** dispatch (Tasks 1–3), prose chunker with overlap + determinism + cap + tiny-tail handling (Task 1), constants (Task 1), ingest wiring (Task 2), unchanged block path for structured/`other` (Task 1 dispatch test), testing (Tasks 1–4). The design's "separate note" and out-of-scope items are recorded above, not implemented. ✓
- **Placeholders:** none — all code and commands are concrete. ✓
- **Type consistency:** `chunk_prose(text: str) -> list[str]`, `chunk_for_category(text: str, category: str) -> list[str]`, `_split_sentences(text: str) -> list[str]` are used identically everywhere they appear. ✓
