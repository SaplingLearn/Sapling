# 0024: Retire the legacy Gemini seam — agents are the only LLM path

- Status: accepted
- Date: 2026-07-30
- Relates to: #151 (this cutover, shipped as #151a + #151b), #152 (agent-migration epic)
- Supersedes: the legacy-fallback clause of ADR 0001 (the framework adoption itself stands)

## Context

ADR 0001 adopted Pydantic AI with a deliberate safety net: every migrated
surface kept its old `services/gemini_service.py` code path as a fallback,
entered on `UsageLimitExceeded` / `UnexpectedModelBehavior` / any other agent
exception. The migrations landed (#143–#147, #349), the eval harness gated
them (ADR 0021, six replay datasets with committed baselines), and the
fallbacks aged from safety net into liability: two prompt stacks to keep in
sync per surface, silent degradation that masked real agent failures (a
tripped guardrail re-ran the whole turn on a worse pipeline instead of
surfacing), a fallback blind spot in the function-mode E2E seam (the legacy
paths had no `model_mode()` gate — `frontend/e2e/streaming.spec.ts` had to
document that hole), and a growing list of double-write hazards once agents
gained in-band graph/mastery tools (#470, #472).

#151 is the endgame: delete the seam. #151a retired the learn.py/streaming
legacy paths; #151b (this ADR's PR) retired the documents.py paths and
deleted the module.

## Decision

Every LLM call in the backend is a Pydantic AI agent under `backend/agents/`
(per-task model slots + the `SAPLING_MODEL_MODE` seam in
`agents/_providers.py`). There is no raw-`google-genai` application seam
anymore. When an agent fails, the route DEGRADES HONESTLY — a mapped HTTP
status, a terminal SSE error, or a best-effort empty result — it never
re-runs the request on a second prompt stack.

### What was deleted

- `services/gemini_service.py` (module-level `genai.Client`; `call_gemini`,
  `call_gemini_multiturn`, `call_gemini_json`, `extract_graph_update`) and
  its test files (`test_gemini_service.py`, `test_gemini_usage_logging.py`,
  the gemini-helper halves of the instrumentation/hermetic guards).
- #151a (learn.py/streaming): `_legacy_chat`, `build_system_prompt`,
  `get_conversation_history`, `_get_course_documents`,
  `_resolve_legacy_model`, the prompt-template loader and the five legacy
  prompt files, `compact_graph_context`.
- #151b (documents.py): `_process_document` (the single-call
  classify/summarize/extract prompt), `_legacy_upload_pipeline`,
  `_stream_legacy_fallback`, `_extend_course_concepts` (the legacy
  concept-scan prompt), and their private coercion helpers
  (`_coerce_str_list` / `_coerce_dict_list` / `_coerce_concept_notes`).
  `step="fallback"` left the upload SSE vocabulary; the frontend's
  fallback-toast branch died with it.
- The two offline benchmarks (`scripts/benchmark_quiz.py`,
  `scripts/benchmark_rag.py`) keep a raw baseline arm via a new
  `scripts/_raw_gemini.py` — benchmark-only by contract (its docstring
  forbids importing it from `services/`, `routes/`, or `agents/`).

### The rung ladder (canonical description)

Failure handling is now a small, uniform ladder instead of a parallel
pipeline. Server side (`services/chat_stream.py::stream_agent_turn` + the
route mappings):

- **Streamed tutor turn, agent fails before any text (Rung 1)** — degrade to
  ONE fresh non-streaming agent turn on the fast tier
  (`nonstream_fallback` → learn.py's `_chat_turn_json` /
  `_start_session_agent`); its reply arrives as a single `token` + `done`.
  The fallback owns persistence and usage; at most one of
  on_complete/nonstream_fallback runs per turn.
- **Writes-guard (the fallback write-state stamp)** — a fallback re-runs the
  whole turn, so it only runs when the failed run wrote nothing. If
  graph/mastery tool writes landed, the turn ends in a terminal `error` with
  `retryable: false`. The Rung-1 fallback is itself a tool-calling run, so
  the route helpers stamp `sapling_wrote` on its exception (#472 review) —
  a failed fallback whose tools wrote is likewise `retryable: false`; a
  pre-write failure stays `retryable: true`. Every streamed `error` event
  carries `retryable` (additive, #151a).
- **Failure after tokens streamed (Rung 2)** — terminal `error`; the client
  keeps the partial and offers Retry (ADR 0020).
- **Client ladder** — `ChatStreamError.retryable` + `shouldFallBackToJson()`
  (`frontend/src/lib/api.ts`): the transparent JSON re-send rung is skipped
  for `retryable: false` errors and for 413s, so the client can no longer
  silently re-run a turn whose side effects landed.
- **JSON routes (guardrail → status mapping)** — `/chat`, `/start-session`,
  `/action` (learn.py, the routes/notes.py precedent):
  `UsageLimitExceeded` → **413** with a cause-naming, deliberately
  non-retry detail (budget trips are deterministic);
  `UnexpectedModelBehavior` → **502** retry-friendly, logged at WARNING;
  bare `Exception` → **502** + full exception log (pages fire on these).
- **Document upload `/upload/sync`** — both guardrail exceptions and bare
  exceptions map to a retry-friendly **502** (`UPLOAD_FAILED_DETAIL`):
  nothing was persisted and the client mints a fresh X-Request-ID per
  attempt, so retrying re-runs the pipeline. Guardrails log WARNING; bare
  exceptions log the full traceback.
- **Document upload streaming `/upload`** — any pre-result agent failure
  emits the terminal `error` (step=`failed`, with `request_id`) +
  `status:done` pair and stops — the exact tail the legacy fallback used on
  double-failure, so clients needed no new case. Post-result persistence
  failures emit the same pair and never a second `result`.
- **`/scan-concepts`** — best-effort enrichment (D4): agent failure degrades
  to `{"concepts": [], "added": 0, "existing": N}` with a warning log.

### /start-session prompt convergence

#151a gave the JSON `/start-session` its first agent implementation
(`_start_session_agent`), converging the greeting prompt on what
`/start-session/stream` already shipped — the last place where the legacy
and agent prompt stacks could drift is gone; there is one greeting prompt.

### Why now, without the usage query

The original deletion gate (ADR 0016's cleanup plan) imagined measuring
legacy-fallback hit rates in `llm_usage` before cutting over. That
measurement is moot: production carries **no user traffic yet** — the prod
project is catalog-only (no user data), so legacy reachability in prod is
zero by construction, and staging traffic is our own. Pre-beta is exactly
when a breaking simplification is cheapest. The #117 observability events
(`document.upload` / `document.processed` deltas, `chat.message_sent`,
`llm_usage` per agent task) ship with this change, so post-beta failure and
cost rates are measurable from day one — on the agent path, the only path.

## Consequences

- (+) One prompt stack per surface; evals (ADR 0021) gate the only code
  that runs.
- (+) The function-mode E2E seam now covers every request-path LLM call —
  no ungated legacy client below `agents/_providers.py` (#439's invariant
  holds globally).
- (+) Honest failures: a tripped guardrail surfaces as 413/502/terminal
  error with `request_id`, instead of silently spending a second model call
  on a worse pipeline.
- (+) `#118` instrumentation is agent-only; the `_log_gemini_usage` side
  channel is gone.
- (−) No second-chance pipeline: transient Gemini trouble that a legacy
  re-run might have papered over now reaches the client as a retryable
  error. Accepted — retry-friendly statuses + client Retry affordances
  (ADR 0020) put that decision with the user, and the streamed tutor keeps
  its one same-family fast-tier fallback rung.
- (−) Benchmarks carry a small raw-Gemini helper (`scripts/_raw_gemini.py`)
  outside the agent stack. Contained by its import contract.

## Revert path

Git history: revert the #151b PR (documents half + deletion) and, if the
learn.py half must come back too, the #151a cutover it stacks on — #472's
review fixes (fallback write-state stamping, ADR 0020 amendment) ride with
#151a, so the pair reverts cleanly in that order. No migrations, no data
shape changed; this was code-path removal only.
