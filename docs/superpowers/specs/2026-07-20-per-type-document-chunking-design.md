# Per-type document chunking

- Date: 2026-07-20
- Status: proposed (design)
- Related: `docs/decisions/0019-content-addressed-course-chunks-ids.md` (forward-references `[[0021-per-type-document-chunking]]`)

## Problem

The RAG pipeline uses a single chunker (`services/chunker.py::chunk_document`) for every
document. It splits on double-newline block boundaries — the natural delimiter in Docling's
markdown output — which works well for **structured** material (slides, lecture notes,
syllabi) but poorly for **continuous prose**. A student's written problem-set work, an essay,
or a dense reading has few blank-line boundaries, so the block splitter produces one giant
block that then gets chopped at arbitrary sentence boundaries with no overlap — ideas land
split across chunks and retrieval quality suffers.

## Approach: strategy registry keyed on `category`

The document classifier already emits a `category`
(`syllabus | lecture_notes | slides | reading | assignment | study_guide | other`), and
`routes/documents.py::_index_document_chunks` (line ~1074) already **receives** that category
but currently ignores it, calling `chunk_document(text)` unconditionally. We wire the existing
signal through instead of inventing a new one.

`services/chunker.py` gains a dispatch:

```python
def chunk_for_category(text: str, category: str) -> list[str]:
    if category in _PROSE_CATEGORIES:   # reading, assignment, study_guide
        return chunk_prose(text)
    return chunk_document(text)         # slides, lecture_notes, syllabus, other (unchanged)
```

- `_index_document_chunks` calls `chunk_for_category(extracted_text, category)` instead of
  `chunk_document(extracted_text)`. No other call site changes.
- `chunk_document` is untouched — structured material keeps its current, working behavior.

## The prose chunker

`chunk_prose(text)` windows over sentences instead of blocks:

1. Segment `text` into sentences (extend the existing `". "`-boundary logic in
   `_split_at_sentence`; handle `?`/`!` too).
2. Greedily pack sentences into windows targeting **~200 words**, hard-capped at
   `_MAX_WORDS` (400).
3. Carry a **~40-word overlap** (the trailing whole sentences summing to ≈40 words) into the
   start of the next window, so ideas that straddle a boundary appear in both neighbours.
4. Drop a trailing window below `_MIN_WORDS` (50) by merging it into the previous window.

**Determinism is a hard requirement** (per ADR 0019: chunk IDs are derived from chunk text, so
boundaries must be reproducible). `chunk_prose` uses only fixed thresholds and greedy packing —
no randomness, no model calls — so re-running on identical input yields identical chunks.

## Constants

Defined alongside the existing `_MIN_WORDS`/`_MAX_WORDS`:

- `_PROSE_TARGET_WORDS = 200`
- `_PROSE_OVERLAP_WORDS = 40`
- `_PROSE_CATEGORIES = {"reading", "assignment", "study_guide"}`

## Data flow (unchanged except the dispatch)

```
upload → classify (category) → extract text
      → _index_document_chunks(category)
            → chunk_for_category(text, category)   ← NEW dispatch
            → embed batches → upsert course_chunks
```

## Testing

- `tests/test_chunker.py`: add cases for `chunk_prose` — continuous prose with no `\n\n`
  splits into ~200-word windows; overlap present between adjacent chunks; determinism (same
  input → identical output across two calls); short prose stays a single chunk; `assignment`/
  `reading`/`study_guide` route to prose while `slides`/`syllabus` route to the block chunker.
- `tests/test_document_indexing.py`: assert `_index_document_chunks` dispatches on category.

## Re-indexing note (for the plan, not this design)

Changing prose boundaries changes chunk IDs, so previously-indexed prose documents will not
collide with their new chunks. Existing rows are stale-but-harmless (last-writer-wins metadata);
a backfill re-index (`scripts/backfill_document_chunks.py`) can refresh them. Whether to backfill
now or let it happen on next upload is an implementation decision for the plan.

## Separate, unrelated note: tutor answer-behavior

The pedagogical rule — the tutor must **never give out answers or complete a student's
assignment / problem set**, and should guide with hints and analogous examples instead — is a
standing behavioral instruction in the tutor's system prompt (`PREAMBLE_TEMPLATE` in
`routes/learn.py`), and equivalently in the quiz-generation prompt (`backend/prompts/`). It is
**not** part of this chunking work and does not depend on it: the rule holds regardless of what
is ingested or what RAG retrieves. Captured here only so it isn't lost; it can ship on its own.

## Out of scope

- The tutor answer-behavior rule above (separate, system-prompt-only change).
- Distinguishing assignment prompts from student solutions (no classifier change).
- The doc-scoped vs. content-addressed chunk-ID discrepancy between ADR 0019 and the current
  `rag_service.index_document_chunks` — noted, but not addressed here.
