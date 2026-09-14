"""Sapling Pydantic AI agents.

Exposes the per-run cost guardrails every agent call site passes via
the explicit `usage_limits=` kwarg. We keep two shapes: workers don't
call tools (tool_calls_limit=0) and never need many requests; the
orchestrator does call tools and may iterate.

OUTPUT-SCHEMA BUDGET (#153, codifying
docs/attempts/2026-05-03-orchestrator-schema-complexity.md)
---------------------------------------------------------------------
Gemini's native structured-output API compiles the output schema into a
constrained-decoding automaton and REJECTS rich schemas outright ("too
many states for serving") — the request fails before the model runs.
The original document-orchestrator output (classification + summary +
concepts + optional syllabus in one model) died exactly this way. Every
agent `output_type` must therefore stay small and flat:

- at most ~8 fields per object (aim for < 5), and one level of object
  nesting below the root (root -> list[Item] is the ceiling);
- no optional NESTED models (`Sub | None` fields — optional scalars are
  fine); if a sub-result is conditional, run a second agent or compose
  in route code;
- enums as flat string Literals, not constrained/patterned strings;
- rich results are composed deterministically in code from several
  small agent runs (see agents/document.py), never asked for whole;
- `PromptedOutput` is the escape hatch when a *specific* Pydantic
  feature trips the provider (e.g. `date` fields on syllabus
  extraction) — it moves enforcement into the prompt + local
  validation but does NOT exempt the schema from this budget.

`tests/test_agent_output_schemas.py` walks every registered agent and
fails CI when an output schema exceeds the budget, so the next rich
schema dies in review, not against Gemini's 400s.

Validation-retry policy (#153): idempotent structured-output generation
agents run with an output-retry budget of 2 (`retries=2` on tool-less
workers; `output_retries=2` on quiz, whose tool retries stay at the
default) so a transiently malformed output re-rolls instead of failing
the request. Free-text agents (chat_tutor, note_chat, health,
ocr_vision) have no output validation to retry — and the streaming
tutor's failure handling belongs to `chat_stream.stream_agent_turn`'s
rung ladder, never to a hidden re-roll. Successful-but-retried runs are
logged by `agents.usage.record_agent_usage`.
"""

from pydantic_ai.usage import UsageLimits

WORKER_LIMITS = UsageLimits(
    # 3, not 2: a worker's only extra requests are output-validation
    # retries (#153 — output-retry budget of 2, so worst case is
    # 1 initial + 2 retries). At 2 the second retry would trip
    # UsageLimitExceeded instead of UnexpectedModelBehavior, which
    # misfiles "model kept emitting garbage" as "input too long" at the
    # routes that distinguish the two (routes/notes.py 413-vs-500).
    request_limit=3,
    tool_calls_limit=0,
    total_tokens_limit=50_000,
)

ORCHESTRATOR_LIMITS = UsageLimits(
    request_limit=8,
    tool_calls_limit=10,
    total_tokens_limit=100_000,
)

# #543 E2: the quiz generation top-up runs a SECOND agent call in the same
# request. Reusing ORCHESTRATOR_LIMITS would hand it a fresh full budget,
# silently doubling the per-request cost backstop that limit exists to be.
# The retry only rewrites a handful of questions and already has the
# concept context in its prompt, so a fraction of the budget is enough —
# and it keeps one request's worst case close to the intended ceiling.
TOPUP_LIMITS = UsageLimits(
    request_limit=4,
    tool_calls_limit=4,
    total_tokens_limit=40_000,
)

# The chat tutor's own ceiling (#149): its tool surface grew to seven
# (two graph readers joined the five ADR-0015 tools), so a legitimately
# tool-heavy turn — a couple of reads plus graph writes — needs more
# request/tool headroom than the generic orchestrator budget, while the
# token ceiling stays put as the cost backstop.
TUTOR_LIMITS = UsageLimits(
    request_limit=12,
    tool_calls_limit=12,
    total_tokens_limit=100_000,
)

__all__ = ["WORKER_LIMITS", "ORCHESTRATOR_LIMITS", "TUTOR_LIMITS"]
