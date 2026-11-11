"""The #646 rescue: the tool-less continuation that finishes a run that ended
without a structured turn, and the run's request count.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pydantic_ai.messages import ModelRequest, ToolReturnPart
from pydantic_ai.usage import RunUsage
from agents import CONTINUATION_LIMITS
from agents.usage import UnfinishedRun, record_agent_usage
from services.tutor import _CONTINUATION_NUDGE, _CONTINUATION_RUN_KEYS
from services import ai_budget

from services.loop.constants import (
    _FEEDBACK_ANSWER_LEAD,
    _FEEDBACK_NEXT_STEP,
    _FEEDBACK_VERDICT_LINES,
)

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


def _template_feedback(verdict: str, reference: str | None) -> str:
    """The hard-level feedback turn (no model): the verdict line, the stored
    reference when the answer is released (H6 content, legal after a wrong
    attempt, spec §3.3), and the fixed next-step line."""
    parts = [_FEEDBACK_VERDICT_LINES[verdict]]
    if reference:
        parts.append(_FEEDBACK_ANSWER_LEAD + reference)
    parts.append(_FEEDBACK_NEXT_STEP)
    return " ".join(parts)


def _continuation_history(messages: list) -> list | None:
    """The failed tool run's messages up to and including its last tool
    results (#646: what follows them is the model's empty answer and any
    output-retry prompts). None when no tool ran — there is nothing to
    continue from, so the turn is re-run tool-less instead."""
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if isinstance(m, ModelRequest) and any(isinstance(p, ToolReturnPart) for p in m.parts):
            return list(messages[: i + 1])
    return None


#: Spec §13 A121: the v2 variant's run arguments
#: (`variant_run_args`) — a continuation finishes the turn in the same variant.
#: A flag-off run carries none of them.
_VARIANT_RUN_KEYS = ("output_type", "instructions", "metadata")


@dataclass(frozen=True)
class ContinuationPlan:
    """What the tool-less continuation run is: its prompt, its `agent.run`
    kwargs (tools are removed by the caller's override) and its usage feature."""

    prompt: str
    run_kwargs: dict
    feature: str


def continuation_plan(*, assembled: str, run_kwargs: dict, messages: list) -> ContinuationPlan:
    """The #646 continuation of a loop run that ended without a structured turn,
    as data (the route runs it; tests/evals/loop_tutor.py replays through it).
    It continues from the failed run's last tool results with the nudge under
    CONTINUATION_LIMITS, or — no tool ran — re-runs the turn itself under the
    turn's own limits. Same slot, same settings, minus `tool_choice` (no tools,
    so a tool_config would have nothing to choose)."""
    carried = {
        k: run_kwargs[k]
        for k in (*_CONTINUATION_RUN_KEYS, *_VARIANT_RUN_KEYS)
        if k in run_kwargs
    }
    carried["model_settings"] = {
        k: v for k, v in (carried.get("model_settings") or {}).items() if k != "tool_choice"
    }
    history = _continuation_history(messages)
    if history is None:
        carried["message_history"] = list(run_kwargs.get("message_history") or [])
        carried["usage_limits"] = run_kwargs.get("usage_limits")
        return ContinuationPlan(prompt=assembled, run_kwargs=carried, feature="loop_tutor")
    carried["message_history"] = history
    carried["usage_limits"] = CONTINUATION_LIMITS
    return ContinuationPlan(
        prompt=_CONTINUATION_NUDGE, run_kwargs=carried, feature="loop_tutor_continuation"
    )


async def _loop_continuation_text(turn, messages: list) -> str | None:
    """The #646 twin of routes.learn._continuation_text for the STRUCTURED loop
    turn. Lane B's live finding: after a tool call gemini flash-lite answered
    with empty responses and never wrote the LoopTurnOut — Gemini only takes
    the structured (JSON) turn with no tools declared (the agent now declares
    no tools after a tool round, so this is the rescue for what is left). So: a
    budget check FIRST (invariant 23; None at the hard level or when the
    existing slot exceeds the refreshed tier ceiling), one counted
    tutor call (A39), then `continuation_plan` run on the SAME slot with every
    tool removed — the safety property, `override(tools=[], toolsets=[])`
    (pinned). Returns the rendered turn (the output validator still judges it
    against deps.loop_turn)."""
    decision = await asyncio.to_thread(  # #117: off the event loop
        ai_budget.check,
        turn.user_id,
        "tutor",
        turn.band,
        **turn.budget_counters(include_current_run=True),
    )
    if decision.level == "hard" or (turn.tier == "deep" and decision.tier_ceiling != "deep"):
        # Never rescue on the old deep slot after the known primary work has
        # lowered its allowance. Replanning/rerouting would be a different turn.
        return None
    plan = continuation_plan(
        assembled=turn.assembled, run_kwargs=turn.run_kwargs, messages=messages
    )
    await asyncio.to_thread(ai_budget.count_tutor_call, turn.user_id)  # #117
    usage = RunUsage()
    result = None
    try:
        with turn.agent.override(tools=[], toolsets=[]):
            result = await turn.agent.run(plan.prompt, usage=usage, **plan.run_kwargs)
    finally:
        # A failed continuation still consumed its bounded model requests.
        # Keep an incomplete bill explicitly partial; never invent missing tokens.
        if result is None:
            logger.warning(
                "Loop continuation ended without final output; usage is incomplete "
                "(known model requests=%s); in-flight token usage may be missing",
                usage.requests,
            )
        if result is not None or usage.requests:
            billed = result if result is not None else UnfinishedRun(usage)
            turn.run_requests += _requests_of(billed)
            try:
                record_agent_usage(
                    billed,
                    feature=plan.feature,
                    task=turn.slot,
                    user_id=turn.user_id,
                    session_id=turn.session_id,
                )
            except Exception as exc:
                # The canonical helper never raises. Keep instrumentation from
                # replacing a provider error or cancellation if that changes.
                logger.warning("Usage accounting hook failed (stage=loop_continuation_usage, error_type=%s)", type(exc).__name__)
    return turn.render(result.output)


def _requests_of(run_result) -> int:
    """Model requests a run reports (RunResult.usage / UnfinishedRun.usage()); 0 unknown."""
    usage = getattr(run_result, "usage", None)
    if not hasattr(usage, "requests") and callable(usage):  # UnfinishedRun.usage()
        usage = usage()
    try:
        return int(getattr(usage, "requests", 0) or 0)
    except (TypeError, ValueError):
        return 0
