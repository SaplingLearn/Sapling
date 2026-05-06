# 0008: Per-task model routing for worker agents

- Status: accepted
- Date: 2026-05-04
- Supersedes: none

## Context

Until this ADR every worker agent hardcoded `gemini-2.5-flash` via `google_model("gemini-2.5-flash")`. That was reasonable for a V1 — one model, easy to reason about — but it left two costs on the table:

1. **The classifier is a 7-way classification.** Flash is overkill; Flash-Lite handles it at meaningfully lower cost.
2. **Summary generation is short-form prose.** Same story.
3. **Concept extraction and syllabus parsing benefit from full Flash** — schema constraints, date parsing, structured-list outputs.

Hardcoding the model in each module also meant model swaps required code edits and a redeploy.

## Decision

Replace `google_model(name)` with a task-keyed selector in `backend/agents/_providers.py::model_for(task)`. Defaults:

| Task | Default |
|---|---|
| classifier | `gemini-2.5-flash-lite` |
| summary | `gemini-2.5-flash-lite` |
| concepts | `gemini-2.5-flash` |
| syllabus | `gemini-2.5-flash` |

Operators override via env var: `SAPLING_MODEL_<TASK_UPPER>` (e.g. `SAPLING_MODEL_CLASSIFIER=gemini-2.5-pro`). Selection happens at module import (process start) — changes require a restart, not a redeploy.

Cost telemetry: `genai-prices` is already a transitive dep of `pydantic-ai-slim[google]` and Logfire's `instrument_pydantic_ai()` auto-attaches `gen_ai.usage.input_tokens`, `output_tokens`, and `gen_ai.cost.usd` to every span. No new code; verified via import smoke test (genai-prices 0.0.57).

`google_model(name)` stays as a back-compat shim so any future caller that wants to bypass the selector and pin a model can.

## Consequences

- (+) Estimated 40–60% Gemini spend reduction on the classifier and summary steps with no behavior regression. Monitor in Logfire after the next 100 uploads.
- (+) Model swaps are an env-var change. We can A/B classifier on Flash vs Flash-Lite vs a fine-tuned model without touching code.
- (+) Per-task telemetry rolls up cleanly in Logfire because each agent run is its own span tagged with the model name.
- (−) Gemini Flash-Lite has lower-quality outputs on edge cases. The 25-case classifier eval set (added alongside this ADR) will catch regressions before they ship; if we see drops we move that task back to Flash via env var.
- (−) Process restart required for model changes. Acceptable — we don't swap models per request, and a bounce is a 30s op.
- (−) The defaults are opinionated guesses. After a quarter of production data, revisit.
