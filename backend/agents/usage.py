"""One-line usage capture for Pydantic AI agent runs (issue #118).

Every agent call site wraps its result in ``record_agent_usage(result,
feature=..., task=...)``. The helper reads ``result.usage()`` and the model
actually used, then hands them to ``events_service.log_llm_usage`` (which
normalizes tokens, computes cost, and enqueues off the request thread).

It is also PostHog's ONLY source of LLM analytics (ADR 0028): ``log_llm_usage``
mirrors the same row as a privacy-mode ``$ai_generation`` (model, provider,
tokens, cost, request id as trace id, feature/task — never prompt or output
content) through the PostHog consent queue. There is no OTel span export to
PostHog; a run that reports here is covered, whatever its call site.

Two properties matter:

* **One line per call site.** Because it returns ``result`` unchanged, a call
  site can wrap inline (``result = record_agent_usage(await agent.run(...),
  feature=..., task=...)``) or add it as a trailing statement.
* **Never raises.** Instrumentation must not break an agent run, so every
  failure — a result shape we don't recognize, a usage extraction slip — is
  swallowed and logged as a metadata-only warning, without exception prose.

The ``model`` is read from the result's final ``ModelResponse`` (the model the
provider actually served); if that's unavailable it falls back to the task's
configured model via ``_providers.model_for``.
"""

from __future__ import annotations

import logging
from typing import Any

from agents._providers import AgentTask, model_for
from services import events_service

logger = logging.getLogger("sapling.agents.usage")


class UnfinishedRun:
    """What ``record_agent_usage`` reads off a run that raised after the
    provider answered: the usage billed so far. Pass ``usage=RunUsage()``
    into ``agent.run`` so a run that raises (output validation exhausted, a
    token cap checked after a response) still says what it cost. With no
    final response to read, the model name falls back to the task slot's
    configured model. (agents/grader.py keeps its own copy, _UnfinishedRun.)
    """

    def __init__(self, usage: Any) -> None:
        self._usage = usage

    def usage(self) -> Any:
        return self._usage

    def all_messages(self) -> list:
        return []


def served_model_name(result: Any, task: AgentTask | None = None) -> str:
    """Best-effort model id for the run, resilient to Pydantic AI churn.

    Public because question provenance (E5) needs the SAME answer this
    module already computes for the `llm_usage` row: "which model actually
    wrote this?" Two independent derivations of that would eventually
    disagree, and the ledger and the stored question would then attribute
    the same generation to different models.
    """
    # Every return below is coerced with str(). Pydantic AI hands back a
    # plain string today, but this value is no longer only written to the
    # usage ledger (which swallows everything): E5 stamps it into question
    # provenance, which is json-serialized into the encrypted
    # questions_json. A non-string leaking through there would raise inside
    # encrypt_json and 502 a generation that had already succeeded —
    # metadata about a quiz must never be able to destroy the quiz.
    #
    # Preferred: the final ModelResponse carries the served model name.
    try:
        name = getattr(result.response, "model_name", None)
        if name:
            return str(name)
    except Exception:
        pass
    # Fallback: scan the message history for the last response with a model.
    try:
        for msg in reversed(result.all_messages()):
            name = getattr(msg, "model_name", None)
            if name:
                return str(name)
    except Exception:
        pass
    # Last resort: the task's configured default model.
    if task is not None:
        try:
            return str(model_for(task).model_name)
        except Exception:
            pass
    return "unknown"


def _log_recovered_retries(result: Any, task: AgentTask | None, feature: str) -> None:
    """Make recovered validation retries observable (#153).

    A run that needed output/tool validation retries but ultimately succeeded
    is invisible today: pydantic-ai re-rolls internally and only exhaustion
    surfaces (as UnexpectedModelBehavior in the route's logs). Count the
    `RetryPromptPart`s in the final message history and WARN so a drifting
    prompt/schema shows up in logs before it starts failing requests outright.
    A log line, not a #117 event: the frozen taxonomy stays untouched.
    """
    retry_parts = [
        part
        for message in result.all_messages()
        for part in getattr(message, "parts", [])
        if type(part).__name__ == "RetryPromptPart"
    ]
    if retry_parts:
        tools = sorted(
            {t for t in (getattr(p, "tool_name", None) for p in retry_parts) if t}
        )
        logger.warning(
            "agent run recovered after %d validation retr%s "
            "(task=%s feature=%s tools=%s)",
            len(retry_parts),
            "y" if len(retry_parts) == 1 else "ies",
            task,
            feature,
            tools or "output",
        )


def _cache_and_thinking(usage: Any) -> tuple[int | None, int | None]:
    """(cached_tokens, thinking_tokens) for the llm_usage row (spec §13 A21), as pydantic-ai
    1.107 carries Gemini's counts (models/google.py::_metadata_as_usage). Gemini omits zero
    counts, so a RunUsage without the key means 0; a shape with no such fields means None."""
    details = getattr(usage, "details", None)
    details = details if isinstance(details, dict) else None
    thinking = int(details.get("thoughts_tokens") or 0) if details is not None else None
    if details is None and not hasattr(usage, "cache_read_tokens"):
        return None, thinking
    cached = max(
        int(getattr(usage, "cache_read_tokens", 0) or 0),
        int((details or {}).get("cached_content_tokens") or 0),
    )
    return cached, thinking


def record_agent_usage(
    result: Any,
    *,
    feature: str,
    task: AgentTask | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    course_id: str | None = None,
) -> Any:
    """Record token usage for an agent run and return ``result`` unchanged.

    ``user_id`` is optional: pass it where the actor is in scope (routes with a
    ``deps.user_id`` / request body); omit it and ``log_llm_usage`` attributes
    the row to the acting user — the request's session user, or the job's
    (``request_context.current_acting_user``, #119) — and the request_id
    from the contextvar still correlates it. Pass
    ``request_id`` explicitly from code that runs OUTSIDE the request
    contextvar (a detached task, an SSE generator), where the implicit lookup
    finds nothing.

    ``session_id`` (PKG-14b, spec §13 A92): pass the loop/tutor session the run
    belongs to wherever the run site knows it (``deps.session_id``); it lands in
    ``llm_usage.session_id`` so the cost report groups per session directly.
    ``course_id`` (spec §13 A137): the course the run served, at the loop's run
    sites that may have no session (check-item drafting and its checks, the
    grader, the loop's decisions); ``llm_usage.course_id`` puts their cost on
    a course in the cost-per-learning-gain report.

    Also warns when the run only succeeded after validation retries (#153) —
    same guarded, never-raises contract.
    """
    try:
        usage = result.usage()
        cached_tokens, thinking_tokens = _cache_and_thinking(usage)
        events_service.log_llm_usage(
            feature=feature, task=task, model=served_model_name(result, task), usage=usage,
            user_id=user_id, cached_tokens=cached_tokens, thinking_tokens=thinking_tokens,
            session_id=session_id, request_id=request_id, course_id=course_id,
        )
    except Exception as exc:
        logger.warning("Usage accounting hook failed (stage=agent_usage_capture, error_type=%s)", type(exc).__name__)
    try:
        _log_recovered_retries(result, task, feature)
    except Exception as exc:
        logger.warning("Usage accounting hook failed (stage=agent_retry_observability, error_type=%s)", type(exc).__name__)
    return result
