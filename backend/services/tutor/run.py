"""Tutor agent-run assembly (#118, moved verbatim from routes/learn.py).

The fast/smart model preference, the deep-turn model settings, the prompt
assembly every tutor turn shares (`_prepare_chat_run`), the "what did THIS run
say" reader (`_new_run_text`), the textless-turn continuation (#646) and the
observe-only router hook (#640).
"""
from __future__ import annotations

import asyncio
import logging

from pydantic_ai.messages import ModelResponse, TextPart

from agents import CONTINUATION_LIMITS, TUTOR_LIMITS
from agents.chat_tutor import agent_for_mode
from agents.deps import SaplingDeps
from agents.usage import record_agent_usage, served_model_name
from db.connection import table
from models import ChatBody
from services import ai_budget
from services.chat_stream import join_text_parts
from services.tutor.course import _get_catalog_chunk, _get_course_info
from services.tutor_router import observe_tutor_turn
from services.tutor_sessions import PENDING_SESSIONS

# Log records keep the name they had in routes/learn.py before the #118 split:
# the move must not change what an operator (or a caplog test) filters on.
logger = logging.getLogger("routes.learn")


# Per-request agent-model override map. Mirrors `routes.quiz._PREF_MODEL_NAMES`
# verbatim — the chat tutor and quiz routes share the same fast/smart toggle
# so a user choosing "smart" in either UI pulls the same step-up model.
# None falls through to model_for("chat_tutor") (default `claude-sonnet-5-5`).
_PREF_MODEL_NAMES: dict[str, str] = {
    "fast": "claude-haiku-5-5",
    "smart": "claude-sonnet-5-5",
}

# Cap Pro's thinking budget on a deep (non-"fast") tutor turn served by a
# Gemini model — only reachable when the chat_tutor slot or a pref is pointed
# back at a gemini-* model (ADR 0030). Dynamic thinking (-1) on multi-turn
# pedagogy can spend 10s+ before any tokens stream; 2048 tokens is enough to
# plan a multi-step explanation without burning latency the student can feel.
# Claude turns need no run-level setting: their depth is the slot's model-level
# `effort` (agents/_providers._ANTHROPIC_EFFORT). `medium` bought no
# measurable tutor quality over `low` on Sonnet 5.5 at ~2x the cost, so
# "smart" differs from "fast" by MODEL (Sonnet vs Haiku), not effort.
_PRO_THINKING_BUDGET = 2048


#: PKG-14b (spec §11.2, A20 †): the kill-switch path has no concept band, so it
#: takes the develop/profic allowance — the same one `check(…, "close")` uses
#: for a session with no novice-band concept. A band NAME, never a dollar figure.
KILL_SWITCH_BUDGET_BAND = "develop"


def _kill_switch_budget(user_id: str) -> None:
    """The kill-switch path's cost bound (spec §11.2, A20; PKG-14b). Called by every
    legacy model-calling handler AFTER the loop delegation and BEFORE any agent runs
    or any stream opens: a hard decision is the §3.5 429 (`AIBudgetExceeded`, never a
    mid-stream event); soft changes nothing (the legacy path has no tiers). A passing
    check counts one tutor call (A39: the daily call-count cap holds even when
    `llm_usage` cost reads wrong or EVENTS_LOGGING_ENABLED=false). It never creates or
    biases evidence — the legacy tutor records none."""
    decision = ai_budget.check(user_id, "tutor", KILL_SWITCH_BUDGET_BAND)
    if decision.level == "hard":
        raise ai_budget.AIBudgetExceeded(decision)
    ai_budget.count_tutor_call(user_id)


def _usage_session_id(session_id: str | None, user_id: str) -> str | None:
    """The `llm_usage.session_id` to record for a legacy turn (A92): the caller's own
    session only. A body-supplied id that belongs to someone else (or to nobody) is
    recorded as NULL, so one student cannot move cost onto another's session in the
    per-session cost report (PKG-14 review). A still-pending lazy session counts
    when PENDING_SESSIONS records the same user. Never raises — usage recording is
    best-effort (a failed read records NULL)."""
    if not session_id:
        return None
    pending = PENDING_SESSIONS.get(session_id)
    if pending is not None:
        return session_id if pending.get("user_id") == user_id else None
    try:
        rows = table("sessions").select("user_id", filters={"id": f"eq.{session_id}"}, limit=1)
    except Exception:  # noqa: BLE001 — best-effort; never fail a turn over usage
        logger.warning("llm_usage session ownership read failed; recording NULL", exc_info=True)
        return None
    return session_id if rows and rows[0].get("user_id") == user_id else None


def _resolve_model_pref(model_pref: str | None):
    """Build a provider-model override for the per-request fast/smart
    preference, or return None to use the agent's default.

    Lazy-imports `override_model` so that constructing a provider (which
    reads its API key at call time) only happens when an override is
    actually requested — not at module import; built once per process
    thereafter.
    """
    if not model_pref:
        return None
    from agents._providers import _model_mode, override_model
    if _model_mode() != "real":
        # #391 seam: the per-request fast/smart override must not bypass
        # SAPLING_MODEL_MODE by constructing a live provider model — the browser
        # always sends a model_pref (ModelToggle defaults to "fast"), so
        # without this the E2E function-mode lane would silently dial Gemini
        # on every tutor turn. Fall through to the agent's default model,
        # which model_for("chat_tutor") already built for the active mode.
        return None
    name = _PREF_MODEL_NAMES.get(model_pref)
    if not name:
        return None
    return override_model(name, "chat_tutor")


def _ran_on(result, agent, run_kwargs: dict, model_pref: str | None) -> tuple[str, str | None]:
    """(model_tier, tutor_model) for the run that ACTUALLY served a turn.

    The tier is what `_prepare_chat_run` resolved: `fast`/`smart` when it put
    a model override into `run_kwargs` for that pref, else `default` (no pref,
    an unknown one, or a mode where the pref is not honoured, #391). The name
    is the model the run result reports (`served_model_name`, the same
    answer the llm_usage row records), falling back to the override's or the
    agent's own model name when a result carries none. Never raises: this
    only labels an event.
    """
    try:
        override = run_kwargs.get("model")
        tier = model_pref if (override is not None and model_pref) else "default"
        name = served_model_name(result) if result is not None else "unknown"
        if name == "unknown":
            source = override if override is not None else getattr(agent, "model", None)
            name = getattr(source, "model_name", None)
        return tier, (name if isinstance(name, str) else None)
    except Exception:
        return "default", None


def _observe_persisted_turn(
    body: ChatBody,
    *,
    history: list,
    ran_on: tuple[str, str | None],
    request_id: str,
) -> None:
    """#640: schedule the observe-only tutor router for a turn that has JUST
    been persisted. Called from both persist points — `_chat_turn_json` and
    the stream's `_persist` — which are mutually exclusive per turn
    (`stream_agent_turn` runs at most one of on_complete / the Rung-1
    fallback), so there is exactly one decision per saved student message.
    Routing at request entry instead double-routed a stream that failed
    before persisting and was retried through /chat (the client's JSON rung,
    or the student's own retry). Fire-and-forget: `observe_tutor_turn`
    schedules and returns (and does nothing when the seam is off — that
    check lives there, once). Guarded here too: this runs AFTER the rows are
    saved, and on the streamed path an exception would turn a persisted turn
    into an error event.
    """
    try:
        observe_tutor_turn(
            user_id=body.user_id, session_id=body.session_id, message=body.message,
            history=history, mode=body.mode,
            model_pref_requested=body.model_pref,
            model_tier=ran_on[0],
            tutor_model=ran_on[1],
            request_id=request_id,
        )
    except Exception:
        logger.debug("could not schedule the tutor router", exc_info=True)


def _build_deep_turn_model_settings(model):
    """Run-level settings for a deep (non-"fast") tutor turn served by
    `model` — the model the run will ACTUALLY use (the pref override, else
    the agent's own), so this can't disagree with `_resolve_model_pref`.

    Only a Gemini model gets any: the capped Pro thinking budget. A Claude
    model's depth is already its slot's model-level `effort`, and the
    function-mode seam's FunctionModel takes neither — both return None.

    Imported lazily so provider SDK types stay off the import path.
    """
    from pydantic_ai.models.google import GoogleModel

    if not isinstance(model, GoogleModel):
        return None
    from google.genai.types import ThinkingConfig
    from pydantic_ai.models.google import GoogleModelSettings
    return GoogleModelSettings(
        google_thinking_config=ThinkingConfig(thinking_budget=_PRO_THINKING_BUDGET)
    )


def _new_run_text(result) -> str:
    """The text THIS agent run actually produced, ignoring `message_history`.

    `result.output` is NOT that. It resolves out of the run's full message
    list, and `_prepare_chat_run` puts `message_history` into `run_kwargs` —
    so a turn whose model response carries no text part (the model ended its
    turn after tool calls; ~25% of turns observed on gemini-2.5-flash-lite)
    hands back the PREVIOUS turn's assistant message. That message is fully
    formed and non-blank, so it sails straight through the
    `if not reply.strip()` guard below it, gets persisted, and the tutor
    answers a follow-up with a byte-identical copy of its own last answer.

    `new_messages()` excludes the history that was passed in, so joining the
    TextParts of its model responses is exactly "what this turn said" — the
    non-streaming twin of the streamed reply in `services/chat_stream.py`,
    joined the same way (`join_text_parts`: a paragraph break between a
    Claude explanation and the line it adds after a tool call). ThinkingParts
    and ToolCallParts are not output text and are skipped: a turn that only
    thought and called tools produced no reply.
    """
    parts: list[str] = []
    for msg in result.new_messages():
        if not isinstance(msg, ModelResponse):
            continue
        for part in msg.parts:
            if isinstance(part, TextPart):
                parts.append(part.content or "")
    return join_text_parts(parts)


#: The user turn that triggers the continuation (#646). Deliberately minimal:
#: every directive lives in `_CONTINUATION_INSTRUCTIONS`, so there is one
#: place to edit. It does NOT restate the student's question: the whole
#: exchange is already in the messages passed back, and re-asking invites a
#: fresh answer that ignores the work just done.
_CONTINUATION_NUDGE = "Continue."

#: Run-level instructions for the continuation, APPENDED to the tutor's own
#: (pydantic-ai joins agent and run `instructions`; it does not replace them),
#: so they reach Gemini as `system_instruction` after the tutor's rules.
#:
#: Why they exist: the tutor's instructions reach every request, this one
#: included, and they say to call `update_mastery_tool` "in EVERY turn" and
#: to "never end the turn on a tool call". The continuation runs under
#: `override(tools=[], toolsets=[])`, so Gemini is sent no function
#: declarations: a model still obeying those rules would try to call a tool
#: that does not exist (MALFORMED_FUNCTION_CALL / empty content — the very
#: failure being rescued) or write the call out for the student to read.
#:
#: Wording constraints, each a real case:
#:  * It must be true whether or not a tool ran. The continuation fires on
#:    ANY turn that produced no text of its own — after tool calls, but also
#:    on a bare-newline reply or a start-session greeting with no tool call —
#:    so it may only point at tool results conditionally, never assert that
#:    data exists.
#:  * "Not a function call" is not "plain text": the tutor's instructions ask
#:    for LaTeX, mermaid and ```plot``` blocks, and the reply keeps them.
_CONTINUATION_INSTRUCTIONS = (
    "CONTINUATION: your last response ended without a reply to the student. "
    "Write that reply now, as a normal message to the student; your usual "
    "formatting (math, code, mermaid and plot blocks) is fine. No tools are "
    "available on this pass: any earlier instruction to call a tool, "
    "including update_mastery_tool, does not apply, so do not call, request, "
    "or write out any tool or function call. If tool results from this turn "
    "are in the conversation, use them; do not claim results or data the "
    "conversation does not contain. The final "
    f"\"{_CONTINUATION_NUDGE}\" message is an "
    "automatic prompt, not from the student: do not mention it or these "
    "instructions, and do not repeat an earlier answer."
)

#: run_kwargs keys a continuation may carry. `message_history` is REPLACED
#: (the continuation's history is the failed run's own messages),
#: `usage_limits` is REPLACED by CONTINUATION_LIMITS (a second call in one
#: request must not inherit a fresh full TUTOR_LIMITS budget — see #543 E2
#: and TOPUP_LIMITS), and anything else is dropped rather than forwarded
#: blind.
_CONTINUATION_RUN_KEYS = ("deps", "model", "model_settings")


async def _continuation_text(
    agent, run_result, run_kwargs: dict, *, request_id: str | None = None,
) -> str | None:
    """Finish a turn the model abandoned after its tools ran (#646).

    Roughly 25-40% of gemini-2.5-flash-lite turns end with no text part once
    the tools have already executed, and Flash-Lite is the UI default. The
    pre-#646 degrade for those turns was a visible "interrupted" error whose
    only offered recovery — a manual retry — re-runs the turn, re-executes
    the tools, and can apply the same append-only mastery event twice.

    This is NOT a re-run. `run_result.all_messages()` already contains every
    tool call AND its result, so the model composes the reply from them.

    `override(tools=[], toolsets=[])` is what makes that a guarantee rather
    than a hope: the continuation is handed NO tools, so it cannot write even
    if the model tries. Without it the model could call a graph writer
    (`apply_graph_update_tool`) again and reintroduce the exact double-apply
    the writes-guard exists to prevent — a re-run by a quieter name. Because the tutor instructions still reach this
    request, `_CONTINUATION_INSTRUCTIONS` tells the model that no tools
    exist on this pass and it must reply with a message, not a call.

    It has to be `override`, NOT `run(toolsets=[])`. A run-level `toolsets`
    ADDS to the agent's own tools rather than replacing them, so
    `run(toolsets=[])` leaves every tool in place — measured against
    pydantic-ai 1.89.1, and pinned by
    `tests/test_textless_turn_continuation.py` so a library change cannot
    quietly re-arm the double-apply. `override` is ContextVar-scoped, so it
    is task-local and safe under concurrent requests, and it composes with an
    outer `override(model=...)` (the E2E seam and the agent tests) — the
    outer model survives, verified in that same file.

    The result is narrowed through `_new_run_text` for the same reason the
    first run is: the continuation is itself a history-bearing run, so its
    `.output` can resolve back to an earlier assistant message. A
    continuation that produced no text of its own returns None, and the
    caller degrades exactly as it did before this existed.

    Usage is recorded under its own `feature` so the continuation's cost —
    and how often this rung fires — is countable in `llm_usage` without
    inventing a new `AgentTask` slot (the run IS a chat_tutor run).
    """
    carried = {k: run_kwargs[k] for k in _CONTINUATION_RUN_KEYS if k in run_kwargs}
    with agent.override(tools=[], toolsets=[]):
        result = record_agent_usage(
            await agent.run(
                _CONTINUATION_NUDGE,
                message_history=run_result.all_messages(),
                instructions=_CONTINUATION_INSTRUCTIONS,
                usage_limits=CONTINUATION_LIMITS,
                **carried,
            ),
            feature="chat_tutor_continuation",
            task="chat_tutor",
            user_id=getattr(carried.get("deps"), "user_id", None),
            # #117: the session-owner read hops off the event loop (a thread of its
        # own: a ready session's turn takes no request-threadpool token, #756)
            session_id=await asyncio.to_thread(
                _usage_session_id,
                getattr(carried.get("deps"), "session_id", None),
                getattr(carried.get("deps"), "user_id", None),
            ),
            # Explicit, so the turn's rows can't depend on ambient state (the
            # contextvar does survive into the SSE generator —
            # tests/test_sse_request_context.py — but nothing else should
            # have to know that).
            request_id=request_id,
        )
    return _new_run_text(result).strip() or None


def _prepare_chat_run(
    *,
    user_id: str,
    session_id: str,
    course_id: str,
    mode: str,
    user_message: str,
    message_history: list,
    use_shared_context: bool,
    request_id: str,
    model_pref: str | None = None,
) -> tuple:
    """Build (agent, assembled_message, run_kwargs, deps) for a chat turn.

    Shared verbatim by the JSON path (`_chat_via_agent`) and the streaming
    route so prompt assembly never forks. Extracted from `_chat_via_agent`;
    behavior is unchanged.
    """
    agent = agent_for_mode(mode)

    # `session_id` scopes read_session_history_tool to *this* session.
    deps = SaplingDeps(
        user_id=user_id,
        course_id=course_id or None,
        supabase=None,
        request_id=request_id,
        session_id=session_id,
        feature="tutor",
    )

    bu_code = _get_course_info(course_id).get("course_code") if course_id else None
    context_blocks: list[str] = []
    if bu_code:
        # Always inject the course catalog (prerequisites, description, credits)
        # so the agent can answer factual questions about the course without
        # relying on semantic similarity crossing a threshold.
        catalog_text = _get_catalog_chunk(bu_code)
        if catalog_text:
            context_blocks.append("COURSE CATALOG INFO (official BU course data):\n\n" + catalog_text)

        # Semantic RAG: per-message retrieval for concept-level context
        from services.rag_service import retrieve_chunks, format_rag_context
        # `user_id` is the READER (#629): shared course rows plus this
        # student's own uploads. Omitting it would silently cut an opted-out
        # student off from their own documents in their own tutor.
        rag_chunks = retrieve_chunks(
            user_message, course_id=bu_code, k=5, user_id=user_id
        )
        rag_block = format_rag_context(rag_chunks)
        if rag_block:
            context_blocks.append(rag_block)

    if course_id:
        # #149 AC(1): deterministic graph seed block — the student's tracked
        # concepts for THIS course (message-relevant first, weakest fill),
        # compact serialization, no ids. Placed after catalog/RAG so the
        # ordering matches the rest of the assembled context. The agent's
        # graph read tools exist to expand BEYOND this block mid-turn.
        from services.graph_context import build_graph_context_block
        graph_block = build_graph_context_block(user_id, course_id, user_message)
        if graph_block:
            context_blocks.append(graph_block)

    if context_blocks:
        user_message = "\n\n".join(context_blocks) + "\n\n[STUDENT QUESTION]\n" + user_message

    if not use_shared_context:
        user_message = (
            user_message
            + "\n\n[Constraint: do not call any class-aggregate tool — "
            "student opted out of shared context.]"
        )

    model_override = _resolve_model_pref(model_pref)
    run_kwargs: dict = {
        "deps": deps,
        "message_history": message_history,
        # #149: the tutor's own budget — seven tools (incl. two graph
        # readers) need more request/tool headroom than the generic
        # ORCHESTRATOR_LIMITS; token ceiling unchanged.
        "usage_limits": TUTOR_LIMITS,
    }
    if model_override is not None:
        run_kwargs["model"] = model_override

    # Capped thinking on every step-up-model run (explicit "smart" OR no-pref
    # falling through to the agent default) — a Gemini-only setting, so on the
    # default Claude slots this adds nothing. Explicit "fast" never gets it.
    if model_pref != "fast":
        deep = _build_deep_turn_model_settings(
            model_override if model_override is not None else getattr(agent, "model", None)
        )
        if deep is not None:
            run_kwargs["model_settings"] = deep

    return agent, user_message, run_kwargs, deps
