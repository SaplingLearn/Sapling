# 0005: Refactor #2 target — quiz generation

- Status: accepted
- Date: 2026-05-03
- Supersedes: none

## Context

With the document upload refactor complete and stable, the next agentic refactor must be picked. Candidates: (a) quiz generation in `backend/routes/quiz.py` — currently a single `gemini_service.call_gemini_json` call with manual misconception/weak-area string augmentation at `routes/quiz.py:82`; (b) chat tutor in `backend/routes/learn.py` — a multi-turn loop with custom system-prompt assembly via `build_system_prompt`; (c) syllabus extraction unification (`routes/documents.py` and `services/calendar_service.py` both have copies of the parsing logic). Quiz is the smallest scope with the most immediate user-visible payoff and the cleanest seam with ADR 0004's tool work.

## Decision

Refactor #2 is `routes/quiz.py::generate_quiz`. Build `backend/agents/quiz.py` with `QuizQuestion` and `Quiz` Pydantic outputs (kept small per ADR 0003 convention 4), register `read_concepts_for_user` and `read_misconceptions_for_course` as tools (per ADR 0004), and replace the misconception-augmentation block at `routes/quiz.py:82`. Streaming is not required for quiz generation — the user is willing to wait without intermediate progress for a single-shot generation. Eval set: 8 cases covering 3 difficulty levels and 2 question types (MCQ + short answer), modeled on `backend/tests/evals/document_classification.py`. Defer chat tutor refactor to refactor #3 (most invasive). Defer syllabus unification to refactor #4 (low-effort cleanup that fits anywhere).

## Consequences

- (+) Quiz generation becomes typed end-to-end; downstream UI can render structured questions instead of parsing strings.
- (+) Misconception use becomes auditable — Logfire traces show which concepts the agent pulled, replacing the opaque `prompt += "..."` augmentation.
- (+) Establishes the pattern for tool-backed agents that prep their own data, paving the way for the chat tutor refactor.
- (−) Quiz generation latency may go up (multiple tool calls vs. one Gemini call). Acceptable for a non-streaming, post-study flow.
- (−) Existing quiz cache logic (`quiz_context_service`) must be preserved during migration. Cache key = (user, course, settings); the agent must produce deterministic outputs given fixed inputs, OR the cache must be invalidated when the agent version changes. Decide which at refactor time.
