# Quiz-grounding eval fixtures

Deterministic ground-truth data for the Layer-1 (retrieval precision/recall)
and Layer-2 (judged grounding) quiz evals. A fake course, "TEST QG 101"
(algorithms/data structures), with fixture course material and a manifest
labeling which phrases should be retrievable for which concepts.

## Files

- `manifest.json` — the labeled ground truth. Schema:
  ```json
  {
    "bu_course_code": "TEST QG 101",
    "concepts": [
      {"concept_name": "...", "kind": "rich|thin|adversarial",
       "relevant_chunk_substrings": ["...", "..."],
       "on_scope_topics": ["..."], "off_scope_topics": ["..."]},
      ...
    ],
    "off_scope_probe_concepts": ["...", "..."]
  }
  ```
  - `kind: "rich"` concepts have several paragraphs of course material.
  - `kind: "thin"` concepts have a single sentence of course material —
    they exercise the case where retrieval has very little to work with.
  - `kind: "adversarial"` concepts share a name with unrelated,
    out-of-scope material (e.g. "trees" as a data structure vs.
    phylogenetic/family trees) — they exercise the case where retrieval
    or the quiz-grounding judge must not be fooled by surface-level term
    overlap.
  - `off_scope_probe_concepts` are topics with zero coverage in the
    fixture docs at all — used to confirm the pipeline correctly refuses
    or flags ungrounded quiz generation rather than hallucinating.
- `docs/*.md` — the fixture course material, one file per concept,
  seeded as a single document.
- `gold_labels.json` — human-calibration labels for the Layer-2 judge
  (starts empty; populated in Task 5).

## CRITICAL invariant: substrings must appear verbatim in the docs

Every phrase listed in a concept's `relevant_chunk_substrings` in
`manifest.json` **must appear character-for-character (case-sensitive)**
somewhere in `docs/*.md`. Layer-1 evals (Task 3) check retrieval
precision/recall by testing whether retrieved chunks contain these exact
substrings — if a substring doesn't literally appear in the docs, the
eval will always fail regardless of retrieval quality.

When editing either the manifest or the docs:

1. Any new/changed `relevant_chunk_substrings` entry must be copy-pasted
   from (or verified against) the actual doc text — don't paraphrase.
2. Keep doc paragraphs structured with blank-line (`\n\n`) breaks so
   `services.chunker.chunk_document` splits them the way a real
   ingested document would.
3. Re-run the seed script (below) and the retrieval sanity check after
   any doc/manifest change.

## Regenerating / seeding staging

```
cd backend
.\venv\Scripts\python.exe scripts/seed_quiz_fixture.py
```

This reads `.env.staging`, chunks all `docs/*.md` with
`chunk_document`, and upserts them into `course_chunks` (staging) under
`course_id = "TEST QG 101"` via `index_document_chunks`. It is additive
and idempotent — content-hash-based chunk IDs mean re-running it after a
doc edit re-indexes cleanly without leaving orphaned rows for unchanged
chunks, and it never touches any real course's data.

Sanity-check retrieval afterward:

```
.\venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('.env.staging'); import sys; sys.path.insert(0,'.'); from services.rag_service import retrieve_chunks; print(len(retrieve_chunks('dynamic programming', course_id='TEST QG 101', k=5)))"
```

Expected: a non-zero count.

## Labeling rubric (reserved — Task 5)

The gold-labeling rubric for `gold_labels.json` (what counts as
"grounded" vs. "hallucinated" for the Layer-2 judge, inter-rater
guidance, etc.) is authored in Task 5 alongside the human calibration
pass. This section is intentionally left as a placeholder until then.
