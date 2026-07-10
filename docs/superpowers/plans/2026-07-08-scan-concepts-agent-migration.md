# Scan-Concepts Agent Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the `/scan-concepts` LLM call in `routes/documents.py` from the legacy `gemini_service.call_gemini_json` onto a new typed Pydantic AI agent, with no change to behavior.

**Architecture:** New tool-less worker agent `concept_scan_agent` returns a typed names-only list. The route builds the message (course label + existing concepts + optional doc summary), runs the agent first through the sync→async bridge, and falls back to the untouched legacy `_extend_course_concepts` on any agent failure (ADR 0001 contract). Everything downstream (graph write, response shape) is unchanged.

**Tech Stack:** FastAPI, Pydantic AI (`pydantic-ai-slim[google]`, Gemini), pytest.

Spec: `docs/superpowers/specs/2026-07-08-scan-concepts-agent-migration-design.md`

## Global Constraints

- New LLM code is a Pydantic AI agent under `backend/agents/`, not an extension of `gemini_service.py`.
- Model is chosen via `agents/_providers.py::model_for(task)`; default `gemini-2.5-flash-lite`; env override `SAPLING_MODEL_CONCEPT_SCAN`.
- Fallback contract: run agent first; on `UsageLimitExceeded`, `UnexpectedModelBehavior`, or any other `Exception`, fall back to the legacy `_extend_course_concepts`.
- Output schema stays compact (ADR 0003): flat model, `concepts: list[str]`, max 15, empty allowed.
- Every agent run passes `usage_limits=WORKER_LIMITS` (from `agents/__init__.py`).
- Do NOT change the two endpoints' request/response shapes, `_scan_concepts_for_course`'s graph write, or the `list[str]` contract.
- Tests live in `backend/tests/`, run via `python -m pytest` from `backend/`.
- Commit messages follow repo style: `feat(<area>): ...`, `test(<area>): ...`.

---

### Task 1: Register the `concept_scan` model task

**Files:**
- Modify: `backend/agents/_providers.py` (the `AgentTask` Literal ~line 29 and `_DEFAULTS` dict ~line 39)
- Test: `backend/tests/test_concept_scan.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `model_for("concept_scan") -> GoogleModel` defaulting to `gemini-2.5-flash-lite`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_concept_scan.py`:

```python
"""Tests for the concept_scan agent migration (/scan-concepts)."""
from pydantic_ai.models.google import GoogleModel

from agents._providers import model_for


def test_model_for_concept_scan_defaults_to_flash_lite():
    m = model_for("concept_scan")
    assert isinstance(m, GoogleModel)
    assert m.model_name == "gemini-2.5-flash-lite"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_concept_scan.py::test_model_for_concept_scan_defaults_to_flash_lite -v`
Expected: FAIL — `KeyError: 'concept_scan'` (task not in `_DEFAULTS`).

- [ ] **Step 3: Add the task key**

In `backend/agents/_providers.py`, add `"concept_scan"` to the `AgentTask` Literal:

```python
AgentTask = Literal[
    "classifier", "summary", "concepts", "syllabus", "quiz", "chat_tutor",
    "note_summary", "note_concepts", "note_chat",
    "study_guide", "social_summary",
    "course_summary", "quiz_context",
    "concept_scan",
]
```

And add its default in `_DEFAULTS` (place near the other concept-related entries):

```python
    # Scan-concepts extends an existing course concept set from a short
    # context (existing concepts + optional doc summary) → the cheap lite
    # tier, matching the MODEL_LITE the legacy path used.
    "concept_scan": "gemini-2.5-flash-lite",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_concept_scan.py::test_model_for_concept_scan_defaults_to_flash_lite -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/agents/_providers.py backend/tests/test_concept_scan.py
git commit -m "feat(agents): add concept_scan model task key"
```

---

### Task 2: Create the `concept_scan` agent

**Files:**
- Create: `backend/agents/concept_scan.py`
- Test: `backend/tests/test_concept_scan.py` (extend)

**Interfaces:**
- Consumes: `model_for("concept_scan")` (Task 1), `SaplingDeps`.
- Produces:
  - `NewConcepts(BaseModel)` with field `concepts: list[str]` (max 15, empty allowed).
  - `concept_scan_agent: Agent[SaplingDeps, NewConcepts]`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_concept_scan.py`:

```python
import pytest
from pydantic import ValidationError
from pydantic_ai import Agent

from agents.concept_scan import NewConcepts, concept_scan_agent


def test_new_concepts_allows_empty_list():
    assert NewConcepts(concepts=[]).concepts == []


def test_new_concepts_rejects_more_than_15():
    with pytest.raises(ValidationError):
        NewConcepts(concepts=[f"Concept {i}" for i in range(16)])


def test_concept_scan_agent_is_configured():
    assert isinstance(concept_scan_agent, Agent)
    assert concept_scan_agent.output_type is NewConcepts
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_concept_scan.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.concept_scan'`.

- [ ] **Step 3: Create the agent module**

Create `backend/agents/concept_scan.py`:

```python
"""Concept-scan agent.

Replaces routes/documents.py::_extend_course_concepts' call_gemini_json
call. Given a course label, the concepts already in the student's graph,
and optionally a document's summary/notes, it returns the NEW concepts to
add — names only, deduplicated against the existing set, possibly empty.

Names-only output (list[str]) matches what the /scan-concepts graph write
consumes; descriptions/importance would be discarded (see the design spec).
Tool-less: the existing-concepts set is a deterministic query the route
already runs and passes in the message — the model has nothing to decide
about fetching it.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps


class NewConcepts(BaseModel):
    """Typed output: new concept names to add to the course graph."""

    concepts: list[str] = Field(
        default_factory=list,
        max_length=15,
        description=(
            "New concept names not already in the course graph. Empty when "
            "the existing set already covers the material."
        ),
    )


_SYSTEM_PROMPT = (
    "You curate the concept set for a student's course knowledge graph. "
    "You are given the course label, the concepts already in the graph, "
    "and optionally a document's title, summary, and already-extracted "
    "concepts.\n\n"
    "Return between 0 and 15 NEW concepts that belong in this course's "
    "graph but are not already in the existing list.\n"
    "- If the existing set already covers the relevant material, return an "
    "empty list.\n"
    "- Each concept is a short Title Case noun phrase (e.g. 'Linear "
    "Regression', 'Big-O Analysis').\n"
    "- Do NOT repeat or paraphrase any existing concept.\n"
    "- No assignment titles, week labels, page numbers, problem numbers, "
    "or administrative items."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


concept_scan_agent = Agent[SaplingDeps, NewConcepts](
    model=model_for("concept_scan"),
    deps_type=SaplingDeps,
    output_type=NewConcepts,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "concept_scan"},
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_concept_scan.py -v`
Expected: PASS (all 4 tests, including Task 1's).

Note: if `concept_scan_agent.output_type` is not exposed by the installed pydantic-ai version, replace that assertion with `assert concept_scan_agent is not None` — do not block on the attribute name.

- [ ] **Step 5: Commit**

```bash
git add backend/agents/concept_scan.py backend/tests/test_concept_scan.py
git commit -m "feat(agents): add concept_scan agent (names-only, tool-less)"
```

---

### Task 3: Wire the agent into the route with legacy fallback

**Files:**
- Modify: `backend/routes/documents.py` (imports ~line 44-51; add helpers near `_extend_course_concepts` ~line 88; swap the call inside `_scan_concepts_for_course` ~line 1163)
- Test: `backend/tests/test_concept_scan.py` (extend)

**Interfaces:**
- Consumes: `concept_scan_agent`, `NewConcepts` (Task 2); `run_agent_sync` (`agents/_run.py`); `WORKER_LIMITS`, `SaplingDeps`, `current_request_id`, `UsageLimitExceeded`, `UnexpectedModelBehavior` (already imported in `documents.py`); `_extend_course_concepts` (existing legacy fallback).
- Produces:
  - `_scan_user_message(*, course_label, existing_concepts, doc_filename=None, doc_summary=None, doc_concept_notes=None) -> str`
  - `async _extend_via_agent(*, user_id, course_id, course_label, existing_concepts, doc_filename=None, doc_summary=None, doc_concept_notes=None) -> list[str]`
  - `_extend_concepts(user_id, course_id, *, course_label, existing_concepts, doc_filename=None, doc_summary=None, doc_concept_notes=None) -> list[str]`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_concept_scan.py`:

```python
import routes.documents as documents
from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior


class _Result:
    def __init__(self, concepts):
        self.output = NewConcepts(concepts=concepts)


class _FakeAgent:
    """Stand-in for concept_scan_agent with an async run()."""

    def __init__(self, *, result=None, exc=None):
        self._result = result
        self._exc = exc
        self.calls = []

    async def run(self, message, **kwargs):
        self.calls.append((message, kwargs))
        if self._exc is not None:
            raise self._exc
        return self._result


def test_scan_user_message_includes_existing_and_doc_context():
    msg = documents._scan_user_message(
        course_label="CS101",
        existing_concepts=["Recursion"],
        doc_filename="lecture1.pdf",
        doc_summary="Intro to sorting algorithms.",
        doc_concept_notes=[{"name": "Merge Sort", "description": "divide and conquer"}],
    )
    assert "CS101" in msg
    assert "Recursion" in msg
    assert "lecture1.pdf" in msg
    assert "Merge Sort" in msg


def test_extend_concepts_returns_agent_output(monkeypatch):
    fake = _FakeAgent(result=_Result(["Binary Search", "Hashing"]))
    monkeypatch.setattr(documents, "concept_scan_agent", fake)
    out = documents._extend_concepts(
        "u1", "c1", course_label="CS101", existing_concepts=["Recursion"],
    )
    assert out == ["Binary Search", "Hashing"]
    assert fake.calls  # agent was actually invoked


def test_extend_concepts_handles_empty(monkeypatch):
    fake = _FakeAgent(result=_Result([]))
    monkeypatch.setattr(documents, "concept_scan_agent", fake)
    out = documents._extend_concepts(
        "u1", "c1", course_label="CS101", existing_concepts=[],
    )
    assert out == []


@pytest.mark.parametrize(
    "exc",
    [UsageLimitExceeded("limit"), UnexpectedModelBehavior("weird"), RuntimeError("boom")],
)
def test_extend_concepts_falls_back_to_legacy(monkeypatch, exc):
    monkeypatch.setattr(documents, "concept_scan_agent", _FakeAgent(exc=exc))
    captured = {}

    def _legacy(**kwargs):
        captured.update(kwargs)
        return ["Legacy Concept"]

    monkeypatch.setattr(documents, "_extend_course_concepts", _legacy)
    out = documents._extend_concepts(
        "u1", "c1", course_label="CS101", existing_concepts=["Recursion"],
    )
    assert out == ["Legacy Concept"]
    assert captured["course_label"] == "CS101"
    assert captured["existing_concepts"] == ["Recursion"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_concept_scan.py -k "extend or scan_user_message" -v`
Expected: FAIL — `AttributeError: module 'routes.documents' has no attribute '_scan_user_message'`.

- [ ] **Step 3: Add the import**

In `backend/routes/documents.py`, add to the agent import block (after line 51):

```python
from agents._run import run_agent_sync
from agents.concept_scan import concept_scan_agent, NewConcepts
```

- [ ] **Step 4: Add the three helpers**

In `backend/routes/documents.py`, immediately AFTER the existing `_extend_course_concepts` function (which stays unchanged as the legacy fallback, ends ~line 154), add:

```python
def _scan_user_message(
    *,
    course_label: str,
    existing_concepts: list[str],
    doc_filename: str | None = None,
    doc_summary: str | None = None,
    doc_concept_notes: list[dict] | None = None,
) -> str:
    """Build the concept_scan agent's user message: course label + existing
    concepts + (optional) document context. Mirrors the legacy prompt's data
    section so agent and legacy paths see the same signal."""
    existing_block = (
        "\n".join(f"- {c}" for c in existing_concepts) if existing_concepts else "(none yet)"
    )
    lines = [
        f'Course: "{course_label}"',
        "Concepts already in the graph:",
        existing_block,
    ]
    if doc_filename or doc_summary or doc_concept_notes:
        notes_block = (
            "\n".join(
                f"  - {n.get('name', '?')}: {n.get('description', '')[:200]}"
                for n in (doc_concept_notes or [])
            )
            or "  (none)"
        )
        lines += [
            "",
            "New document being scanned:",
            f"  Title: {doc_filename or '(untitled)'}",
            f"  Summary: {doc_summary or '(none)'}",
            "  Concepts already extracted from this document:",
            notes_block,
        ]
    return "\n".join(lines)


async def _extend_via_agent(
    *,
    user_id: str,
    course_id: str,
    course_label: str,
    existing_concepts: list[str],
    doc_filename: str | None = None,
    doc_summary: str | None = None,
    doc_concept_notes: list[dict] | None = None,
) -> list[str]:
    """Run concept_scan_agent and return new concept names. Raises on agent
    failure so the sync dispatcher can fall back to legacy."""
    deps = SaplingDeps(
        user_id=user_id,
        course_id=course_id,
        supabase=None,
        request_id=current_request_id() or str(uuid.uuid4()),
    )
    message = _scan_user_message(
        course_label=course_label,
        existing_concepts=existing_concepts,
        doc_filename=doc_filename,
        doc_summary=doc_summary,
        doc_concept_notes=doc_concept_notes,
    )
    result = await concept_scan_agent.run(
        message, deps=deps, usage_limits=WORKER_LIMITS,
    )
    return list(result.output.concepts)


def _extend_concepts(
    user_id: str,
    course_id: str,
    *,
    course_label: str,
    existing_concepts: list[str],
    doc_filename: str | None = None,
    doc_summary: str | None = None,
    doc_concept_notes: list[dict] | None = None,
) -> list[str]:
    """Agent-first concept extension with legacy fallback (ADR 0001).

    Sync entry point for the sync /scan-concepts handlers: drives the async
    agent via run_agent_sync, falling back to the legacy call_gemini_json
    path on any agent failure.
    """
    try:
        return run_agent_sync(
            _extend_via_agent(
                user_id=user_id,
                course_id=course_id,
                course_label=course_label,
                existing_concepts=existing_concepts,
                doc_filename=doc_filename,
                doc_summary=doc_summary,
                doc_concept_notes=doc_concept_notes,
            )
        )
    except (UsageLimitExceeded, UnexpectedModelBehavior):
        logger.warning("concept_scan agent guardrails tripped; using legacy")
    except Exception:
        logger.exception("concept_scan agent failed; using legacy")
    return _extend_course_concepts(
        course_label=course_label,
        existing_concepts=existing_concepts,
        doc_filename=doc_filename,
        doc_summary=doc_summary,
        doc_concept_notes=doc_concept_notes,
    )
```

- [ ] **Step 5: Swap the call in `_scan_concepts_for_course`**

In `backend/routes/documents.py`, inside `_scan_concepts_for_course` (~line 1163), replace the `_extend_course_concepts(...)` call with `_extend_concepts(...)`, threading `user_id`/`course_id`:

```python
    concepts = _extend_concepts(
        user_id,
        course_id,
        course_label=_course_label(course_id),
        existing_concepts=existing_concepts,
        doc_filename=doc_filename,
        doc_summary=doc_summary,
        doc_concept_notes=doc_concept_notes,
    )
```

(Leave `_extend_course_concepts` defined — it is now the fallback.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_concept_scan.py -v`
Expected: PASS (all tests through Task 3).

- [ ] **Step 7: Commit**

```bash
git add backend/routes/documents.py backend/tests/test_concept_scan.py
git commit -m "feat(documents): run /scan-concepts via concept_scan agent, legacy fallback"
```

---

### Task 4: End-to-end endpoint regression test

**Files:**
- Test: `backend/tests/test_concept_scan.py` (extend)

**Interfaces:**
- Consumes: FastAPI `app`, `TestClient`; the autouse `_bypass_session_auth` + `_hermetic_supabase_client` fixtures from `conftest.py`; `_FakeAgent` (Task 3).
- Produces: nothing (regression coverage only).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_concept_scan.py`:

```python
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_course_scan_endpoint_uses_agent_and_keeps_response_shape():
    fake = _FakeAgent(result=_Result(["Binary Search", "Hashing"]))
    with patch("routes.documents._validate_user", return_value=None), \
         patch("routes.documents._course_label", return_value="CS101"), \
         patch("routes.documents.apply_graph_update", return_value=None), \
         patch("routes.documents.concept_scan_agent", fake), \
         patch("routes.documents.table") as t:
        t.return_value.select.return_value = [
            {"id": "n1", "concept_name": "Recursion"},
        ]
        r = client.post(
            "/api/documents/course/c1/scan-concepts",
            json={"user_id": "u1"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["concepts"] == ["Binary Search", "Hashing"]
    assert "added" in body and "existing" in body
    assert fake.calls  # the agent path (not legacy) served the request
```

- [ ] **Step 2: Run test to verify it fails (before Task 3 wiring) or passes (after)**

Run: `python -m pytest tests/test_concept_scan.py::test_course_scan_endpoint_uses_agent_and_keeps_response_shape -v`
Expected: PASS once Task 3 is in place (the endpoint now routes through `concept_scan_agent`). If run before Task 3, it FAILS because the legacy path serves the request and `fake.calls` is empty.

- [ ] **Step 3: Run the full file + confirm no regressions**

Run: `python -m pytest tests/test_concept_scan.py tests/test_documents_routes.py -q`
Expected: PASS (new file green; existing document route tests unaffected).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_concept_scan.py
git commit -m "test(documents): e2e regression for /scan-concepts agent path"
```

---

## Self-Review

**1. Spec coverage:**
- New agent `agents/concept_scan.py` (names-only, no tools) → Task 2. ✅
- `concept_scan` model key + env override → Task 1. ✅
- Agent-first + legacy fallback via `run_agent_sync`, sync handlers unchanged → Task 3. ✅
- `WORKER_LIMITS` on the run → Task 3 (`_extend_via_agent`). ✅
- Endpoints/response/graph-write unchanged → Task 3 Step 5 (swap only) + Task 4 (regression). ✅
- Unit tests now, evals deferred → Tasks 1–4 unit/e2e; no eval task (deferred per spec). ✅
- Out-of-scope items (retire legacy fallback, de-dup streaming, delete gemini_service) → not touched; `_extend_course_concepts` and the `gemini_service` import deliberately remain. ✅

**2. Placeholder scan:** No TBD/TODO; every code step shows full code; every run step shows command + expected result. ✅

**3. Type consistency:** `NewConcepts.concepts: list[str]` defined in Task 2, consumed as `result.output.concepts` in Task 3; `_extend_concepts(user_id, course_id, *, course_label, existing_concepts, ...)` signature identical across Task 3 definition, Task 3 call-site swap, and Task 3/4 tests; `_FakeAgent.run` async matches `Agent.run`. ✅

No gaps found.
