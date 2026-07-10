# Design: migrate `/scan-concepts` to a Pydantic AI agent

- Status: proposed
- Date: 2026-07-08
- Area: agent migration (epic #152 — retire `gemini_service` as the primary LLM seam)
- Related: ADR 0001 (adopt Pydantic AI + fallback contract), ADR 0008 (per-task
  model routing), ADR 0003 (compact output schemas), ADR 0016 (wire-format
  adapter convention), ADR 0017 (evals-as-follow-up precedent)

## Context / problem

Sapling calls Gemini two ways: the legacy `services/gemini_service.py`
(`call_gemini*` — build a prompt string, get untyped text back, parse and
coerce defensively) and typed **Pydantic AI agents** under `backend/agents/`
(declare a typed output, the framework enforces and validates it). Epic #152
is the standing decision to move **every** LLM call onto the agent style so
`gemini_service.py` can eventually be deleted.

The document **classify/summarize/extract** step already shipped on agents
(refactor #1, PR #67): both `upload_document_sync` (`routes/documents.py:561`)
and the streaming `upload_document` (`:722–793`) run the agent pipeline, with
`_process_document` / `_legacy_upload_pipeline` kept only as an
exception-time fallback. (The canopy epic's "next step: migrate the
classify/extract step" is stale — that work is done.)

The genuinely **live, non-fallback** un-migrated LLM call left in
`routes/documents.py` is **`/scan-concepts`**. This spec migrates only that
call. It is not a bug fix — scan-concepts works today — it is a
consistency/maintainability migration that removes one of the last live
callers of `gemini_service`.

## Current behavior (what ships today)

The "scan concepts" feature extends a course's knowledge-graph concept set:
look at the concepts already in the graph, ask Gemini which important ones are
missing, and add the new ones as graph nodes.

Two endpoints funnel into one helper:

- `POST /api/documents/doc/{document_id}/scan-concepts` — `scan_document_concepts`
  (`routes/documents.py:1191`) — seeds the scan with a document's stored
  summary + concept notes.
- `POST /api/documents/course/{course_id}/scan-concepts` — `scan_course_concepts`
  (`:1234`) — seeds from the course label + existing graph alone.

Both call `_scan_concepts_for_course` (`:1148`), which:
1. Reads existing `graph_nodes` for `(user_id, course_id)`.
2. Calls `_extend_course_concepts` (`:88`) — **the LLM call being migrated**.
3. Writes any returned names as new nodes via `apply_graph_update`.
4. Returns `{"concepts": [...], "added": N, "existing": M}`.

`_extend_course_concepts` (`:88–154`) is old-style:
- Hand-builds a prompt string embedding the course label, existing concepts,
  and optional doc summary/notes, ending with "Return ONLY valid JSON … `{
  "concepts": ["...", "..."] }` … 0–15 NEW concepts not in the list …".
- `raw = call_gemini_json(prompt, model=MODEL_LITE)` (`:151`) — model
  **hardwired**.
- Defends against malformed output: `if not isinstance(raw, dict): return []`
  then `_coerce_str_list(raw.get("concepts"))`.
- Returns `list[str]` (names only). May be empty.

Both scan handlers are **synchronous** `def` FastAPI handlers.

## Goal & scope

Replace the single Gemini call inside `_extend_course_concepts` with a typed
Pydantic AI agent, preserving behavior exactly.

**In scope**
- New agent `agents/concept_scan.py`.
- Register a `concept_scan` model task in `agents/_providers.py`.
- Route wiring in `routes/documents.py`: agent-first with the existing
  function kept as a legacy fallback.
- Unit tests.

**Out of scope (explicitly deferred)**
- Retiring the upload-path legacy fallback (`_process_document` /
  `_legacy_upload_pipeline`, the `call_gemini_json` at `:226`).
- De-duplicating the streaming upload pipeline vs.
  `agents/document.py::process_document`.
- Any change to the graph write, the endpoints' request/response shapes, or the
  frontend.
- Deleting `gemini_service.py` (still has other callers, incl. this file's
  legacy fallback).

## Design

### 1. New agent — `agents/concept_scan.py`

Modeled on `agents/concept_extraction.py`. A **new** agent rather than reuse of
`concept_extraction_agent` because the task differs materially:
`concept_extraction` takes **raw document text** and must return **≥1** concept
*with descriptions + importance*; scan-concepts takes an **existing concept
list + course label + optional doc summary**, must **avoid duplicates**, and
must be allowed to return **nothing** (`[]`).

```python
class NewConcepts(BaseModel):
    # Names only — matches the graph write's needs and the current list[str]
    # return. Empty list is valid ("existing set already covers it").
    concepts: list[str] = Field(max_length=15)

concept_scan_agent = Agent[SaplingDeps, NewConcepts](
    model=model_for("concept_scan"),
    deps_type=SaplingDeps,
    output_type=NewConcepts,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "concept_scan"},
)
```

Decisions baked in:
- **Output = names only** (`list[str]`). The scan path only consumes concept
  names (`{"concept_name": name, "initial_mastery": 0.0}`); descriptions/
  importance would be discarded. Also keeps the schema flat/small per ADR 0003.
  Revisit only if the feature starts displaying per-concept descriptions.
- **No tools.** The existing-concepts set is a single deterministic query the
  route already runs; there is nothing for the model to decide about fetching
  it. The route fetches it and passes it in the user message. (Matches the
  tool-less worker pattern of `classifier`/`summary`/`concept_extraction`.)
- **System prompt** ported near-verbatim from the current prose prompt (0–15
  new, non-duplicate, short Title Case noun phrases; no assignment titles,
  week labels, page/problem numbers, or administrative items; return `[]` if
  the existing set already covers the material), minus the "return valid JSON"
  instructions the output type now enforces. `_PROMPT_HASH` is the 12-char
  sha256 prefix of the prompt body, surfaced via `metadata` for Logfire, as in
  the other agents.

### 2. Model registration — `agents/_providers.py`

Add the task key so model choice stays config-driven (ADR 0008), defaulting to
the same cheap tier used today (`MODEL_LITE` → flash-lite):

```python
AgentTask = Literal[..., "concept_scan"]
_DEFAULTS = { ..., "concept_scan": "gemini-2.5-flash-lite" }
```

Operator override: `SAPLING_MODEL_CONCEPT_SCAN`, no code change.

### 3. Route wiring — safe swap with legacy fallback

Follows the ADR 0001 / ADR 0016 migration pattern used by the prior four
refactors: run the agent first, fall back to the untouched legacy code on
failure.

- Add `_extend_via_agent(...)` — builds the user message (course label +
  existing concepts + optional doc filename/summary/concept notes), runs
  `concept_scan_agent` with `WORKER_LIMITS`, returns `result.output.concepts`
  (already `list[str]`; the "wire-format adapter" is trivial here).
- Keep the current `_extend_course_concepts` as the **legacy fallback** — same
  name, body unchanged.
- New dispatcher `_extend_concepts(...)`:

```python
def _extend_concepts(...) -> list[str]:
    try:
        return run_agent_sync(_extend_via_agent(...))
    except (UsageLimitExceeded, UnexpectedModelBehavior):
        logger.warning("concept_scan agent guardrails tripped; using legacy")
        return _extend_course_concepts(...)
    except Exception:
        logger.exception("concept_scan agent failed; using legacy")
        return _extend_course_concepts(...)
```

- `_scan_concepts_for_course` (`:1163`) calls `_extend_concepts` instead of
  `_extend_course_concepts` directly. Everything downstream (graph write,
  `added`/`existing` counting, JSON response) is unchanged.
- **Sync bridge:** the scan handlers stay synchronous; the async agent is
  driven via the existing `run_agent_sync(...)` helper (`agents/_run.py`),
  which is the sanctioned sync→async seam. No route signature changes.
- **Deps:** construct `SaplingDeps(user_id, course_id, supabase=None,
  request_id=<correlation id from request.state / current_request_id>)`.
  `supabase=None` is fine — the agent has no tools. `session_id` unused.
- **`WORKER_LIMITS`** applied on the agent run (from `agents/__init__.py`) so
  this call has a token/tool ceiling, avoiding the "no limits" class of
  regression tracked in #327.

### 4. What stays identical
Both endpoints, their request/response shapes, `_scan_concepts_for_course`'s
graph write and `added`/`existing` counts, the decrypt logic for the doc
summary/notes, and the `list[str]` contract between helper and graph write. The
frontend cannot observe the change.

## Testing

Unit tests in `backend/tests/test_concept_scan.py`, mirroring the style of
`test_syllabus_adapter.py` / `test_ocr_pipeline.py`:
- Agent success → returns the model's concept names as `list[str]`.
- Empty result (`[]`) → handled, `added: 0`.
- `/doc/{id}/scan-concepts` and `/course/{id}/scan-concepts` end-to-end with a
  mocked agent (asserting graph write + response shape unchanged).
- Each fallback trigger — `UsageLimitExceeded`, `UnexpectedModelBehavior`,
  generic `Exception` — falls through to `_extend_course_concepts`.
- Duplicate-avoidance is prompt-governed; a light assertion that existing
  concepts are included in the message passed to the agent.

**Evals — deferred (decision).** The four big refactors shipped eval cases; the
notetaker agents (ADR 0017) shipped without and logged it as debt. This is a
low-risk cheap-model call whose legacy-parity is easy to pin with unit tests,
so: unit tests now, a small `tests/evals/concept_scan.py` as a follow-up.

## Files touched
- **New:** `backend/agents/concept_scan.py`, `backend/tests/test_concept_scan.py`
- **Edit:** `backend/agents/_providers.py` (+1 task key + Literal entry),
  `backend/routes/documents.py` (`_extend_via_agent`, `_extend_concepts`
  dispatcher, swap the call in `_scan_concepts_for_course`; keep
  `_extend_course_concepts` as fallback)

The `from services.gemini_service import MODEL_LITE, call_gemini_json` import
(`documents.py:37`) stays as long as the legacy fallback (and `_process_document`)
remain; removing it belongs to the out-of-scope "retire legacy fallback" slice.

## Rollback
Single-revert safe. The legacy path is intact and unchanged; reverting the
dispatcher swap restores the pre-migration behavior. The new agent module and
provider key are additive and dormant if unreferenced.

## Follow-ups (tracked, not in this slice)
1. `tests/evals/concept_scan.py` eval cases.
2. Retire the upload-path legacy fallback (`_process_document` /
   `_legacy_upload_pipeline`), removing the `:226` `call_gemini_json` site.
3. De-duplicate the streaming upload pipeline against
   `agents/document.py::process_document`.
4. Update epic #152 / canopy: the classify/extract step is already migrated.

## Open questions
None blocking. Output-shape (names-only) and evals-deferred are decided above;
flag if either should change before implementation.
