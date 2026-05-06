# SSE and legacy-fallback contracts weren't logged to the vault during Days 4-5

- Date: 2026-05-03
- Related: docs/decisions/0002-vault-structure.md, docs/decisions/0003-implementation-conventions.md

## What I tried

Ran Prompts 13 (route streaming) and 14 (hardening + evals) to completion. Did not run `/log-decision` to capture the contracts that emerged: (a) the streaming route uses `asyncio.create_task(asyncio.to_thread(...))` for post-roll work because FastAPI `BackgroundTasks` doesn't fire for streaming responses; (b) `_legacy_upload_pipeline` is the fallback target on `UsageLimitExceeded`, `UnexpectedModelBehavior`, and any other exception during agent execution. Both contracts ended up only in code comments (`backend/agents/document.py:17`, `backend/routes/documents.py:579`).

## Why it didn't work

The retrospective (Prompt 15) expected `/sync-context` to surface these facts — its "STOP if missing" rule explicitly names them. But `/sync-context` is read-only by design; it can't surface what was never written. Backfilling them into ADR 0003 is fine, but the gap is what mattered: the next fresh agent on Day 4 (had there been one) would have had no vault evidence that those contracts exist.

## What I'd try next

Add an explicit "log decisions to the vault" step inside the body of any prompt that establishes a non-obvious contract — Prompts 13 and 14 in this pack are the obvious candidates, and the same pattern applies to next week's quiz refactor. `/log-decision` should run before the prompt ends, not be deferred to a weekly retrospective. Code comments are a backup, not a substitute. A lightweight alternative: a `/log-decision-from-code` command that grep-greps `# ADR:` markers in code and proposes an ADR draft — automates the lift but adds maintenance and another source of truth, so try the discipline route first.
