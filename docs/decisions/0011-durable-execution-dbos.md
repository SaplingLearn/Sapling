# 0011: Durable execution via DBOS (deferred design)

- Status: proposed (deferred — design only, no implementation)
- Date: 2026-05-04
- Supersedes: none

## Context

The agentic upload pipeline is in-memory only. If the FastAPI worker process dies mid-upload — pod restart, OOM kill, deploy rollover — the user's upload is lost. They retry from scratch, paying for OCR + classifier + workers + graph update again. The fallback path (`_legacy_upload_pipeline`) is the same shape; it isn't durable either.

For a tutoring app at our current scale this is acceptable: a few users a week hit a flaky upload, the cost of re-running is bounded, and the user's mental model is "uploads can fail." For the trajectory the product is on (more users, larger documents, more steps in the pipeline once the chat tutor agent ships), it stops being acceptable.

Pydantic AI has first-class integrations with two durable-execution frameworks: **DBOS** and **Temporal**. The plan ADR 0001 referenced flagged this as a future option; this ADR makes the choice explicit.

## Proposed design (not implemented)

Adopt DBOS Transact (`pydantic-ai-dbos`):
- Wrap each agent run as a DBOS step (`@dbos.step()`).
- Wrap `process_document` as a DBOS workflow (`@dbos.workflow()`).
- Each step's output is checkpointed to Postgres on completion.
- If the worker crashes mid-pipeline, restart from the last completed step on resume — no re-running of already-completed worker calls.

DBOS over Temporal because:
- DBOS is in-process — no separate worker tier, no queue infrastructure beyond Postgres (which we already run via Supabase).
- The Sapling codebase is already Postgres-anchored; DBOS reads from the same database.
- Pydantic itself uses DBOS in `pydantic-ai-dbos` (their first-party demo), so the integration is well-tested.
- Temporal is more powerful but operationally heavier for a solo-dev project.

## Why this is deferred, not built

- Schema migration: DBOS adds tables to track workflow state. Need to design how it coexists with Supabase RLS and our column-level encryption (`backend/services/encryption.py`).
- Behavior change: a DBOS workflow can resume a partially-failed run. The current fallback contract assumes either the orchestrator or the legacy path runs cleanly to completion. Resumption means a worker that ran partially before a crash, when retried, must be idempotent. Most of our agent calls are idempotent in practice (LLM call → DB insert), but the `apply_concepts_to_graph` insertion path and Supabase `documents` row write need an explicit idempotency check.
- We have no incidents yet that would justify the operational cost. Today the failure mode is "user retries"; that's tolerable until it isn't.
- Coexistence with the two-phase upload from ADR 0010: if both ship, durable execution wraps the worker job. Doing them simultaneously is too much surface area at once.

## When to revisit

- After the first production incident where a mid-flight upload was lost. The vault entry will be in `docs/attempts/` and will reference this ADR.
- If we add steps that materially change downstream state (e.g. the chat tutor agent spawns a quiz, which creates a session, which mutates user mastery — all in one flow). The cost of re-running compounds.
- If we add streaming charging (per-token billing on the Gemini side hits the user's wallet), making "the user paid for a half-completed run" a real grievance.

## What I'd try next (if implementing)

1. Stand up DBOS in a non-production env first. `uv add pydantic-ai-dbos`, point it at a test Postgres.
2. Migrate `process_document` to a DBOS workflow with each agent run as a step.
3. Add an idempotency key column to `documents` keyed off `X-Request-ID` (already wired per ADR 0009) so a retry of the same logical upload can detect "already saved."
4. Test crash recovery: kill the worker mid-`asyncio.gather(summary, concepts, syllabus)` and confirm the restart picks up at the last step that completed.
5. Sequence after ADR 0010 ships, not before — a queue + durable execution at the same time is two new failure surfaces simultaneously.
