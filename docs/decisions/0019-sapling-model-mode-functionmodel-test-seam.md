# 0019: SAPLING_MODEL_MODE FunctionModel test seam

- Status: accepted
- Date: 2026-07-23
- Supersedes: none (extends 0008 per-task model routing)

## Context

Epic #402 (the E2E regression suite) needs agent journeys — the tutor, quiz,
notes, and document paths — to run deterministically in tests while exercising
the *real* prompt, tool registration, arg-schema validation, and retry loop. Two
constraints made that hard. First, `agents/_providers.py::model_for(task)` was
the single construction point for every agent's model but had no injection seam:
it always returned `GoogleModel(name, provider=_provider)`, so tests could only
stub whole agent objects (`patch("<agent>.run")`), which leaves all the wiring
under test untested — the exact failure mode the epic is fighting. Second, #379
installed an autouse `_hermetic_llm_transport` guard that patches
`google.genai._api_client.BaseApiClient` at the class level so any unstubbed LLM
call raises `UnstubbedLLMEgress`; pydantic-ai's `GoogleModel` wraps a
`google.genai.Client`, so the agents lane already rides that guard. A test seam
that needed the guard *disabled* to work would be substituting at the wrong
layer. This is issue #391.

## Decision

Add a `SAPLING_MODEL_MODE` dispatch inside `model_for`, defaulting to `real`.

- `real` (default; unset/blank/`"real"`) → `GoogleModel`, still honoring the
  per-task `SAPLING_MODEL_<TASK>` override from ADR 0008. Production and the
  default hermetic unit lane are byte-for-byte unchanged.
- `function` → a pydantic-ai `FunctionModel` bound to a per-task handler that
  tests register via `register_function_handler(task, handler)` /
  `clear_function_handlers()`. The handler resolution is deferred to run time
  (a closure, not capture time), so a handler registered *after* the agent
  module was imported still takes effect — necessary because agents build their
  model at import (`model=model_for(...)` on a module-level `Agent`).
- `cassette` is a recognized mode name (issue #391 scope) but raises
  `NotImplementedError`; record/replay from `tests/evals` is a deliberate
  follow-up, not silently stubbed.
- Any other value raises `ValueError` — a typo'd mode is a config error, never a
  silent fall-through to `real` that would bill Gemini.

The load-bearing property: `FunctionModel` never constructs a `google.genai`
request, so a `function`-mode run substitutes **above** the transport guard. It
needs no hermetic-guard exemption marker and runs clean in the default lane;
`test_function_mode_rides_above_transport_guard` pins that invariant, and
`test_default_real_mode_agent_run_still_trips_the_guard` is the counter-check
proving the guard is genuinely in the path. Tests drive a real agent by pairing
the mode with `Agent.override(model=model_for(task))`, the pydantic-ai-blessed
per-run injection (cf. ADR 0013's per-call `model=` layer).

## Consequences

- (+) Agent tests can exercise the real prompt, tool registration, arg schemas,
  and retry loop deterministically and offline — the AC drives `note_chat_agent`
  with a scripted `search_course_materials_tool` call and asserts on the
  LLM-chosen arguments after schema validation, plus a classifier retry-loop
  test that watches an out-of-range field get rejected then corrected.
- (+) Zero production-path change: `real` is the default and the deployed code
  never reads a handler registry. The ~976-test hermetic lane is untouched
  (+13 new tests, no regressions).
- (+) The seam sits above the transport guard by construction, so it composes
  with #379 instead of fighting it — no fourth guard, no bypass.
- (−) `FunctionModel` does **not** enforce Gemini's structured-output
  schema-complexity limits (see `docs/attempts/2026-05-03-orchestrator-schema-
  complexity.md`). A schema that passes in `function` mode can still be rejected
  by the real `GoogleModel`. The seam gives confidence about *wiring*, not about
  whether Gemini will accept an output schema — keep the eval cassettes for that.
- (−) `cassette` mode is declared but unbuilt; a follow-up issue tracks it.
- (−) Because agents capture their model at import, `function` mode reaches an
  already-imported agent only via `Agent.override(...)` or by setting the env
  before import. Full-journey E2E lanes (#392/#393/#399) that drive real routes
  must set `SAPLING_MODEL_MODE=function` at process start so every agent builds
  as a `FunctionModel`, then register per-task handlers.
