"""Sapling Pydantic AI agents.

Exposes the per-run cost guardrails every agent call site passes via
the explicit `usage_limits=` kwarg. We keep two shapes: workers don't
call tools (tool_calls_limit=0) and never need many requests; the
orchestrator does call tools and may iterate.
"""

from pydantic_ai.usage import UsageLimits

WORKER_LIMITS = UsageLimits(
    request_limit=2,
    tool_calls_limit=0,
    total_tokens_limit=50_000,
)

ORCHESTRATOR_LIMITS = UsageLimits(
    request_limit=8,
    tool_calls_limit=10,
    total_tokens_limit=100_000,
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
