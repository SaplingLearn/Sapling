# Quiz Grounding in Course Material — Design Spec

**Date:** 2026-07-03
**Status:** Approved (pending user spec review)

---

## Problem

Quiz generation is the one AI feature with **zero** connection to course material. `quiz_agent` (`backend/agents/quiz.py`) receives only the target concept name as a string plus knowledge-graph signals (mastery, class misconceptions, prior attempts) via its tools. It never sees the BU catalog or the uploaded document chunks now indexed in `course_chunks` by the RAG pipeline.

The result: a quiz for CAS CS 330 is generated from the concept name + the student's mastery scores. It doesn't reflect what CS 330 actually covers, nor what's in the lecture slides / readings students in the class uploaded. This directly contradicts the product goal — *"practice problems based on the document ingestion provided from users of the same class."*

The tutor chat (`routes/learn.py::_chat_via_agent`) already grounds its answers in catalog + semantic `course_chunks` retrieval. This spec brings the same grounding to quiz generation, and adds a rigorous two-layer eval to verify it.

Study guides are explicitly **out of scope** for this cycle (they already read `documents.summary`/`concept_notes`; upgrading them is a later follow-up).

---

## Goal

When a quiz is generated for a concept in course X, retrieve the most relevant catalog + document chunks for that concept and inject them into the quiz agent's prompt, so the **majority** of questions are grounded in — and none drift off-scope from — what the class is actually learning. Then measure grounding accuracy with an eval whose own accuracy is validated against human labels.

---

## Grounding stance: mostly-grounded, on-scope (not exclusively-grounded)

- The retrieved course material is the **primary anchor**: most questions should trace to it and stay within its scope.
- It is **not a straitjacket**: where the material is thin on a concept, the agent may supplement with *foundational, on-topic* aspects of that same concept to produce a well-formed quiz.
- Off-syllabus drift is prohibited: the agent must not test topics the course clearly does not cover.

---

## Architecture

### Data flow

```
generate_quiz (POST /api/quiz/generate)
  concept_node → course_id (already resolved, quiz.py:229)
    → _quiz_via_agent(course_id, concept_name, ...)
        → bu_code = courses.course_code[course_id]           (new; same chain as tutor/upload)
        → rag_chunks = retrieve_chunks(concept_name, course_id=bu_code, k=5)   (new)
        → catalog_text = _get_catalog_chunk(bu_code)          (new; reuse learn.py helper)
        → user_message = COURSE MATERIAL block + existing routing message      (new)
        → quiz_agent.run(user_message, deps=...)              (unchanged call, richer message)
```

The agent keeps all current tools (mastery, misconceptions, quiz history) — those still drive difficulty, targeting, and distractors. The injected material drives *what the questions are about*.

Retrieval query = the `concept_name` (the natural, specific query, e.g. `"dynamic programming"`). Document chunks are the primary payload; the catalog chunk is included mainly for scope-bounding (it is a one-paragraph description, too thin to write substantive questions from).

---

## Components

### 1. Grounding injection — `routes/quiz.py::_quiz_via_agent`

Before building `user_message`, resolve the BU code and retrieve material:

```python
from routes.learn import _get_catalog_chunk
from services.rag_service import retrieve_chunks, format_rag_context

def _resolve_bu_code(course_id: str | None) -> str | None:
    if not course_id:
        return None
    rows = table("courses").select(
        "course_code", filters={"id": f"eq.{course_id}"}, limit=1
    )
    return (rows[0].get("course_code") if rows else None) or None

def _course_material_block(course_id: str | None, concept_name: str) -> str:
    """Best-effort catalog + document-chunk context for a concept. Empty string
    if nothing is available (no course, no bu_code, no chunks) — never raises."""
    bu_code = _resolve_bu_code(course_id)
    if not bu_code:
        return ""
    blocks: list[str] = []
    catalog = _get_catalog_chunk(bu_code)
    if catalog:
        blocks.append("COURSE CATALOG (official BU course data):\n\n" + catalog)
    try:
        chunks = retrieve_chunks(concept_name, course_id=bu_code, k=5)
    except Exception:
        chunks = []
    rag_block = format_rag_context(chunks)
    if rag_block:
        blocks.append(rag_block)
    return "\n\n".join(blocks)
```

Injected into `user_message`:

```python
material = _course_material_block(course_id, concept_name)
routing_msg = (  # the existing message, unchanged
    f"Generate {num_questions} {difficulty} questions for the student. "
    f"The target concept is '{concept_name}' (concept_node_id={concept_node_id}). "
    f"Follow the workflow in your system prompt; pass concept_node_id="
    f"'{concept_node_id}' to read_recent_quiz_attempts."
)
if use_shared_context:
    routing_msg += (
        " Also call read_misconceptions_for_course and use those misconceptions "
        "as distractors and probes."
    )
if material:
    user_message = (
        "COURSE MATERIAL for '" + concept_name + "':\n\n" + material
        + "\n\n[GENERATE QUIZ]\n" + routing_msg
    )
else:
    user_message = routing_msg
```

### 2. Fallback behavior (best-effort — never blocks a quiz)

Grounding *enhances*; its absence never fails quiz generation. If `course_id` is missing, `bu_code` can't be resolved, or retrieval returns nothing (no docs uploaded for that course yet), the block is empty and the quiz generates exactly as today. The existing 502-on-failure contract in `generate_quiz` is untouched — `_course_material_block` swallows its own retrieval errors.

### 3. System-prompt change — `agents/quiz.py`

Add a source-of-truth instruction, gated on the block's presence:

- **When a `COURSE MATERIAL` block is present:** treat it as the primary anchor. The majority of questions should be grounded in and stay within the scope of that material. Where the material is thin on the concept, you may supplement with foundational, on-topic aspects of the same concept — but never test topics the course does not cover (no off-syllabus drift). Difficulty, targeting, and distractors are still governed by the mastery/misconception/history tools.
- **When absent:** fall back to general knowledge of the concept (current behavior, unchanged).

No workflow rewrite — just this gated instruction.

---

## Eval design (two layers)

Runs against staging with real Gemini, as a standalone `scripts/benchmark_quiz.py` (mirrors `benchmark_rag.py`'s structure and reporting).

### Shared fixture (deterministic ground truth)

Seed known documents with distinctive content into a dedicated staging test course (a throwaway "TEST" offering), so both layers have controlled ground truth — we know exactly what the material says and what is on- vs. off-scope. Fixture coverage is deliberately diverse:

- **Rich-material concepts** — the material thoroughly covers the concept (tests straightforward grounding).
- **Thin-material concepts** — the material barely touches the concept (tests the "supplement with foundational on-topic content" behavior without off-scope drift).
- **Off-scope negative probes** — concepts the course does *not* cover; assert the agent does not generate questions on them.
- **Adversarial name-overlap** — concept names that overlap other domains (e.g. "trees": CS vs. biology) to catch scope drift.

The fixture (documents + a labeled ground-truth manifest of relevant chunks and on/off-scope topics) is committed as a data file so runs are reproducible.

### Layer 1 — Retrieval quality (precision/recall@k)

For each fixture concept, call `retrieve_chunks(concept_name, course_id=bu_code, k=5)` and score against the fixture's **labeled relevant-chunk set**:

- **Recall@k** — did the expected relevant chunks come back?
- **Precision@k** — how much of what came back is actually relevant (catches misleading junk that would pollute the quiz)?

Reported as continuous per-concept metrics plus an overall mean. This exercises the document-RAG path the quiz now depends on.

### Layer 2 — Quiz grounding, scope, and correctness (judged)

Generate a quiz for each fixture concept via the real code path (`_quiz_via_agent` invoked directly, staging DB), then judge it. The judge's own accuracy is validated (see Calibration).

**Judge design (this is where accuracy lives):**
- **Panel + majority vote:** run the judge N times (default N=3) per question; take the majority verdict. Reduces single-call variance.
- **Forced evidence citation:** for each question the judge must quote the exact span of source material that supports it, or state "not in material." Makes "grounded" verifiable rather than a vibe.
- **Judge ≠ generator model:** the judge uses a different (stronger) model than the one that generated the quiz, to avoid self-preference bias.
- **Answer-correctness check:** the judge verifies the marked correct answer is *actually correct*, not merely present among the options.

**Per-question verdicts → aggregated continuous metrics (reported, not just pass/fail):**
- **Grounded ratio** — fraction of questions with a valid evidence citation.
- **Off-scope count** — questions testing topics outside the course.
- **Correctness rate** — fraction whose marked answer the judge confirms is correct.

**Coarse regression gates (tunable, secondary to the raw numbers):**
- Grounded ratio ≥ 0.6 (majority grounded — reflects mostly-grounded stance).
- Off-scope count = 0 (strict; off-syllabus is a hard fail).
- Correctness rate ≥ 0.95.

Thresholds exist only to flag regressions in CI-adjacent runs; the tracked continuous metrics are the real signal.

### Calibration (validates the eval itself)

Before trusting the judge: hand-label ~20 generated questions (grounded? on-scope? answer correct?) once, and measure the judge panel's agreement with those human labels. If agreement is low, the judge prompt/model is wrong and the eval is measuring nothing — fix it before relying on Layer 2. The gold set is committed for re-checking when the judge model or prompt changes.

### Non-determinism dial

Real Gemini generation varies run-to-run. `benchmark_quiz.py` supports generating M quizzes per concept (default M=1, raise for a truer estimate) and averaging the Layer-2 metrics — a cost/accuracy trade-off the operator sets via a flag.

### Reporting

Same ASCII-bar accuracy report style as `benchmark_rag.py`: per-concept Layer-1 precision/recall and Layer-2 grounded/off-scope/correctness, plus overall means and the coarse gate verdicts.

---

## Hermetic unit tests (CI-gated)

In `tests/test_quiz_routes.py`, covering the injection logic without live LLM/DB:

- **bu_code resolution** — `_resolve_bu_code` returns the course_code for a known course_id; `None` for missing/unknown.
- **Material injected when chunks exist** — mock `retrieve_chunks` to return chunks; assert the `COURSE MATERIAL` block is prepended to `user_message` and the routing message is preserved.
- **Fallback: no chunks** — mock `retrieve_chunks` to return `[]`; assert `user_message` equals the routing message (no block) and the quiz still generates.
- **Fallback: no course_id** — assert no retrieval attempted, quiz generates as today.
- **Fallback: retrieval raises** — mock `retrieve_chunks` to raise; assert it's swallowed and the quiz still generates (no 502 from grounding).

The live two-layer benchmark is the content-quality gate; these unit tests are the plumbing gate.

---

## Error handling

- `_course_material_block` is best-effort and swallows retrieval exceptions → grounding failure degrades to current (ungrounded) behavior, never a user-facing error.
- The existing `generate_quiz` guardrail handling (`UsageLimitExceeded`/`UnexpectedModelBehavior`/bare-Exception → 502) is unchanged.

---

## Files changed

| File | Change |
|---|---|
| `backend/routes/quiz.py` | Modify — add `_resolve_bu_code`, `_course_material_block`; inject block in `_quiz_via_agent` |
| `backend/agents/quiz.py` | Modify — add gated source-of-truth instruction to the system prompt |
| `backend/tests/test_quiz_routes.py` | Modify — add 5 hermetic injection/fallback tests |
| `backend/scripts/benchmark_quiz.py` | New — two-layer live eval (retrieval P/R@k + judged grounding/scope/correctness) |
| `backend/scripts/fixtures/quiz_grounding/` | New — seeded fixture documents + labeled ground-truth manifest + human-labeled gold set |

---

## What this does NOT include (future work)

- **Study-guide grounding** — upgrading study guides to use catalog + semantic `course_chunks` (they currently read `documents.summary`/`concept_notes` only).
- **Agentic retrieval tool** — a `search_course_materials` tool the quiz agent calls on demand (deferred; injection is deterministic and sufficient).
- **Re-ranking / query expansion** on the quiz retrieval path beyond what `retrieve_chunks` already does.
