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
- `gold_labels.json` — human-calibration labels for the Layer-2 judge.
  Starts `{"labels": []}`; a human populates it by hand (see "Labeling
  rubric" below) — it is never auto-filled by an LLM.

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

```powershell
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

```powershell
.\venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('.env.staging'); import sys; sys.path.insert(0,'.'); from services.rag_service import retrieve_chunks; print(len(retrieve_chunks('dynamic programming', course_id='TEST QG 101', k=5)))"
```

Expected: a non-zero count.

## Labeling rubric (Task 5)

`gold_labels.json` holds **human**-authored ground truth used to check
whether the Layer-2 LLM judge (`judge_question` in `benchmark_quiz.py`)
can be trusted. An LLM must never author these labels — that would just
be checking the judge against itself. A person reads each question
against the fixture course material in `docs/*.md` and records their
own true/false verdict for each of the three dimensions the judge also
scores:

- **`grounded`** — `true` only if the question's content (the concept
  being tested, any facts/claims in the stem, and the correct answer)
  is actually supported by the material in `docs/*.md`. If the
  question relies on outside knowledge not present in the fixture
  docs, or misstates something the docs say, label `false`.
- **`on_scope`** — `true` unless the question tests a topic the
  fixture course clearly does not cover (off-syllabus). Foundational,
  on-topic content still counts as `on_scope=true` even if it isn't
  verbatim in the material — this dimension is about topical
  relevance to the course, not verbatim grounding (see `grounded`
  above for that).
- **`answer_correct`** — `true` only if the option marked as the
  correct answer is, in fact, the correct answer to the question as
  written.

### Entry shape

Each entry in the `labels` array pairs a real wire-format question
(exactly what `routes/quiz.py::_agent_question_to_wire` produces — i.e.
what `_generate_quiz_for_async`/`_quiz_via_agent` actually returns, so
labels line up with what `judge_question` is given) with the human's
verdict on the three dimensions above:

```json
{
  "labels": [
    {
      "question_obj": {
        "question": "What technique avoids recomputing overlapping subproblems?",
        "options": [
          {"text": "Memoization", "correct": true},
          {"text": "Bubble sort", "correct": false},
          {"text": "Binary search", "correct": false},
          {"text": "Depth-first search", "correct": false}
        ]
      },
      "grounded": true,
      "on_scope": true,
      "answer_correct": true
    }
  ]
}
```

`question_obj` must be a real question — either copied from an actual
`scripts/benchmark_quiz.py` run's Layer 2 output, or from
`unlabeled_candidates.json` (see below) if present — never invented
from scratch, since the point is to grade the real generation +
judging pipeline.

### Populating the gold set

Target ~20 labeled entries spanning the `rich`/`thin`/`adversarial`
concepts in `manifest.json`, including at least a few expected to be
`grounded=false` or `on_scope=false` so the judge is checked on
negatives, not just positives. Labeling is a manual, human step — it
is intentionally not automated here. `gold_labels.json` starts (and,
absent a human labeling pass, remains) `{"labels": []}`; with an empty
gold set, `scripts/benchmark_quiz.py --calibrate` prints a reminder to
label questions first and exits without calling the judge.

If `unlabeled_candidates.json` exists alongside this README, it holds
real generated `question_obj` entries with no label fields yet — a
human can copy entries from it into `gold_labels.json` and fill in the
three booleans, rather than needing to run the benchmark themselves to
get raw material to label.

Once ~20 entries are labeled, run:

```powershell
.\venv\Scripts\python.exe scripts/benchmark_quiz.py --calibrate
```

This prints per-dimension agreement between the judge and the human
labels. Any dimension below 0.80 means the judge is not reliable on
that dimension yet — revise `_JUDGE_PROMPT` in `benchmark_quiz.py` and
re-run calibration before trusting Layer 2 results.
