# Spec: Flashcard generation/import → agent (#146)

## Context

Agent-migration epic (#152), milestone #2. Five raw `call_gemini*` flashcard seams remain, all producing
`{front, back}` card lists from a text prompt (the image path OCRs to markdown *first*, so it's text-in too):

- `services/flashcard_import_service.py` — `call_gemini(prompt, json_mode=True)` in
  `extract_cards_from_image`, `gemini_generate_cards`, `gemini_cleanup_cards`, `gemini_cloze` (+ import at :25).
- `services/gemini_service.py:175` — `generate_flashcards(...)` (the main AI-generation path),
  imported by `routes/flashcards.py:15` as `_generate`.

`run_agent_sync` (from #147/#296) is on `main` for these sync services. Card shape is `Card = {front, back}`.

## Goal

All flashcard generation/import runs through one Pydantic AI `flashcard_agent`. No `gemini_service` import
remains in the flashcard path (`flashcard_import_service.py`, `routes/flashcards.py`).

## Requirements

### R1 — Flashcard agent
- Add `agents/flashcard.py`: `FlashCard = {front: str, back: str}`, `Flashcards = {cards: list[FlashCard]}`,
  `flashcard_agent = Agent[..., Flashcards]`. Register `flashcard` in `_providers` (`gemini-2.5-flash`).
- The agent's system prompt is generic ("produce front/back study cards"); each call passes the existing
  rendered prompt template as the user message (task-specific instructions already live in those templates).

### R2 — Shared runner + migrate the 4 import functions
- Add `flashcard_import_service._run_flashcard_agent(prompt: str) -> list[Card]`: runs the agent via
  `run_agent_sync`, returns `{front, back}` dicts with empty-front/back filtered out (preserving
  `_parse_card_json`'s filtering), and **degrades to `[]` on agent failure** (preserving the old
  "bad output → []" resilience — no raise).
- Rewire each function onto it:
  - `extract_cards_from_image`: empty OCR markdown → `[]` (unchanged); else `_run_flashcard_agent(prompt)`.
  - `gemini_generate_cards`: `_run_flashcard_agent(prompt)`.
  - `gemini_cleanup_cards`: `out = _run_flashcard_agent(prompt); return out if out else cards`
    (unchanged fallback-to-input behavior).
  - `gemini_cloze`: `_run_flashcard_agent(prompt)`.
- Remove `from services.gemini_service import call_gemini`.

### R3 — Move the main generation path onto the agent
- Add `flashcard_import_service.generate_flashcards(topic, count, context, documents, weak_concepts) -> list[dict]`
  — the prompt-building moved verbatim from `gemini_service.generate_flashcards`, then `_run_flashcard_agent(prompt)`.
- `routes/flashcards.py:15` imports `generate_flashcards` from `flashcard_import_service` (not `gemini_service`).
- Remove `generate_flashcards` from `services/gemini_service.py` (only `routes/flashcards.py` imported it;
  it is not otherwise referenced or tested).

### R4 — Behavior/contract preserved
- Every function still returns the same `list[{front, back}]` shape. `gemini_cleanup_cards` still falls back
  to its input on empty/failed cleanup. `extract_cards_from_image` still short-circuits on empty OCR.
- Route endpoints (`/flashcards/generate`, `/import/parse`, `/import/generate`) unchanged in signature/response;
  route tests that patch the whole functions keep working.

### R5 — Tests
- `tests/test_flashcard_import_service.py`: rewrite the 7 `patch("...call_gemini")` sites to patch
  `flashcard_import_service.flashcard_agent.run` (AsyncMock returning a `Flashcards`), asserting the same
  returned card lists. Repoint the two "invalid response" cases: `gemini_generate_cards` on agent failure → `[]`;
  `gemini_cleanup_cards` on agent failure → the input cards. Keep the empty-OCR test (agent not called).
- Add a test for `flashcard_import_service.generate_flashcards` (agent path → card dicts; the built prompt
  carries topic/weak-concept context).
- Agent runs mocked; no live Gemini.

## Acceptance criteria (verifiable)
1. `grep -rn "call_gemini\|from services.gemini_service" backend/services/flashcard_import_service.py backend/routes/flashcards.py`
   → no matches.
2. `agents/flashcard.py` exists (`flashcard_agent`, `Flashcards`/`FlashCard`, `metadata` with `prompt_version`+`agent`);
   `_providers` `AgentTask`+`_DEFAULTS` include `flashcard`.
3. The 4 import functions + `generate_flashcards` return `list[{front, back}]` via the agent; `_run_flashcard_agent`
   filters empties and returns `[]` on agent failure (tests).
4. `gemini_cleanup_cards` falls back to input on failed cleanup; `extract_cards_from_image` returns `[]` on empty OCR
   without calling the agent (tests).
5. `routes/flashcards.py` imports `generate_flashcards` from `flashcard_import_service`; `gemini_service.py` no longer
   defines it.
6. `python -m pytest tests/test_flashcard_import_service.py tests/test_flashcard_import_routes.py tests/test_gemini_service.py -q`
   passes; full `python -m pytest tests/ -q` shows no new failures vs `main`.
7. `ruff check .` passes for changed files.

## Out of scope
- The non-LLM parsers (`parse_xlsx`, `parse_anki_apkg`, `scrape_quizlet_url`, `dedup_against_existing`) — unchanged.
- Deleting the rest of `services/gemini_service.py` (#151).
