# Quiz Grounding in Course Material Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ground quiz generation in the catalog + document-RAG context the tutor already uses, so the majority of quiz questions reflect what the class is actually learning, and add a rigorous two-layer eval that verifies it.

**Architecture:** In `_quiz_via_agent` (routes/quiz.py), before invoking `quiz_agent`, resolve the BU course code and retrieve catalog + document chunks for the target concept, then prepend a `COURSE MATERIAL` block to the agent's message (best-effort — never blocks a quiz). A gated system-prompt instruction tells the agent to treat that material as the primary anchor. A standalone `scripts/benchmark_quiz.py` measures retrieval quality (Layer 1) and quiz grounding/scope/correctness via a calibrated LLM judge panel (Layer 2).

**Tech Stack:** Python, FastAPI, pydantic-ai, Supabase PostgREST, `google-genai` (gemini-embedding-001 + Gemini chat), pytest.

## Global Constraints

- All Supabase access goes through `db.connection.table()` or `db.connection.rpc()` — never import httpx or supabase-py directly.
- No imports of `google.generativeai` — project uses `google.genai` (the new SDK).
- Grounding is **best-effort**: absence of course material (no course_id, no bu_code, empty retrieval, or a retrieval exception) must never fail quiz generation — it falls back to current behavior. The existing `generate_quiz` 502 guardrail contract is unchanged.
- Grounding stance is **mostly-grounded, on-scope**: the majority of questions grounded in the material, supplementing with foundational on-topic content allowed, off-syllabus drift prohibited. Do NOT make grounding exclusive.
- Retrieval query is the `concept_name`; `retrieve_chunks(query, course_id, k=5, min_similarity=0.55)` returns `list[dict]` each `{"course_id", "chunk_text", "similarity"}`.
- BU code resolution chain: `table("courses").select("course_code", filters={"id": f"eq.{course_id}"}, limit=1)` — same as tutor/upload.
- Tests run from `backend/` with `pytest tests/ -q`; all tests must pass after each task. Use `.\venv\Scripts\python.exe -m pytest` on Windows.
- Study guides are OUT OF SCOPE.

---

### Task 1: Ground quiz generation in course material (production change + hermetic tests)

**Files:**
- Modify: `backend/routes/quiz.py` (add imports + `_resolve_bu_code`, `_course_material_block`; wire into `_quiz_via_agent` at ~line 144-192)
- Modify: `backend/agents/quiz.py` (append gated instruction to `_SYSTEM_PROMPT` at ~line 70-130)
- Test: `backend/tests/test_quiz_routes.py` (add a `TestQuizGrounding` class)

**Interfaces:**
- Produces:
  - `_resolve_bu_code(course_id: str | None) -> str | None`
  - `_course_material_block(course_id: str | None, concept_name: str) -> str` — best-effort; returns `""` on any miss/error, never raises
  - `_quiz_via_agent` unchanged signature; now prepends the material block to `user_message` when non-empty
- Consumes: `routes.learn._get_catalog_chunk(course_code: str) -> str`; `services.rag_service.retrieve_chunks`, `services.rag_service.format_rag_context`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_quiz_routes.py`:

```python
class TestQuizGrounding:
    """_quiz_via_agent prepends a COURSE MATERIAL block (best-effort) and
    the quiz still generates when grounding is absent."""

    NODE = {"id": "node_x", "user_id": "user_1", "course_id": "course-uuid-1",
            "concept_name": "dynamic programming"}

    def _valid_quiz_result(self):
        # quiz_agent.run(...) returns an object whose .output is a Quiz whose
        # single question passes wire validation (correct_answer ∈ options).
        from agents.quiz import Quiz, QuizQuestion
        q = QuizQuestion(
            question="What does memoization avoid?",
            type="multiple_choice", difficulty="easy",
            options=["Recomputation", "Sorting", "Hashing", "Recursion"],
            correct_answer="Recomputation",
            explanation="Memoization caches subproblem results.",
            concept="dynamic programming",
        )
        return MagicMock(output=Quiz(questions=[q]))

    def _table_factory(self, *, course_code="CAS CS 330"):
        def factory(name):
            m = MagicMock()
            if name == "graph_nodes":
                m.select.return_value = [self.NODE]
            elif name == "courses":
                m.select.return_value = [{"course_code": course_code}] if course_code else []
            else:  # quiz_attempts insert, etc.
                m.select.return_value = []
                m.insert.return_value = []
                m.update.return_value = []
            return m
        return factory

    def test_resolve_bu_code_returns_course_code(self):
        from routes.quiz import _resolve_bu_code
        with patch("routes.quiz.table", side_effect=self._table_factory()):
            assert _resolve_bu_code("course-uuid-1") == "CAS CS 330"

    def test_resolve_bu_code_none_for_missing(self):
        from routes.quiz import _resolve_bu_code
        assert _resolve_bu_code(None) is None
        with patch("routes.quiz.table", side_effect=self._table_factory(course_code=None)):
            assert _resolve_bu_code("course-uuid-1") is None

    def test_material_injected_when_chunks_exist(self):
        agent_run = AsyncMock(return_value=self._valid_quiz_result())
        with (
            patch("routes.quiz.table", side_effect=self._table_factory()),
            patch("routes.quiz.quiz_agent.run", new=agent_run),
            patch("routes.quiz._get_catalog_chunk", return_value="Course: CAS CS 330 ..."),
            patch("routes.quiz.retrieve_chunks",
                  return_value=[{"course_id": "CAS CS 330",
                                 "chunk_text": "Memoization caches subproblem results.",
                                 "similarity": 0.81}]),
        ):
            client.post("/api/quiz/generate", json={
                "user_id": "user_1", "concept_node_id": "node_x",
                "num_questions": 1, "difficulty": "easy", "use_shared_context": False,
            })
        msg = agent_run.call_args[0][0]
        assert "COURSE MATERIAL" in msg
        assert "Memoization caches subproblem results." in msg
        assert "[GENERATE QUIZ]" in msg
        assert "dynamic programming" in msg  # routing message preserved

    def test_no_block_when_retrieval_empty(self):
        agent_run = AsyncMock(return_value=self._valid_quiz_result())
        with (
            patch("routes.quiz.table", side_effect=self._table_factory()),
            patch("routes.quiz.quiz_agent.run", new=agent_run),
            patch("routes.quiz._get_catalog_chunk", return_value=""),
            patch("routes.quiz.retrieve_chunks", return_value=[]),
        ):
            r = client.post("/api/quiz/generate", json={
                "user_id": "user_1", "concept_node_id": "node_x",
                "num_questions": 1, "difficulty": "easy", "use_shared_context": False,
            })
        msg = agent_run.call_args[0][0]
        assert "COURSE MATERIAL" not in msg
        assert r.status_code == 200

    def test_retrieval_exception_is_swallowed(self):
        agent_run = AsyncMock(return_value=self._valid_quiz_result())
        with (
            patch("routes.quiz.table", side_effect=self._table_factory()),
            patch("routes.quiz.quiz_agent.run", new=agent_run),
            patch("routes.quiz._get_catalog_chunk", return_value=""),
            patch("routes.quiz.retrieve_chunks", side_effect=RuntimeError("embed down")),
        ):
            r = client.post("/api/quiz/generate", json={
                "user_id": "user_1", "concept_node_id": "node_x",
                "num_questions": 1, "difficulty": "easy", "use_shared_context": False,
            })
        assert r.status_code == 200  # grounding failure never 502s the quiz
        assert "COURSE MATERIAL" not in agent_run.call_args[0][0]
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend
.\venv\Scripts\python.exe -m pytest tests/test_quiz_routes.py::TestQuizGrounding -v
```
Expected: FAIL — `ImportError: cannot import name '_resolve_bu_code'` / `_get_catalog_chunk`/`retrieve_chunks` not patchable on `routes.quiz`.

- [ ] **Step 3: Add imports + helpers to `routes/quiz.py`**

Add these module-level imports near the top of `backend/routes/quiz.py` (with the other imports):

```python
from routes.learn import _get_catalog_chunk
from services.rag_service import retrieve_chunks, format_rag_context
```

Add these two helpers above `_quiz_via_agent`:

```python
def _resolve_bu_code(course_id: str | None) -> str | None:
    """Resolve a Sapling course UUID to its BU course_code (course_chunks
    partition key). None if unresolvable OR if the lookup fails — grounding
    must never break quiz generation."""
    if not course_id:
        return None
    try:
        rows = table("courses").select(
            "course_code", filters={"id": f"eq.{course_id}"}, limit=1
        )
    except Exception:
        return None
    return (rows[0].get("course_code") if rows else None) or None


def _course_material_block(course_id: str | None, concept_name: str) -> str:
    """Best-effort catalog + document-chunk context for a concept.

    Returns "" if nothing is available (no course, no bu_code, no chunks) or
    if retrieval raises — grounding must never break quiz generation.
    """
    bu_code = _resolve_bu_code(course_id)
    if not bu_code:
        return ""
    blocks: list[str] = []
    try:
        catalog = _get_catalog_chunk(bu_code)
    except Exception:
        catalog = ""
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

- [ ] **Step 4: Wire the block into `_quiz_via_agent`**

In `_quiz_via_agent`, replace the `user_message = (...)` assignment (and the `if use_shared_context:` block that follows it) at ~line 175-186 with:

```python
    routing_msg = (
        f"Generate {num_questions} {difficulty} questions for the student. "
        f"The target concept is '{concept_name}' "
        f"(concept_node_id={concept_node_id}). Follow the workflow in your "
        f"system prompt; pass concept_node_id='{concept_node_id}' to "
        f"read_recent_quiz_attempts."
    )
    if use_shared_context:
        routing_msg += (
            " Also call read_misconceptions_for_course and use those misconceptions "
            "as distractors and probes."
        )

    material = _course_material_block(course_id, concept_name)
    if material:
        user_message = (
            "COURSE MATERIAL for '" + concept_name + "':\n\n" + material
            + "\n\n[GENERATE QUIZ]\n" + routing_msg
        )
    else:
        user_message = routing_msg
```

- [ ] **Step 5: Verify no circular import**

```
cd backend
.\venv\Scripts\python.exe -c "import routes.quiz; print('import ok')"
```
Expected: `import ok`. If this raises `ImportError` (circular import via `routes.learn`), move the two new imports from module level into the top of `_course_material_block`/`_resolve_bu_code` function bodies instead, and update the test patch targets accordingly (patch `routes.quiz._get_catalog_chunk` still works only for module-level imports — if you move them function-local, patch `routes.learn._get_catalog_chunk` and `services.rag_service.retrieve_chunks`). Prefer module-level; only fall back if the import genuinely cycles.

- [ ] **Step 6: Append the gated instruction to the quiz system prompt**

In `backend/agents/quiz.py`, append to the `_SYSTEM_PROMPT` string (before the closing `)` after `"...concepts the student doesn't have."`):

```python
    "\n\nCOURSE MATERIAL grounding:\n"
    "- If the user message contains a `COURSE MATERIAL` block, treat it as "
    "  the PRIMARY source of truth for question content. The MAJORITY of "
    "  questions must be grounded in and stay within the scope of that "
    "  material, so the quiz reflects what this class is actually covering.\n"
    "- You MAY supplement with foundational, on-topic aspects of the same "
    "  concept where the material is thin — but NEVER test topics the course "
    "  clearly does not cover (no off-syllabus drift).\n"
    "- Difficulty, targeting, and distractors are still governed by the "
    "  mastery / misconception / quiz-history tools.\n"
    "- If there is no COURSE MATERIAL block, use general knowledge of the "
    "  concept as before."
```

(This changes `_PROMPT_HASH` automatically — it is derived from the prompt text.)

- [ ] **Step 7: Run the grounding tests — verify they pass**

```
.\venv\Scripts\python.exe -m pytest tests/test_quiz_routes.py::TestQuizGrounding -v
```
Expected: all 5 PASS.

- [ ] **Step 8: Run the full quiz route suite + full suite**

```
.\venv\Scripts\python.exe -m pytest tests/test_quiz_routes.py -q
.\venv\Scripts\python.exe -m pytest tests/ -q --ignore=tests/evals
```
Expected: no new failures (the pre-existing `test_flashcard_import_service` timing flake and `test_ocr_pipeline` asyncio error are unrelated).

- [ ] **Step 9: Commit**

```
git add backend/routes/quiz.py backend/agents/quiz.py backend/tests/test_quiz_routes.py
git commit -m "feat(quiz): ground quiz generation in catalog + document-RAG course material"
```

---

### Task 2: Eval fixtures + staging seeding helper

**Files:**
- Create: `backend/scripts/fixtures/quiz_grounding/manifest.json` (labeled ground truth)
- Create: `backend/scripts/fixtures/quiz_grounding/README.md` (how to regenerate)
- Create: `backend/scripts/fixtures/quiz_grounding/gold_labels.json` (human calibration set — starts empty, filled in Task 5)
- Create: `backend/scripts/seed_quiz_fixture.py` (seeds fixture docs into a staging TEST course + a concept node)

**Interfaces:**
- Produces: a staging TEST offering/course whose `course_chunks` contain the fixture material, plus `manifest.json` consumed by Tasks 3-5 with this schema:
  ```
  {
    "bu_course_code": "TEST QG 101",
    "concepts": [
      {"concept_name": "...", "kind": "rich|thin|adversarial",
       "relevant_chunk_substrings": ["...", "..."],   # for Layer 1 P/R
       "on_scope_topics": ["..."], "off_scope_topics": ["..."]},
      ...
    ],
    "off_scope_probe_concepts": ["quantum error correction", ...]
  }
  ```

- [ ] **Step 1: Write the fixture manifest**

Create `backend/scripts/fixtures/quiz_grounding/manifest.json` with at least 4 concepts spanning the required kinds. Fill `relevant_chunk_substrings` with verbatim phrases you will put in the seed documents. Example (replace bracketed content with real material you author):

```json
{
  "bu_course_code": "TEST QG 101",
  "concepts": [
    {"concept_name": "dynamic programming", "kind": "rich",
     "relevant_chunk_substrings": ["overlapping subproblems", "memoization table"],
     "on_scope_topics": ["memoization", "tabulation", "optimal substructure"],
     "off_scope_topics": ["quantum annealing"]},
    {"concept_name": "amortized analysis", "kind": "thin",
     "relevant_chunk_substrings": ["aggregate method"],
     "on_scope_topics": ["potential method", "accounting method"],
     "off_scope_topics": ["floating-point rounding"]},
    {"concept_name": "trees", "kind": "adversarial",
     "relevant_chunk_substrings": ["binary search tree", "tree traversal"],
     "on_scope_topics": ["BST", "balanced trees", "traversal"],
     "off_scope_topics": ["phylogenetic trees", "photosynthesis"]}
  ],
  "off_scope_probe_concepts": ["quantum error correction", "cellular respiration"]
}
```

- [ ] **Step 2: Author the seed documents**

Create one or more `.md`/`.txt` files under `backend/scripts/fixtures/quiz_grounding/docs/` whose text contains every `relevant_chunk_substrings` phrase verbatim, structured with `\n\n` block breaks (so `chunk_document` splits them cleanly). Keep "thin" concepts genuinely thin (one sentence) and "rich" concepts thorough (a few paragraphs). Document in `README.md` that substrings in the manifest MUST appear verbatim in these docs.

- [ ] **Step 3: Write the seeding script**

Create `backend/scripts/seed_quiz_fixture.py`:

```python
"""Seed the quiz-grounding fixture into a staging TEST course.

Idempotent: upserts course_chunks by content hash and reuses a fixed
course/offering/concept-node id set. Run from backend/:
    python scripts/seed_quiz_fixture.py
Reads .env.staging.
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env.staging")
sys.path.insert(0, str(BASE))

from db.connection import table                       # noqa: E402
from services.chunker import chunk_document           # noqa: E402
from services.rag_service import index_document_chunks  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "quiz_grounding"
MANIFEST = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
BU_CODE = MANIFEST["bu_course_code"]
DOC_ID = "quizfix-doc-0001"
UPLOADER = "quizfix-user-0001"


def main() -> None:
    texts = []
    for p in sorted((FIX / "docs").glob("*")):
        texts.append(p.read_text(encoding="utf-8"))
    full_text = "\n\n".join(texts)
    chunks = chunk_document(full_text)
    count = index_document_chunks(BU_CODE, DOC_ID, UPLOADER, chunks)
    print(f"Seeded {count} chunks for {BU_CODE} (doc {DOC_ID}).")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Seed staging and verify**

```
cd backend
.\venv\Scripts\python.exe scripts/seed_quiz_fixture.py
```
Expected: `Seeded N chunks for TEST QG 101 (doc quizfix-doc-0001).` with N ≥ number of fixture blocks. Then verify retrieval works:
```
.\venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('.env.staging'); import sys; sys.path.insert(0,'.'); from services.rag_service import retrieve_chunks; print(len(retrieve_chunks('dynamic programming', course_id='TEST QG 101', k=5)))"
```
Expected: a non-zero count.

- [ ] **Step 5: Create the empty gold-labels file**

Create `backend/scripts/fixtures/quiz_grounding/gold_labels.json` with `{"labels": []}` (populated in Task 5).

- [ ] **Step 6: Commit**

```
git add backend/scripts/fixtures/quiz_grounding backend/scripts/seed_quiz_fixture.py
git commit -m "test(quiz): quiz-grounding eval fixtures + staging seeding script"
```

---

### Task 3: `benchmark_quiz.py` Layer 1 — retrieval precision/recall@k

**Files:**
- Create: `backend/scripts/benchmark_quiz.py` (Layer 1 only in this task; Layer 2 added in Task 4)

**Interfaces:**
- Consumes: `manifest.json` (Task 2), `services.rag_service.retrieve_chunks`
- Produces: `score_retrieval(concept: dict, chunks: list[dict]) -> dict` returning `{"recall": float, "precision": float, "hits": int, "expected": int}`; a `--chunks-only` CLI mode

- [ ] **Step 1: Write the Layer 1 scorer + a unit test for it**

Create `backend/tests/test_benchmark_quiz.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from benchmark_quiz import score_retrieval


def test_recall_and_precision():
    concept = {"relevant_chunk_substrings": ["memoization table", "overlapping subproblems"]}
    chunks = [
        {"chunk_text": "A memoization table stores results.", "similarity": 0.8},
        {"chunk_text": "Overlapping subproblems recur.", "similarity": 0.7},
        {"chunk_text": "Unrelated text about sorting.", "similarity": 0.6},
    ]
    r = score_retrieval(concept, chunks)
    assert r["recall"] == 1.0          # both expected substrings found
    assert abs(r["precision"] - 2/3) < 1e-6  # 2 of 3 returned chunks relevant


def test_zero_recall_when_missing():
    concept = {"relevant_chunk_substrings": ["red-black tree"]}
    chunks = [{"chunk_text": "quicksort partitions", "similarity": 0.9}]
    r = score_retrieval(concept, chunks)
    assert r["recall"] == 0.0
    assert r["precision"] == 0.0
```

- [ ] **Step 2: Run it to confirm it fails**

```
cd backend
.\venv\Scripts\python.exe -m pytest tests/test_benchmark_quiz.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'benchmark_quiz'`.

- [ ] **Step 3: Implement `benchmark_quiz.py` with Layer 1**

Create `backend/scripts/benchmark_quiz.py`:

```python
"""Quiz-grounding benchmark (two layers).

Layer 1: retrieval precision/recall@k for each fixture concept.
Layer 2 (Task 4): judged grounding/scope/correctness of generated quizzes.

Run from backend/ (reads .env.staging):
    python scripts/benchmark_quiz.py --chunks-only   # Layer 1 only
    python scripts/benchmark_quiz.py                 # both layers
"""
import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp1252 guard

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
from dotenv import load_dotenv
load_dotenv(BASE / ".env.staging")

from services.rag_service import retrieve_chunks  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "quiz_grounding"
MANIFEST = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
BU_CODE = MANIFEST["bu_course_code"]


def score_retrieval(concept: dict, chunks: list[dict]) -> dict:
    """recall = fraction of expected substrings present in any returned chunk;
    precision = fraction of returned chunks that contain any expected substring."""
    expected = concept.get("relevant_chunk_substrings", [])
    texts = [c.get("chunk_text", "") for c in chunks]
    hits = sum(1 for sub in expected if any(sub in t for t in texts))
    relevant_returned = sum(1 for t in texts if any(sub in t for sub in expected))
    recall = hits / len(expected) if expected else 0.0
    precision = relevant_returned / len(texts) if texts else 0.0
    return {"recall": recall, "precision": precision,
            "hits": hits, "expected": len(expected)}


def run_layer1() -> list[dict]:
    print("=" * 60)
    print("LAYER 1 — RETRIEVAL PRECISION/RECALL@k")
    print("=" * 60)
    results = []
    for concept in MANIFEST["concepts"]:
        name = concept["concept_name"]
        chunks = retrieve_chunks(name, course_id=BU_CODE, k=5)
        s = score_retrieval(concept, chunks)
        results.append({"concept": name, **s})
        print(f"  [{concept['kind']:11}] {name:28} "
              f"recall={s['recall']:.2f} precision={s['precision']:.2f}")
    mean_r = sum(r["recall"] for r in results) / len(results)
    mean_p = sum(r["precision"] for r in results) / len(results)
    print(f"\n  Mean recall={mean_r:.2f}  mean precision={mean_p:.2f}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks-only", action="store_true")
    parser.add_argument("--runs-per-concept", type=int, default=1)  # used by Layer 2
    args = parser.parse_args()
    run_layer1()
    if args.chunks_only:
        print("\n(Layer 2 skipped — remove --chunks-only to run it)")
        return
    # Layer 2 wired in Task 4.


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the unit test — verify it passes**

```
.\venv\Scripts\python.exe -m pytest tests/test_benchmark_quiz.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Run Layer 1 against staging**

```
.\venv\Scripts\python.exe scripts/benchmark_quiz.py --chunks-only
```
Expected: each fixture concept prints recall/precision; rich concepts should show recall 1.0.

- [ ] **Step 6: Commit**

```
git add backend/scripts/benchmark_quiz.py backend/tests/test_benchmark_quiz.py
git commit -m "test(quiz): benchmark_quiz Layer 1 — retrieval precision/recall@k"
```

---

### Task 4: `benchmark_quiz.py` Layer 2 — judged grounding, scope, correctness

**Files:**
- Modify: `backend/scripts/benchmark_quiz.py` (add Layer 2 + judge)
- Modify: `backend/tests/test_benchmark_quiz.py` (add judge-aggregation unit tests)

**Interfaces:**
- Consumes: `manifest.json`, `_quiz_via_agent` (routes/quiz.py, Task 1), `services.gemini_service.call_gemini_json`, fixture material text
- Produces:
  - `judge_question(question: dict, material: str, n_votes: int, model: str) -> dict` returning `{"grounded": bool, "on_scope": bool, "answer_correct": bool, "evidence": str}` (majority over `n_votes`)
  - `aggregate(verdicts: list[dict]) -> dict` returning `{"grounded_ratio", "off_scope_count", "correctness_rate"}`
  - `generate_quiz_for(concept_name: str) -> list[dict]` — drives `_quiz_via_agent` directly against staging

- [ ] **Step 1: Write judge-aggregation unit tests**

Add to `backend/tests/test_benchmark_quiz.py`:

```python
from benchmark_quiz import aggregate, majority_vote


def test_majority_vote_true():
    votes = [{"grounded": True}, {"grounded": True}, {"grounded": False}]
    assert majority_vote(votes, "grounded") is True


def test_aggregate_metrics():
    verdicts = [
        {"grounded": True, "on_scope": True, "answer_correct": True},
        {"grounded": True, "on_scope": True, "answer_correct": False},
        {"grounded": False, "on_scope": False, "answer_correct": True},
    ]
    a = aggregate(verdicts)
    assert abs(a["grounded_ratio"] - 2/3) < 1e-6
    assert a["off_scope_count"] == 1
    assert abs(a["correctness_rate"] - 2/3) < 1e-6
```

- [ ] **Step 2: Run to confirm failure**

```
.\venv\Scripts\python.exe -m pytest tests/test_benchmark_quiz.py -v
```
Expected: FAIL — `ImportError: cannot import name 'aggregate'`.

- [ ] **Step 3: Add the judge + Layer 2 to `benchmark_quiz.py`**

Add these imports at the top of `benchmark_quiz.py` (after the existing ones):

```python
import asyncio  # noqa: E402
from services.gemini_service import call_gemini_json  # noqa: E402
from routes.quiz import _quiz_via_agent  # noqa: E402

# Judge uses a DIFFERENT (stronger) model than the quiz generator to avoid
# self-preference bias. gemini-2.5-pro judges; the quiz agent runs on
# model_for("quiz"). If gemini_service exposes no model override, set the
# model via its config; document the exact judge model in the run output.
JUDGE_MODEL = "gemini-2.5-pro"
```

Add the judge and aggregation functions:

```python
def majority_vote(votes: list[dict], key: str) -> bool:
    trues = sum(1 for v in votes if v.get(key))
    return trues > len(votes) / 2


_JUDGE_PROMPT = (
    "You are grading ONE quiz question against the course material below.\n"
    "Return strict JSON: {{\"grounded\": bool, \"on_scope\": bool, "
    "\"answer_correct\": bool, \"evidence\": string}}.\n"
    "- grounded: true ONLY if the question's content is supported by the "
    "material. Put the exact supporting quote in `evidence`, or set evidence "
    "to \"NOT IN MATERIAL\" and grounded=false.\n"
    "- on_scope: false if the question tests a topic the course clearly does "
    "not cover (off-syllabus). Foundational, on-topic content counts as "
    "on_scope=true even if not verbatim in the material.\n"
    "- answer_correct: true only if the marked correct_answer is actually "
    "correct for the question.\n\n"
    "COURSE MATERIAL:\n{material}\n\n"
    "QUESTION: {question}\nOPTIONS: {options}\nMARKED CORRECT: {correct}\n"
)


def judge_question(question: dict, material: str, n_votes: int, model: str) -> dict:
    votes = []
    prompt = _JUDGE_PROMPT.format(
        material=material[:8000],
        question=question["question"],
        options=question.get("options", question.get("choices", [])),
        correct=question.get("correct_answer", question.get("answer", "")),
    )
    for _ in range(n_votes):
        try:
            v = call_gemini_json(prompt, model=model)
        except TypeError:
            v = call_gemini_json(prompt)  # gemini_service without model kwarg
        except Exception:
            v = {"grounded": False, "on_scope": True, "answer_correct": False,
                 "evidence": "JUDGE ERROR"}
        votes.append(v)
    return {
        "grounded": majority_vote(votes, "grounded"),
        "on_scope": majority_vote(votes, "on_scope"),
        "answer_correct": majority_vote(votes, "answer_correct"),
        "evidence": votes[0].get("evidence", ""),
    }


def aggregate(verdicts: list[dict]) -> dict:
    n = len(verdicts) or 1
    return {
        "grounded_ratio": sum(1 for v in verdicts if v["grounded"]) / n,
        "off_scope_count": sum(1 for v in verdicts if not v["on_scope"]),
        "correctness_rate": sum(1 for v in verdicts if v["answer_correct"]) / n,
    }


def generate_quiz_for(concept_name: str) -> list[dict]:
    """Drive the real quiz agent against staging for a fixture concept.
    Uses fixed fixture ids; the agent's history/mastery tools tolerate an
    unseeded node (they return empty). `course_id=FIXTURE_COURSE_ID` is the
    fixture `courses` row seeded by `seed_quiz_fixture.py`, so grounding
    resolves the real `bu_code` and exercises the production path."""
    return asyncio.run(_quiz_via_agent(
        user_id="quizfix-user-0001",
        course_id=FIXTURE_COURSE_ID,  # seeded fixture course → resolves bu_code
        concept_node_id="quizfix-node-0001",
        concept_name=concept_name,
        num_questions=4,
        difficulty="medium",
        use_shared_context=False,
        request_id="quizfix-bench",
    ))
```

Note on `generate_quiz_for`: grounding needs a real `course_id` to resolve
`bu_code`, so pass the seeded fixture course UUID (`FIXTURE_COURSE_ID`, exported
by `seed_quiz_fixture.py`) — not `None`. The seed script upserts that `courses`
row (course_code `TEST QG 101`) before the benchmark runs, so the lookup
resolves the real `bu_code` rather than needing a patch.

Extend `main()` to run Layer 2 after Layer 1 (when `--chunks-only` is absent):

```python
    # ---- Layer 2 ----
    material = "\n\n".join(
        p.read_text(encoding="utf-8") for p in sorted((FIX / "docs").glob("*"))
    )
    print("\n" + "=" * 60)
    print(f"LAYER 2 — QUIZ GROUNDING/SCOPE/CORRECTNESS (judge={JUDGE_MODEL})")
    print("=" * 60)
    for concept in MANIFEST["concepts"]:
        name = concept["concept_name"]
        all_verdicts = []
        for _ in range(args.runs_per_concept):
            questions = generate_quiz_for(name)
            for q in questions:
                all_verdicts.append(judge_question(q, material, n_votes=3, model=JUDGE_MODEL))
        a = aggregate(all_verdicts)
        gate = "PASS" if (a["grounded_ratio"] >= 0.6 and a["off_scope_count"] == 0
                          and a["correctness_rate"] >= 0.95) else "FAIL"
        print(f"  [{gate}] {name:28} grounded={a['grounded_ratio']:.2f} "
              f"off_scope={a['off_scope_count']} correct={a['correctness_rate']:.2f}")
```

- [ ] **Step 4: Run the aggregation unit tests — verify pass**

```
.\venv\Scripts\python.exe -m pytest tests/test_benchmark_quiz.py -v
```
Expected: all PASS (Layer 1 tests + `test_majority_vote_true` + `test_aggregate_metrics`).

- [ ] **Step 5: Run the full benchmark against staging**

```
.\venv\Scripts\python.exe scripts/benchmark_quiz.py
```
Expected: Layer 1 table, then Layer 2 per-concept grounded/off_scope/correct with PASS/FAIL gates. Rich concepts should show grounded ≥ 0.6, off_scope = 0.

- [ ] **Step 6: Commit**

```
git add backend/scripts/benchmark_quiz.py backend/tests/test_benchmark_quiz.py
git commit -m "test(quiz): benchmark_quiz Layer 2 — judged grounding/scope/correctness"
```

---

### Task 5: Judge calibration against human labels

**Files:**
- Modify: `backend/scripts/benchmark_quiz.py` (add `--calibrate` mode)
- Modify: `backend/scripts/fixtures/quiz_grounding/gold_labels.json` (fill with human labels)

**Interfaces:**
- Consumes: `judge_question` (Task 4), `gold_labels.json`
- Produces: `--calibrate` CLI mode printing judge-vs-human agreement per dimension; `calibration_agreement(judge: list[dict], gold: list[dict]) -> dict`

- [ ] **Step 1: Write the agreement unit test**

Add to `backend/tests/test_benchmark_quiz.py`:

```python
from benchmark_quiz import calibration_agreement


def test_calibration_agreement():
    judge = [{"grounded": True, "on_scope": True, "answer_correct": True},
             {"grounded": False, "on_scope": True, "answer_correct": True}]
    gold = [{"grounded": True, "on_scope": True, "answer_correct": True},
            {"grounded": True, "on_scope": True, "answer_correct": True}]
    a = calibration_agreement(judge, gold)
    assert a["grounded"] == 0.5      # 1 of 2 agree
    assert a["on_scope"] == 1.0
    assert a["answer_correct"] == 1.0
```

- [ ] **Step 2: Run to confirm failure**

```
.\venv\Scripts\python.exe -m pytest tests/test_benchmark_quiz.py::test_calibration_agreement -v
```
Expected: FAIL — `ImportError: cannot import name 'calibration_agreement'`.

- [ ] **Step 3: Implement calibration**

Add to `benchmark_quiz.py`:

```python
def calibration_agreement(judge: list[dict], gold: list[dict]) -> dict:
    """Fraction of items where judge verdict matches the human label, per dimension."""
    n = len(gold) or 1
    dims = ["grounded", "on_scope", "answer_correct"]
    return {d: sum(1 for j, g in zip(judge, gold) if j[d] == g[d]) / n for d in dims}


def run_calibrate() -> None:
    gold = json.loads((FIX / "gold_labels.json").read_text(encoding="utf-8"))["labels"]
    if not gold:
        print("gold_labels.json is empty — label ~20 questions first (see README).")
        return
    material = "\n\n".join(
        p.read_text(encoding="utf-8") for p in sorted((FIX / "docs").glob("*"))
    )
    judge = [judge_question(item["question_obj"], material, n_votes=3, model=JUDGE_MODEL)
             for item in gold]
    human = [{k: item[k] for k in ("grounded", "on_scope", "answer_correct")} for item in gold]
    agree = calibration_agreement(judge, human)
    print(f"Judge agreement vs human ({len(gold)} labels): {agree}")
    for d, v in agree.items():
        flag = "OK" if v >= 0.8 else "LOW — judge unreliable on this dimension"
        print(f"  {d}: {v:.2f}  [{flag}]")
```

Wire into `main()`: add `parser.add_argument("--calibrate", action="store_true")` and, at the top of `main()` after parsing, `if args.calibrate: run_calibrate(); return`.

- [ ] **Step 4: Run the unit test — verify pass**

```
.\venv\Scripts\python.exe -m pytest tests/test_benchmark_quiz.py -v
```
Expected: all PASS.

- [ ] **Step 5: Populate the gold set (human labeling)**

Generate a batch of questions (`python scripts/benchmark_quiz.py` and copy questions from the run, or add a temporary dump), then hand-label ~20 in `gold_labels.json`:

```json
{"labels": [
  {"question_obj": {"question": "...", "options": ["..."], "correct_answer": "..."},
   "grounded": true, "on_scope": true, "answer_correct": true},
  ...
]}
```
Document the labeling rubric in `README.md` (grounded = supported by fixture material; on_scope = not off-syllabus; answer_correct = marked answer is right).

- [ ] **Step 6: Run calibration against staging**

```
.\venv\Scripts\python.exe scripts/benchmark_quiz.py --calibrate
```
Expected: per-dimension agreement printed. If any dimension < 0.80, revise `_JUDGE_PROMPT` and re-run — the eval is only trustworthy once the judge agrees with human labels.

- [ ] **Step 7: Commit**

```
git add backend/scripts/benchmark_quiz.py backend/scripts/fixtures/quiz_grounding/gold_labels.json backend/scripts/fixtures/quiz_grounding/README.md
git commit -m "test(quiz): judge calibration against human-labeled gold set"
```

---

## Self-Review

**Spec coverage:**
- ✅ Grounding injection in `_quiz_via_agent` (best-effort, catalog + document chunks) — Task 1
- ✅ Fallback never blocks a quiz — Task 1 (tests: empty retrieval, no course_id, retrieval raises)
- ✅ Gated "mostly-grounded, on-scope" system-prompt instruction — Task 1 Step 6
- ✅ Hermetic unit tests for injection/fallback — Task 1
- ✅ Diverse + adversarial + off-scope fixtures — Task 2
- ✅ Layer 1 retrieval precision/recall@k — Task 3
- ✅ Layer 2 panel judge + evidence citation + judge≠generator + answer-correctness + continuous metrics + coarse gates — Task 4
- ✅ Non-determinism dial (`--runs-per-concept`) — Task 4
- ✅ Human calibration gold set + agreement check — Task 5

**Type consistency:**
- `_resolve_bu_code(course_id) -> str | None`, `_course_material_block(course_id, concept_name) -> str` — defined Task 1, used by Task 4's grounding path ✓
- `score_retrieval` (Task 3), `judge_question`/`aggregate`/`majority_vote` (Task 4), `calibration_agreement` (Task 5) — each defined before use ✓
- `retrieve_chunks(query, course_id, k, min_similarity)` signature matches rag_service ✓
- Fixture `manifest.json` schema consistent across Tasks 2-5 ✓

**Open decision flagged for implementer:** `JUDGE_MODEL = "gemini-2.5-pro"` must differ from `model_for("quiz")`; confirm `call_gemini_json` accepts a model override (the judge code handles both signatures). If the quiz generator already runs on 2.5-pro, pick a different judge tier.

**No placeholders:** all steps contain runnable code/commands. Fixture *content* (document text, gold labels) is authored by the implementer against the documented schema — this is data, not code, and the schema + examples are fully specified.
