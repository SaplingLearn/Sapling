# 0011: Durable execution via DBOS (shipped + validated, default off)

- Status: accepted (shipped + validated, default off)
- Date: 2026-05-04
- Supersedes: none

## Update (2026-07-30, #154)

Closed every gap the 2026-05-04 update below left open (its own text noted
"the parts that haven't shipped: test coverage, real production
validation, monitoring of resume behavior" — this update ships all three).

1. **Entrypoint wiring was missing.** `backend/services/durable.py`'s
   decorators could go real (`DBOS_ENABLED=true` + `dbos` importable) with
   no `DBOS` instance ever constructed or `.launch()`ed anywhere in
   `main.py` — durability looked wired from the decorators alone but did
   nothing at call time. Fixed: `backend/main.py`'s `_lifespan` now calls
   `services.durable.init_dbos()` right after the #174 secrets validation
   and before `yield`, and `shutdown_dbos()` in the shutdown path.
2. **The `DBOS_DATABASE_URL` precondition is now enforced, not just
   documented.** `is_durable()` requires ALL THREE of `DBOS_ENABLED=true`,
   `dbos` importable, AND `DBOS_DATABASE_URL` non-empty. The flag-on-but-
   no-URL case now degrades to passthrough with a logged warning instead of
   silently doing nothing (the code previously didn't check the URL at
   all, despite the module docstring claiming it did).
3. **`backend/requirements-durable.txt` now exists** (`dbos>=2.28,<3`,
   pinned to the version this update's verification ran against). Never
   added to `requirements.txt`/`requirements.lock` — durability stays
   opt-in and the hermetic suite runs with `dbos` NOT installed.
4. **Test coverage, previously zero, now covers both modes and resume:**
   - `backend/tests/test_durable_shim.py` — hermetic, runs WITHOUT `dbos`
     installed. Reloads the shim under every precondition combination
     (flag off, flag on + import failure, flag on + no URL, flag on +
     working stub, stub whose `launch()` raises) and asserts passthrough
     byte-compatibility (return values, args/kwargs, exceptions) plus the
     fail-loud contract.
   - `backend/tests/test_dbos_resume.py` — opt-in
     (`RUN_DBOS_RESUME=1`, skipped otherwise; also skips if `dbos` isn't
     installed). A real subprocess crash/resume proof against a live
     Postgres: `test_shim_resume_minimal_workflow` crashes a 2-step
     workflow mid-step-2 (`os._exit(42)`), resumes it in a fresh process,
     and asserts the already-checkpointed step did NOT re-run while the
     crashed step ran to completion exactly once.
     `test_pipeline_identical_with_dbos_on` runs
     `agents.document.process_document` for real under DBOS
     (`SAPLING_MODEL_MODE=function`) and asserts its output matches the
     function-mode constants byte-for-byte — proof that wrapping the
     pipeline in `@durable_workflow`/`@durable_step` changes durability,
     not behavior. Both tests were run against a real `dbos==2.28.0` +
     a throwaway Postgres during this update and passed; see the file
     docstrings for exactly what each does and does not prove.
5. **Activation procedure, corrected against the installed
   `dbos==2.28.0`** (verified directly against the package source in a
   scratch venv; see `backend/services/durable.py::init_dbos`'s docstring
   for the file/line citations):

   a. `pip install -r backend/requirements-durable.txt`.
   b. Provision a reachable Postgres for DBOS's own system database (the
      SAME Postgres instance Supabase/`SUPABASE_DB_URL` uses is fine — DBOS
      creates its own `dbos` schema there; see "System schema" below).
   c. Set `DBOS_ENABLED=true` and `DBOS_DATABASE_URL=postgres://...`.
   d. Restart the FastAPI workers. `init_dbos()` runs in `_lifespan`;
      ANY failure constructing/launching DBOS makes the app FAIL TO START
      (same fail-loud posture as #174's `validate_config()`) rather than
      boot into a silently non-durable state.
   e. ~~Run DBOS migrations (`dbos migrate`)~~ — **this step from the
      2026-05-04 procedure below is STALE and is corrected here**:
      `DBOS.launch()` runs the system-database migrations ITSELF
      (verified in `dbos/_dbos.py::DBOS._launch`, which calls
      `self._sys_db.run_migrations()` before anything else happens). No
      separate `dbos migrate` step is needed for Sapling's setup, where the
      app's DB role has ordinary DDL rights. (`dbos.run_dbos_database_
      migrations()` exists as a standalone helper for the case where it
      doesn't — not exercised here.)
   f. Confirm activation: `services.durable.is_durable()` returns `True`;
      `init_dbos()` logs `"durable execution ACTIVE (DBOS launched)"` at
      startup (or `"durable execution off — passthrough decorators"` in the
      default, off, mode) — both plain `logger.info` calls, so both are
      captured by #119's Logfire app-logging instrumentation with no
      further wiring.

**Resume monitoring.** Beyond the startup INFO log above, `DBOS.launch()`
logs its own recovery activity (`"Recovering N workflows from application
version ..."` / `"No workflows to recover..."`) through the same app-
logging path, so Logfire has it automatically. For a direct look, DBOS's
system database is its own schema (defaults to `dbos`, confirmed from the
installed package's migration DDL in `dbos/_migration.py`) with a
`workflow_status` table (`workflow_uuid`, `status`, `name`, `executor_id`,
`recovery_attempts`, `created_at`/`updated_at` as epoch-ms bigints, …). A
sample query to list resumed/pending workflows:

```sql
select workflow_uuid, name, status, executor_id, recovery_attempts,
       to_timestamp(created_at / 1000.0) as created_at,
       to_timestamp(updated_at / 1000.0) as updated_at
from dbos.workflow_status
where status in ('PENDING', 'ENQUEUED')
   or recovery_attempts > 0
order by created_at desc;
```

`dbos.*` is entirely DBOS-managed — created and migrated by
`DBOS.launch()` itself — and is deliberately OUTSIDE
`backend/db/migrations/`; it is not a Sapling schema, and `python -m
db.migrate` never touches it.

**Streaming-route asymmetry, reaffirmed.** Still intentional (unchanged
from the 2026-05-04 text below): the streaming `POST /api/documents/upload`
route stays non-durable, with X-Request-ID replay as its crash semantic.
That semantic is now more tightly pinned than when this ADR was first
written: PR #464 closed the "#132 remainder" — one `result` SSE event per
streamed upload, ever, with post-result persistence failures always
terminating in `error:failed` + `status:done` rather than a legacy-fallback
second run (routes/documents.py's post-roll comment block, "#154 builds on
this structure — keep persistence in the post-roll, after the result
event"). `tests/test_documents_routes.py::TestUploadIdempotency::
test_streaming_replay_emits_done_without_reprocessing` now asserts (not
just implies) BOTH halves of the #132/#154 acceptance criterion — a crash
after the `result` event leaves exactly one consistent document — directly:
zero agent invocations (`classifier_agent.run` unmocked-but-spied,
`assert_not_called()`) and zero new `documents` inserts
(`t.return_value.insert.assert_not_called()`) on an X-Request-ID replay.

**Still deferred, unchanged:** production incident-driven validation (this
ADR's original "when to revisit" trigger #1 — a real lost mid-flight
upload — hasn't happened, so `DBOS_ENABLED` stays off in every deployed
environment); DBOS Conductor / multi-executor recovery (Sapling runs a
single executor, `executor_id="local"`, so cross-executor recovery
semantics are unexercised by the resume test above); and coexistence with
ADR 0010's two-phase upload if that ever ships (still an open sequencing
question — see that section, unchanged, further down).

## Update (2026-05-04)

`backend/services/durable.py` shipped with `@workflow` and `@step`
decorators that:

- Activate as real DBOS decorators when `DBOS_ENABLED=true` AND the
  `dbos` package is importable AND `DBOS_DATABASE_URL` is set.
- Otherwise no-op as identity passthroughs — code runs identically to
  before this ADR.

`@durable_workflow` is applied to `agents.document.process_document`, so
flipping the flag turns the upload pipeline into a checkpointed DBOS
workflow without further code changes in the route layer. Activation
procedure for operators:

1. `pip install dbos` (added to a future `requirements-durable.txt`,
   not in the default requirements).
2. Provision a Postgres for DBOS metadata (cannot reuse Supabase RLS
   tables; needs its own schema).
3. Set `DBOS_ENABLED=true` and `DBOS_DATABASE_URL=postgres://…`.
4. Run DBOS migrations (`dbos migrate`).
5. Restart the FastAPI workers; `services.durable.is_durable()` should
   return True at startup.

Idempotency keys (per ADR 0009 + the `documents.request_id` migration
in this PR) compose with DBOS — a workflow that crashes mid-flight and
restarts will re-check the idempotency cache before re-running.

The original deferred-design notes below remain accurate for the parts
that haven't shipped (test coverage, real production validation,
monitoring of resume behavior).

### Step granularity (commit 918fdba)

Each agent run inside `_run_workers` is now wrapped with `@durable_step`
(`_step_classify`, `_step_summary`, `_step_concepts`,
`_step_syllabus`). With DBOS active, a worker crash mid-`asyncio.gather`
resumes at the last completed step instead of re-running the whole
workflow.

### Streaming-route asymmetry (intentional)

The streaming `POST /api/documents/upload` route bypasses
`process_document` and calls each agent inline so it can emit SSE
progress events between phases. Those inline calls are NOT wrapped in
the durable workflow — only `/upload/sync` (which calls
`process_document`) gets durability when DBOS is enabled.

This is intentional. SSE connections are per-process; if the worker
crashes, the client's stream is gone before any resume could deliver
progress events to it. Re-running the whole pipeline on the next
client retry (deduplicated by `X-Request-ID` per ADR 0009) is the
right semantic — there's nothing useful a resumed workflow could do
for a connection that no longer exists.

If a future iteration wants durable streaming UX, the design is the
two-phase upload from ADR 0010: a `POST` that returns 202 + a
`GET /upload/<id>/events` that opens a fresh SSE stream on the live
workflow state. That sequencing belongs to ADR 0010, not this ADR.

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
