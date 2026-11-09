from __future__ import annotations

import asyncio
import logging
import uuid
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from sse_starlette.sse import EventSourceResponse

from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from agents import CONTINUATION_LIMITS, TUTOR_LIMITS
from agents.chat_tutor import agent_for_mode
from agents.deps import SaplingDeps
from agents.usage import record_agent_usage, served_model_name
from db.connection import table
from services import events_service
from services.academics import offering_course_id, require_course_enrollment, resolve_offering
from models import StartSessionBody, ChatBody, EndSessionBody, ActionBody, ModeSwitchBody, RenameSessionBody
from services.agent_events import SSE_CACHE_CONTROL, SaplingEvent, sapling_event_to_sse
from services.auth_guard import require_self, get_session_user_id, guard_off_loop
from services.chat_stream import join_text_parts, merge_graph_updates, stream_agent_turn
from services.encryption import (
    decrypt_if_present,
    decrypt_json_column,
    encrypt_if_present,
    encrypt_json,
)
from services.profiles import get_display_name
from services.graph_service import get_graph
from services.request_context import current_request_id
from services.streak_service import touch_streak_safe
from services.tutor_sessions import (
    PENDING_SESSIONS,
    SESSION_NOT_FOUND as _SESSION_NOT_FOUND,
    aget_pending,
    amaterialize_stored,
    araise_if_discarded,
    arequire_owned_open,
    arequire_session_open,
    arequire_session_owner,
    astash_pending,
    astored,
    discard_if_pending,
    discarded_reason,
    elapsed_minutes as _elapsed_minutes,
    materialization_lock,
    raise_if_discarded,
    rename_pending,
    require_session_owner,
    row_may_exist as _session_row_may_exist,
    session_owned_by,
    stash_pending,
)
from services.tutor_router import observe_tutor_turn
from services.xp_service import award_xp_safe

logger = logging.getLogger(__name__)

router = APIRouter()

# Lazy sessions: start-session does not write to DB until the user sends their
# first chat message. PENDING_SESSIONS (session_id -> pending payload) lives in
# services/tutor_sessions.py so other routes can share the ownership rule.

MODE_DISPLAY_NAMES = {
    "socratic": "Socratic (question-based)",
    "expository": "Expository (direct explanation)",
    "teachback": "Teach-back (you explain to me)",
}

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
    if the model tries. Without it the model could call `update_mastery_tool`
    again and reintroduce the exact double-apply the writes-guard exists to
    prevent — a re-run by a quieter name. Because the tutor's own
    instructions (which demand a mastery call every turn) still reach this
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
            # Explicit, so the turn's rows can't depend on ambient state (the
            # contextvar does survive into the SSE generator —
            # tests/test_sse_request_context.py — but nothing else should
            # have to know that).
            request_id=request_id,
        )
    return _new_run_text(result).strip() or None


async def _get_course_id_for_topic(topic: str, user_id: str) -> str:
    """
    Find the course_id associated with a topic/concept for a user.
    First checks if topic matches a course_code or course_name,
    then falls back to finding via graph_nodes.
    """
    if not topic:
        return ""
    topic_trim = topic.strip()
    if not topic_trim:
        return ""
    
    # First, check if topic matches a course code or name in user's enrolled
    # courses. Enrollment keys on an offering; the abstract course (which the
    # session + knowledge graph key on) sits behind
    # offering_id → course_offerings.course_id → courses. Match the topic against
    # the abstract course's code/name and return the abstract course_id.
    try:
        enrolled = await table("enrollments").aselect(
            "offering_id,course_offerings!inner(course_id,courses!inner(course_code,course_name))",
            filters={"user_id": f"eq.{user_id}"},
        )
        for row in enrolled:
            offering = row.get("course_offerings", {})
            if not isinstance(offering, dict):
                continue
            abstract_course_id = offering.get("course_id")
            course = offering.get("courses", {}) if isinstance(offering.get("courses"), dict) else {}
            course_code = course.get("course_code", "") or ""
            course_name = course.get("course_name", "") or ""

            # Match on course_code (exact or case-insensitive)
            if course_code and topic_trim.upper() == course_code.upper():
                return abstract_course_id
            # Match on course_name
            if course_name and topic_trim.lower() == course_name.lower():
                return abstract_course_id
            # Same label as graph subject roots (graph_service)
            label = f"{course_code} - {course_name}" if course_code else course_name
            if label and topic_trim == label:
                return abstract_course_id
    except Exception as e:
        print(f"Failed to resolve course_id for topic={topic_trim!r} user_id={user_id!r}: {e}")
    
    # Fallback: find via graph_nodes - look for nodes matching topic
    # that have a course_id
    node_rows = await table("graph_nodes").aselect(
        "course_id",
        filters={
            "user_id": f"eq.{user_id}",
            "concept_name": f"eq.{topic_trim}",
        },
        limit=10,
    )
    for row in (node_rows or []):
        if row.get("course_id"):
            return row["course_id"]
    
    # Try matching on subject field (legacy support)
    subject_rows = await table("graph_nodes").aselect(
        "course_id",
        filters={
            "user_id": f"eq.{user_id}",
            "subject": f"eq.{topic_trim}",
        },
        limit=1,
    )
    for row in (subject_rows or []):
        if row.get("course_id"):
            return row["course_id"]
    
    return ""


async def _get_session_offering_id(session_id: str) -> str:
    """Get the offering_id a session is scoped to, if any.

    Sessions key on the offering (0025); the abstract course id (the graph
    key) is derived from it via ``offering_course_id`` where needed.
    """
    rows = await table("sessions").aselect("offering_id", filters={"id": f"eq.{session_id}"}, limit=1)
    if rows and rows[0].get("offering_id"):
        return rows[0]["offering_id"]
    return ""


async def _session_course_id(session_id: str) -> str | None:
    """The abstract course (the graph key) behind a session's offering."""
    offering_id = await _get_session_offering_id(session_id)
    return await run_in_threadpool(offering_course_id, offering_id) if offering_id else ""


def _get_course_info(course_id: str) -> dict:
    """Get course info (code and name) for a course_id."""
    if not course_id:
        return {"course_code": "", "course_name": ""}
    try:
        rows = table("courses").select(
            "course_code,course_name",
            filters={"id": f"eq.{course_id}"},
            limit=1,
        )
        if rows:
            return {
                "course_code": rows[0].get("course_code", ""),
                "course_name": rows[0].get("course_name", ""),
            }
    except Exception as e:
        print(f"Failed to load course info for course_id={course_id!r}: {e}")
    return {"course_code": "", "course_name": ""}


def _get_catalog_chunk(course_code: str) -> str:
    """Return the catalog chunk_text for a BU course code, or empty string.

    Fetches up to 5 catalog chunks and returns the longest one — handles
    courses that were scraped from multiple listing pages (duplicates with
    slightly different content) by preferring the most complete entry.
    """
    if not course_code:
        return ""
    try:
        rows = table("course_chunks").select(
            "chunk_text",
            filters={"course_id": f"eq.{course_code}", "category": "eq.catalog"},
            limit=5,
        )
        # Decrypt BEFORE the "Prerequisites:" test and the longest-chunk choice
        # below (#484): both read the text, and against ciphertext the first
        # would never match and the second would compare base64 lengths.
        for row in rows or []:
            row["chunk_text"] = decrypt_if_present(row.get("chunk_text"))
        if rows:
            # Prefer a chunk that has an explicit Prerequisites line; fall back
            # to the longest chunk. Handles courses scraped from two listing
            # pages where one entry has prerequisites and one doesn't.
            with_prereq = [r for r in rows if "Prerequisites:" in r.get("chunk_text", "")]
            candidates = with_prereq if with_prereq else rows
            return max(candidates, key=lambda r: len(r.get("chunk_text", "")))["chunk_text"]
    except Exception as e:
        print(f"[RAG] Failed to load catalog chunk for {course_code!r}: {e}")
    return ""


async def _load_message_history(session_id: str, *, exclude_id: str | None = None) -> list:
    """Load the prior conversation as Pydantic AI `ModelMessage` objects.

    Reads the encrypted `messages` rows, decrypts at the boundary, and
    converts each turn into a `ModelRequest`/`ModelResponse` pair so
    chat_tutor_agent.run() can consume them via `message_history=` for
    multi-turn coherence.

    Roles are mapped:
      - user    -> ModelRequest(parts=[UserPromptPart(...)])
      - assistant / model -> ModelResponse(parts=[TextPart(...)])
      - anything else -> dropped (e.g. legacy 'system' rows).

    Empty/decrypt-failed content is skipped so we don't feed empty
    parts to the LLM.

    The history carries NO system/instructions text. The tutor's rules
    reach the model only because the chat tutor agents declare them as
    `instructions=` (re-sent on every request); a `system_prompt=` would
    be skipped whenever this history is non-empty, i.e. on every turn after
    the opener. Pinned by tests/test_chat_tutor_prompt_every_turn.py.

    ``exclude_id``: the current turn's own user row, left behind by an
    earlier attempt that persisted it and then failed (#761) — it is this
    turn's message, not prior history, so it must not be sent twice.
    """
    rows = await table("messages").aselect(
        "id,role,content",
        filters={"session_id": f"eq.{session_id}"},
        order="created_at.asc",
    )

    history: list = []
    for r in rows or []:
        if exclude_id and r.get("id") == exclude_id:
            continue
        raw_role = (r.get("role") or "").lower()
        content = decrypt_if_present(r.get("content"))
        if not content:
            continue
        if raw_role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=str(content))]))
        elif raw_role in ("assistant", "model"):
            history.append(ModelResponse(parts=[TextPart(content=str(content))]))
        # else: drop (legacy 'system' rows have no equivalent in
        # Pydantic AI's role taxonomy).
    return history


def _message_row(session_id: str, role: str, content: str, graph_update, message_id) -> dict:
    return {
        "id": message_id or str(uuid.uuid4()),
        "session_id": session_id,
        "role": role,
        "content": encrypt_if_present(content),
        "graph_update_json": graph_update if graph_update else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def save_message(
    session_id: str, role: str, content: str, graph_update: dict = None,
    *, message_id: str | None = None,
):
    """Write one transcript row.

    Refuses (404/409) a session discarded since the turn started (#761), so a
    turn racing end/delete gets a clean answer instead of an FK failure.

    ``message_id`` (#761): a turn-derived id (``_turn_message_id``) makes the
    write idempotent — a retried turn re-writes the same id and the duplicate
    is ignored, so a retry after a partial persist never duplicates the row.
    """
    await araise_if_discarded(session_id)
    row = _message_row(session_id, role, content, graph_update, message_id)
    if message_id:
        await table("messages").aupsert(row, on_conflict="id", ignore_duplicates=True)
    else:
        await table("messages").ainsert(row)


def save_message_sync(session_id: str, role: str, content: str, graph_update: dict = None) -> None:
    """`save_message` for `_consume_pending`, which runs in the threadpool."""
    raise_if_discarded(session_id)
    table("messages").insert(_message_row(session_id, role, content, graph_update, None))


#: Namespace for turn-derived message ids (#761). Any fixed UUID works; it
#: only has to never change, or a retry stops matching its first attempt.
_TURN_MESSAGE_NS = uuid.UUID("5f0c1d6e-7a3b-4c2e-9d41-0b6e2a7c9f13")


def _turn_message_id(session_id: str, turn_id: str, role: str) -> str:
    """The deterministic ``messages.id`` of ``role``'s row for one client turn.

    Session-scoped (the session id is hashed in), so a client-chosen turn id
    can never address another session's rows.
    """
    return str(uuid.uuid5(_TURN_MESSAGE_NS, f"{session_id}:{turn_id}:{role}"))


async def _persisted_turn(session_id: str, turn_id: str | None) -> dict | None:
    """The stored result of a turn that already persisted, or None (#761).

    A client that lost a turn's `done` (cancel, idle timeout, dropped
    connection) after the server had persisted it re-sends the SAME
    ``turn_id`` on its fallback/retry. Re-running would answer the same
    message twice and re-apply the turn's tool writes; replaying the stored
    assistant row does neither. ``mastery_changes`` is not stored per
    message, so a replay reports none (the writes themselves did land).
    """
    if not turn_id:
        return None
    rows = await table("messages").aselect(
        "content,graph_update_json",
        filters={"id": f"eq.{_turn_message_id(session_id, turn_id, 'assistant')}"},
        limit=1,
    )
    if not rows:
        return None
    graph_update = rows[0].get("graph_update_json") or {}
    if isinstance(graph_update, str):
        try:
            graph_update = json.loads(graph_update)
        except ValueError:
            graph_update = {}
    return {
        "reply": decrypt_if_present(rows[0].get("content")) or "",
        "graph_update": graph_update,
        "mastery_changes": [],
        "replayed": True,
    }


async def _replay_events(replay: dict):
    """A persisted turn re-sent on /chat/stream, in the ordinary event
    vocabulary — status:start, ONE token with the whole reply, done — the
    same shape the Rung-1 fallback already produces."""
    for ev in (
        SaplingEvent(type="status", step="start", message="Starting."),
        SaplingEvent(type="token", step="reply", message="",
                     data={"delta": replay["reply"]}),
        SaplingEvent(type="done", step="reply", message="Complete.", data=replay),
    ):
        yield sapling_event_to_sse(ev)


def get_user_name(user_id: str) -> str:
    # Display name lives on user_profiles (0024); resolve + decrypt via helper.
    return get_display_name(user_id) or "Student"


def _consume_pending(session_id: str, user_id: str) -> bool:
    """If session was started lazily, persist session row + first assistant message before user/chat.

    Callers run require_session_owner first; the user check here is a
    second line of defence and runs before anything is written, so a
    mismatched caller can never destroy or claim the owner's pending session.

    Concurrency (CodeRabbit on #709): every turn route runs this in FastAPI's
    threadpool (`_consume_pending_off_loop`), so two of the owner's requests
    can arrive while the session is still pending. Materialisation is serialised per session id by
    ``materialization_lock``; the pending entry is removed only AFTER the
    session row and the initial assistant message are written. So:

    - a request that finds no pending entry can rely on the row existing
      UNLESS the entry was discarded (end-session / delete) rather than
      materialised. A discard leaves a tombstone (``discard_pending``), and
      both the lock-free fast path and the post-wait re-check consult it, so
      a turn that passed its ownership check just before the discard answers
      409 (ended) / 404 (deleted) instead of writing messages for a session
      row that will never exist (#761). The fast path takes no lock for a
      ready session;
    - a request that loses the race waits on the lock, then finds the entry
      gone and returns, and only then writes its own messages (no FK
      failure on ``messages.session_id``);
    - ownership checks keep seeing the pending entry throughout, so a
      concurrent request is never 404'd in a gap between "no longer
      pending" and "row inserted";
    - if materialisation fails, the entry stays pending (never wrongly
      ready) and the lock is released for the next request to retry.

    The row write is an upsert that ignores a duplicate id, so a retry is
    safe even when an earlier attempt committed the row but its response was
    lost (timeout, dropped connection). Two markers on the pending payload:

    - ``_row_may_exist`` is set BEFORE the first write attempt. From then on
      end-session / rename / delete must treat the session as possibly
      having a ``sessions`` row and act on the DB too, not just on memory.
    - ``_row_written`` is set once a write has returned. It guards the
      ``session.started`` event against double-logging when a later step
      (the greeting write) fails and the request is retried.

    Sync code: the async routes call it through ``_consume_pending_off_loop``
    so the lock wait and the network writes never block the event loop.

    Returns True only when THIS call materialised the session (so the row
    was just written with ``ended_at`` NULL and the caller can skip the
    ended-session read).
    """
    if session_id not in PENDING_SESSIONS:
        raise_if_discarded(session_id, user_id)
        return False
    with materialization_lock(session_id):
        pending = PENDING_SESSIONS.get(session_id)
        if pending is None:
            # Another request materialised it (row exists) or discarded it
            # (tombstone) while we waited.
            raise_if_discarded(session_id, user_id)
            return False
        if pending["user_id"] != user_id:
            raise HTTPException(status_code=404, detail=_SESSION_NOT_FOUND)

        if not pending.get("_row_written"):
            # Sessions key on the offering (0025). The pending payload carries
            # the offering id (resolved at start-session) alongside the
            # abstract course id.
            session_data = {
                "id": session_id,
                "user_id": user_id,
                "mode": pending["mode"],
                "topic": pending["topic"],
            }
            if pending.get("offering_id"):
                session_data["offering_id"] = pending["offering_id"]

            pending["_row_may_exist"] = True
            table("sessions").upsert(session_data, on_conflict="id", ignore_duplicates=True)
            pending["_row_written"] = True
            # #117: session.started once the lazy session row actually
            # materializes. The topic is free text -> content= (fingerprint
            # only), never payload.
            events_service.log_event(
                "session.started",
                category="usage",
                user_id=user_id,
                payload={
                    "session_id": session_id,
                    "mode": pending["mode"],
                    "offering_id": pending.get("offering_id"),
                },
                content=pending["topic"],
            )
        save_message_sync(session_id, "assistant", pending["assistant_reply"], pending["graph_update"])
        PENDING_SESSIONS.pop(session_id, None)
        return True


async def _consume_pending_off_loop(session_id: str, user_id: str) -> bool:
    """`_consume_pending` for the async routes (/chat, /chat/stream, /action).

    The slow path takes a blocking threading lock (possibly held by a
    threadpool request mid-insert) and makes sync network writes, so it runs
    in the threadpool; doing it inline would freeze every request on this
    worker's event loop for as long as the insert takes. A session that is
    not pending takes the inline fast path and never leaves the loop.
    """
    if session_id not in PENDING_SESSIONS:
        await araise_if_discarded(session_id, user_id)
        return False
    return await run_in_threadpool(_consume_pending, session_id, user_id)


async def _open_turn_session(session_id: str, user_id: str) -> None:
    """The entry checks every turn route (/chat, /chat/stream, /action,
    /mode-switch) runs before touching a session (#761): not discarded,
    owned by the caller, materialised if still pending, and — once
    materialised — not ended (409).

    The tombstone check comes first so a session ended while still pending
    answers 409 SESSION_ENDED rather than the bare 404 the ownership check
    would give a session that has no row and no pending entry. A ready
    session never reaches `_consume_pending` (pinned in
    test_learn_session_ownership.py).

    With `stateless_tutor_sessions` on (#117) a session not pending in THIS
    process goes to the table: one atomic call answers tombstones and
    materialises a pending session, one `sessions` read the rest.
    """
    if session_id not in PENDING_SESSIONS and await astored():
        if not await amaterialize_stored(session_id, user_id):
            await arequire_owned_open(session_id, user_id)
        return
    await araise_if_discarded(session_id, user_id)
    await arequire_session_owner(session_id, user_id)
    if await _consume_pending_off_loop(session_id, user_id):
        return  # materialised just now, with ended_at NULL
    await arequire_session_open(session_id)


# Guardrail → HTTP status mapping (the notes precedent — routes/notes.py::
# _run_note_worker, #329). The two Pydantic AI guardrail failures are
# distinct and must not be conflated: a budget trip is deterministic
# (retrying the same turn fails identically → 413, cause-naming detail, no
# "try again" wording), while unexpected/degenerate model output is
# transient upstream trouble (→ 502, retry-friendly detail; a WARNING, not
# an exception log — pages should fire on the bare-Exception 502 below,
# which IS a bug).
_USAGE_LIMIT_DETAIL = (
    "This turn exceeded the tutor's processing budget — the conversation or "
    "message is too long to answer in one turn. Retrying the same message "
    "will hit the same limit; try a shorter message or a fresh session."
)
_MODEL_TROUBLE_DETAIL = "The tutor had trouble answering that. Please try again."


async def _agent_turn_or_http_error(turn, *, what: str):
    """Await an agent-served tutor turn, mapping guardrail failures to HTTP
    statuses. Shared by /chat, /start-session and /action (#151a — the old
    behavior degraded to the deleted `call_gemini_multiturn` pipeline)."""
    try:
        return await turn
    except UsageLimitExceeded as e:
        logger.warning("%s hit its usage budget; returning 413", what, exc_info=e)
        raise HTTPException(status_code=413, detail=_USAGE_LIMIT_DETAIL) from e
    except UnexpectedModelBehavior as e:
        logger.warning(
            "%s returned unexpected model behavior; returning 502", what, exc_info=e
        )
        raise HTTPException(status_code=502, detail=_MODEL_TROUBLE_DETAIL) from e
    except HTTPException:
        # Known states raised inside the turn (auth, 404s) pass through.
        raise
    except Exception as e:
        logger.exception("Unexpected %s failure; returning 502", what)
        raise HTTPException(status_code=502, detail=_MODEL_TROUBLE_DETAIL) from e


def _session_offering(body: StartSessionBody, course_id: str) -> str:
    """The offering a new session row keys on. A client-named
    ``body.course_id`` passes the #115 enrollment gate (404 unless the student
    is enrolled) and lands on the offering it returns; a topic-derived course
    keeps the current-term resolution."""
    if body.course_id:
        return require_course_enrollment(body.user_id, body.course_id)
    return resolve_offering(course_id, create=True) if course_id else ""


async def _start_session_agent(
    body: StartSessionBody,
    session_id: str | None = None,
    *,
    model_pref: str | None = None,
    request_id: str | None = None,
) -> dict:
    """Core start-session pipeline on chat_tutor_agent: _prepare_chat_run
    (empty history) -> agent.run -> record_agent_usage -> stash
    PENDING_SESSIONS. Replaces `_start_session_legacy` (#151a) with the same
    signature and return shape.

    Shared by the JSON route and the streaming route's Rung-1
    `nonstream_fallback` (agent failed before any token).

    `session_id`: the streaming route already minted one up front (it needs
    it for SaplingDeps before it knows whether the streamed agent or this
    fallback will serve the turn); passing it through here means a turn only
    ever has ONE session_id and PENDING_SESSIONS is stashed exactly once,
    regardless of which path serves it. `None` (the JSON route's case)
    mints a fresh one.

    `model_pref`: explicit override for the fast/smart knob; `None` falls
    through to `body.model_pref`. The streaming fallback forces "fast" (D2):
    a different, faster model is a materially better second chance than
    re-rolling the same tier, and it bounds the client's 45s idle window.

    A whitespace-only greeting raises UnexpectedModelBehavior (the #153
    bare-newline-after-tool-call quirk) so the caller's guardrail mapping —
    or the stream's Rung-1 ladder — handles it instead of stashing an empty
    greeting.

    Returns {"session_id", "reply", "graph_update", "mastery_changes",
    "graph_state"} — a superset of what the JSON route needs, and exactly
    the shape the streaming `done` event / frontend `ChatResult` expects.
    """
    if session_id is None:
        session_id = str(uuid.uuid4())

    # `request_id`: the streaming route's Rung-1 fallback passes the turn's
    # own, so its usage rows join the turn regardless of ambient context.
    request_id = request_id or current_request_id() or str(uuid.uuid4())

    # Use abstract course_id from body, or resolve it from the topic. The graph
    # + shared context key on this abstract id; the session row keys on the
    # offering `_session_offering` picks (a client-named course is gated, #115).
    course_id = body.course_id or await _get_course_id_for_topic(body.topic, body.user_id)
    offering_id = await run_in_threadpool(_session_offering, body, course_id)

    user_message = (
        f"Student wants to learn about: {body.topic}\n\n"
        "Begin the session with a warm greeting and your first question or explanation."
    )

    agent, assembled, run_kwargs, deps = await run_in_threadpool(
        _prepare_chat_run,
        user_id=body.user_id,
        session_id=session_id,
        course_id=course_id,
        mode=body.mode,
        user_message=user_message,
        message_history=[],
        use_shared_context=body.use_shared_context,
        request_id=request_id,
        model_pref=model_pref if model_pref is not None else body.model_pref,
    )

    try:
        result = record_agent_usage(
            await agent.run(assembled, **run_kwargs),
            feature="chat_tutor", task="chat_tutor", user_id=body.user_id,
            request_id=request_id,
        )
        # str — chat_tutor agents return plain Markdown. Read every text
        # part this turn wrote (`_new_run_text`), not `.output`: `.output` is
        # only the FINAL model response, so a Claude turn that explains,
        # calls a tool, then adds a line would persist just that line (ADR
        # 0030). (The stale-history hazard doesn't apply here — this call
        # passes `message_history=[]` — but the same reader keeps all three
        # non-streamed paths and the stream persisting identical text.)
        reply = _new_run_text(result)
        if not reply.strip():
            # Same textless shape as the chat turns (#646), and this is the
            # LAST rung on the opener path: a streamed /start-session/stream
            # turn that goes textless with no writes degrades to Rung 1,
            # which is this function on the fast tier — Flash-Lite, the
            # model that produces textless turns in the first place. Raising
            # here ends the student's very first interaction on "The tutor
            # is unavailable". Finish the turn if the model will; the
            # opener's tool results are in its messages just like a chat
            # turn's.
            try:
                rescued = await _continuation_text(agent, result, run_kwargs, request_id=request_id)
            except Exception:
                logger.warning(
                    "Continuation after a textless session greeting failed",
                    exc_info=True,
                )
                rescued = None
            if rescued:
                logger.info("Textless session greeting rescued by a continuation")
                reply = rescued
            else:
                raise UnexpectedModelBehavior(
                    "chat_tutor produced a whitespace-only session greeting"
                )
    except Exception as exc:
        # PR #472 review: THIS run's tools may have written graph/mastery
        # before the failure. Stamp the write-state so the streaming
        # route's fallback error can set retryable correctly — a client
        # retry after real writes would re-apply them.
        exc.sapling_wrote = bool(deps.graph_updates or deps.mastery_changes)
        raise

    # Graph writes (if any) already landed in-band via the agent's tools;
    # merge their payloads for the response echo, exactly like the chat turn.
    graph_update = merge_graph_updates(deps.graph_updates)

    # Lazy-session contract preserved: nothing hits `sessions` until the
    # first chat turn calls _consume_pending — exactly once per session_id.
    await astash_pending(session_id, {
        "user_id": body.user_id,
        "mode": body.mode,
        "topic": body.topic,
        "course_id": course_id,        # abstract — graph + shared-context key
        "offering_id": offering_id,    # term-scoped — the session-row key
        "use_shared_context": body.use_shared_context,
        "assistant_reply": reply,
        "graph_update": graph_update,
    })

    return {
        "session_id": session_id,
        "reply": reply,
        "graph_update": graph_update,
        "mastery_changes": list(deps.mastery_changes),
        "graph_state": await run_in_threadpool(get_graph, body.user_id),
    }


@router.post("/start-session")
async def start_session(body: StartSessionBody, request: Request):
    await guard_off_loop(require_self, body.user_id, request)
    result = await _agent_turn_or_http_error(
        _start_session_agent(body), what="start-session agent"
    )
    return {
        "session_id": result["session_id"],
        "initial_message": result["reply"],
        "graph_state": result["graph_state"],
    }


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


async def _chat_via_agent(
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
) -> tuple[dict, tuple[str, str | None]]:
    """Run chat_tutor_agent and return the wire response shape.

    Returns ``({"reply": str, "graph_update": dict, "mastery_changes": list},
    (model_tier, tutor_model))`` — the wire dict, and what the run actually
    ran on (see `_ran_on`), kept out of the dict so it can never leak.
    Graph changes are persisted in-band during the agent run by
    `apply_graph_update_tool` / `update_mastery_tool` (registered on
    chat_tutor); the tools also accumulate their payloads on `deps` so the
    route can echo `graph_update` (for graph_update_json / concepts_covered)
    and the real `mastery_changes` deltas back to the client. Both are
    empty when nothing changed this turn.

    `use_shared_context=False` flips the model into "no class-aggregate"
    mode by appending a constraint instruction to the user message —
    the chat tutor's class-aggregate tools (read_user_progress, etc.)
    aggregate per-user data, but a future shared-context tool would
    need this guard rail. Keeping the constraint in-band rather than
    branching the agent surface keeps the agent definition stable.
    """
    agent, user_message, run_kwargs, deps = await run_in_threadpool(
        _prepare_chat_run,
        user_id=user_id,
        session_id=session_id,
        course_id=course_id,
        mode=mode,
        user_message=user_message,
        message_history=message_history,
        use_shared_context=use_shared_context,
        request_id=request_id,
        model_pref=model_pref,
    )

    try:
        result = record_agent_usage(
            await agent.run(user_message, **run_kwargs),
            feature="chat_tutor", task="chat_tutor", user_id=deps.user_id,
            request_id=request_id,
        )
        # `.output` alone is a HISTORY read on this path: `_prepare_chat_run`
        # puts `message_history` into `run_kwargs`, so a textless model
        # response makes `.output` resolve to the PREVIOUS turn's assistant
        # message — fully formed, non-blank, and therefore invisible to the
        # `not reply.strip()` guard below. Trust it only when this run
        # actually produced text, mirroring `stream_agent_turn`'s narrowing.
        # This matters here more than anywhere: `_chat_turn_json` is both the
        # POST /api/learn/chat route AND the streamed route's Rung-1
        # fallback, which is exactly where the streaming fix now sends
        # textless turns. And `.output` is only the FINAL model response even
        # when this run did write text: a Claude turn that explains, calls a
        # tool, then adds a line would persist just that line (ADR 0030) — so
        # the reply is always this run's own joined text.
        reply = _new_run_text(result)

        if not reply.strip():
            # #153 / ADR-0023 follow-up: gemini-2.5-pro occasionally follows an
            # end-of-turn tool call with a bare-newline final text; and per the
            # narrowing above, a turn that ended after tool calls with no text
            # part reaches here blank instead of replaying history.
            #
            # Try to FINISH the turn before failing it (#646). Unlike the
            # streamed route there is no Rung-1 ladder below this — this IS
            # that rung — so the alternative is a 502 for a turn whose tools
            # have already run. Fire regardless of whether writes landed:
            # nothing else will re-run, so there is no better answer waiting.
            try:
                rescued = await _continuation_text(agent, result, run_kwargs, request_id=request_id)
            except Exception:
                # Second model call; a failure here must degrade to the
                # pre-#646 behaviour, never surface as its own error.
                logger.warning(
                    "Continuation after a textless JSON turn failed",
                    exc_info=True,
                )
                rescued = None
            if rescued:
                logger.info("Textless JSON turn rescued by a continuation")
                reply = rescued
            else:
                # Still nothing: this turn produced no reply. Treat it as
                # degenerate model output so the caller's
                # UnexpectedModelBehavior handling — the route's 502 mapping,
                # or the stream fallback's Rung-1 ladder — applies instead of
                # persisting a stale or empty assistant row.
                # Usage was recorded above — tokens were spent.
                raise UnexpectedModelBehavior(
                    "chat_tutor produced no reply text this turn"
                )
    except Exception as exc:
        # PR #472 review: THIS run's tools may have written graph/mastery
        # before the failure. Stamp the write-state so the streaming
        # route's fallback error can set retryable correctly — a client
        # retry after real writes would re-apply them.
        exc.sapling_wrote = bool(deps.graph_updates or deps.mastery_changes)
        raise

    # Merge all graph update payloads accumulated by tools during this run
    # into a single dict so the route can persist graph_update_json and
    # end_session can derive concepts_covered correctly.
    merged_graph_update = merge_graph_updates(deps.graph_updates)

    response = {
        "reply": reply,
        "graph_update": merged_graph_update,
        # Real before/after deltas accumulated by update_mastery_tool.
        # Empty when no mastery moved this turn.
        "mastery_changes": deps.mastery_changes,
    }
    # Out of band, never in the wire dict: what this run actually ran on, for
    # the #640 router's event.
    return response, _ran_on(result, agent, run_kwargs, model_pref)


def _turn_row_ids(body: ChatBody) -> tuple[str | None, str | None]:
    """(user row id, assistant row id) for this turn: deterministic when the
    client sent a ``turn_id``, else (None, None) — fresh random ids."""
    if not body.turn_id:
        return None, None
    return (
        _turn_message_id(body.session_id, body.turn_id, "user"),
        _turn_message_id(body.session_id, body.turn_id, "assistant"),
    )


async def _save_turn_rows(
    body: ChatBody, reply: str, graph_update: dict | None,
    *, user_row_id: str | None, assistant_row_id: str | None,
) -> None:
    """Persist one chat turn: the user row, then the assistant row.

    Partial persistence (#761): the two rows are two writes, so the second
    can fail after the first landed. With a ``turn_id`` both writes are
    idempotent (turn-derived ids, duplicates ignored), so a retry re-writes
    nothing it already has — and the retry's history load skips the orphan
    user row. WITHOUT one a retry would duplicate the user row, so the
    failure is stamped ``sapling_wrote`` — the same flag the agent helpers
    use for tool writes — and the stream reports ``retryable: False``.
    """
    await save_message(body.session_id, "user", body.message, message_id=user_row_id)
    try:
        await save_message(body.session_id, "assistant", reply, graph_update,
                           message_id=assistant_row_id)
    except Exception as exc:
        if not body.turn_id:
            exc.sapling_wrote = True
        raise


async def _chat_turn_json(
    body: ChatBody,
    request: Request,
    *,
    model_pref: str | None = None,
) -> dict:
    """One full non-streaming chat turn: agent run, persistence, and the
    #117 `chat.message_sent` emission — the SINGLE emission site for
    JSON-served turns (#151a; the streamed route's on_complete hook is the
    streamed twin, and at most one of the two serves any turn).

    Shared by the JSON /chat route (wrapped in the guardrail → status
    mapping) and the streaming route's Rung-1 `nonstream_fallback`, which
    forces `model_pref="fast"` (D2): a different, faster model is a
    materially better second chance than re-rolling the same tier, and it
    bounds the client's 45s idle window.

    Persist ordering preserved: prior turns load BEFORE the new user row is
    written; the user row and assistant row are written only after the agent
    run succeeds, so a failed turn persists nothing.

    This is also one of the two points the observe-only tutor router (#640)
    is scheduled from — see `_observe_persisted_turn`.
    """
    # Unify with the middleware-stamped request ID so agent traces and
    # any downstream error payloads share the same correlation key.
    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )

    # The session keys on the offering; the agent's graph tools key on the
    # abstract course derived from it. Load prior turns BEFORE writing the
    # new user row, so the message_history we hand the agent contains only
    # the conversation state up to (but not including) the current turn.
    user_row_id, assistant_row_id = _turn_row_ids(body)
    course_id, message_history = await asyncio.gather(
        _session_course_id(body.session_id),
        _load_message_history(body.session_id, exclude_id=user_row_id),
    )

    response, ran_on = await _chat_via_agent(
        user_id=body.user_id,
        session_id=body.session_id,
        course_id=course_id,
        mode=body.mode,
        user_message=body.message,
        message_history=message_history,
        use_shared_context=body.use_shared_context,
        request_id=request_id,
        model_pref=model_pref if model_pref is not None else body.model_pref,
    )

    # Encryption happens inside save_message (`encrypt_if_present`).
    await _save_turn_rows(body, response["reply"], response.get("graph_update") or None,
                          user_row_id=user_row_id, assistant_row_id=assistant_row_id)

    # #117: one chat.message_sent per persisted turn. The message text is
    # fingerprinted via content= — it never enters a payload. request_id is
    # explicit, the same id whichever path (JSON route or the stream's
    # fallback) serves the turn.
    events_service.log_event(
        "chat.message_sent",
        category="usage",
        user_id=body.user_id,
        request_id=request_id,
        payload={"mode": body.mode, "session_id": body.session_id},
        content=body.message,
    )
    _observe_persisted_turn(
        body, history=message_history, ran_on=ran_on, request_id=request_id,
    )

    return response


@router.post("/chat")
async def chat(body: ChatBody, request: Request):
    await guard_off_loop(require_self, body.user_id, request)
    await _open_turn_session(body.session_id, body.user_id)
    # #761: the client's fallback for a stream whose `done` it never saw. If
    # that turn already persisted, answer with it instead of running it again.
    replay = await _persisted_turn(body.session_id, body.turn_id)
    if replay is not None:
        return replay
    return await _agent_turn_or_http_error(
        _chat_turn_json(body, request), what="chat agent"
    )


@router.post("/chat/stream")
async def chat_stream(body: ChatBody, request: Request):
    """SSE token-streaming chat turn (#70) with live graph deltas (#74).

    The JSON /chat pipeline (`_chat_turn_json`, on the fast tier) is the
    server-side Rung-1 fallback, and the client keeps the JSON route as its
    own non-streaming rung. No DBOS
    wrap here — stream routes are deliberately outside durable execution
    (ADR 0011); retries are client-driven, and idempotent when the client
    sends the same ``turn_id`` on the stream and on its fallback/retry
    (#761): the writes dedupe on turn-derived ids, and a turn that already
    persisted is replayed (here and on /chat) instead of run again.
    """
    await guard_off_loop(require_self, body.user_id, request)
    await _open_turn_session(body.session_id, body.user_id)

    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )

    # #761: a re-sent turn that already persisted replays its stored reply
    # over the same event vocabulary instead of running again.
    replay = await _persisted_turn(body.session_id, body.turn_id)
    if replay is not None:
        return EventSourceResponse(
            _replay_events(replay),
            headers={"X-Request-ID": request_id, "Cache-Control": SSE_CACHE_CONTROL},
        )

    # Load prior turns BEFORE the new user row is written, so history is
    # conversation state up to (not including) this turn.
    user_row_id, assistant_row_id = _turn_row_ids(body)
    course_id, message_history = await asyncio.gather(
        _session_course_id(body.session_id),
        _load_message_history(body.session_id, exclude_id=user_row_id),
    )

    agent, assembled, run_kwargs, deps = await run_in_threadpool(
        _prepare_chat_run,
        user_id=body.user_id,
        session_id=body.session_id,
        course_id=course_id,
        mode=body.mode,
        user_message=body.message,
        message_history=message_history,
        use_shared_context=body.use_shared_context,
        request_id=request_id,
        model_pref=body.model_pref,
    )
    # No extra model override here: _prepare_chat_run already applied the
    # seam-aware fast/smart preference (_resolve_model_pref), and the agent's
    # own model is _LoopSafeGoogleModel in real mode / FunctionModel under
    # SAPLING_MODEL_MODE=function — forcing a GoogleModel here would bypass
    # the e2e seam and re-create the cross-loop client problem #453 solved.

    #: What the streamed run actually ran on — set by `_usage` (on_usage runs
    #: before on_complete), read by `_persist` for the #640 router's event.
    ran: dict = {}

    async def _persist(reply: str, graph_update: dict, mastery_changes: list) -> dict:
        # Mirrors chat()'s ordering: user row, then assistant row. Runs only
        # after the agent run completes, so a disconnect mid-generation
        # persists nothing. Encryption happens inside save_message. Async, so
        # stream_agent_turn shields it: a disconnect from here on still lets
        # the turn finish persisting (#761).
        await _save_turn_rows(body, reply, graph_update or None,
                              user_row_id=user_row_id, assistant_row_id=assistant_row_id)
        # #117: same event as the JSON route, from the on_complete hook so a
        # disconnected mid-generation turn emits nothing. request_id is
        # explicit. The request contextvars (request id, DNT/GPC, request
        # view) DO survive here: Starlette runs the streaming body in a child
        # task whose context was copied before RequestIDMiddleware reset its
        # own, and the shielded persist task copies it again — so the PostHog
        # mirror still honours DNT/GPC. Pinned by tests/test_sse_request_context.py.
        events_service.log_event(
            "chat.message_sent",
            category="usage",
            user_id=body.user_id,
            request_id=request_id,
            payload={"mode": body.mode, "session_id": body.session_id},
            content=body.message,
        )
        # #640: the streamed twin of `_chat_turn_json`'s router call, labelled
        # with the run `_usage` saw (on_usage runs before on_complete).
        ran_on = ran.get("on") or _ran_on(None, agent, run_kwargs, body.model_pref)
        _observe_persisted_turn(
            body, history=message_history, ran_on=ran_on, request_id=request_id,
        )
        return {}

    async def _fallback() -> dict:
        # Rung 1 only (agent failed before any token, no writes landed —
        # stream_agent_turn's writes-guard enforces that). _chat_turn_json
        # persists its own user + assistant rows and emits its own
        # chat.message_sent, so _persist must not also run —
        # stream_agent_turn enforces that exclusivity. model_pref="fast"
        # (D2): the second chance runs on the fast tier.
        return await _chat_turn_json(body, request, model_pref="fast")

    def _usage(run_result) -> None:
        # #118: streaming turns report usage via the final AgentRunResultEvent,
        # surfaced by stream_agent_turn's on_usage hook after the run completes.
        # request_id is explicit so the row is tied to its turn (and to the
        # turn's decision.made) by construction, not by ambient context.
        record_agent_usage(
            run_result, feature="chat_tutor", task="chat_tutor", user_id=body.user_id,
            request_id=request_id,
        )
        ran["on"] = _ran_on(run_result, agent, run_kwargs, body.model_pref)

    async def event_stream():
        async for ev in stream_agent_turn(
            agent=agent,
            user_message=assembled,
            run_kwargs=run_kwargs,
            deps=deps,
            on_complete=_persist,
            nonstream_fallback=_fallback,
            on_usage=_usage,
            request_id=request_id,
            continuation=lambda rr: _continuation_text(agent, rr, run_kwargs, request_id=request_id),
        ):
            yield sapling_event_to_sse(ev)

    return EventSourceResponse(
        event_stream(),
        headers={"X-Request-ID": request_id, "Cache-Control": SSE_CACHE_CONTROL},
    )


@router.post("/start-session/stream")
async def start_session_stream(body: StartSessionBody, request: Request):
    """Streamed session opener — runs chat_tutor_agent and streams the
    greeting (#152/#151).

    The JSON /start-session route shares the same `_start_session_agent`
    pipeline and remains the client's non-streaming fallback.
    PENDING_SESSIONS lazy materialization is preserved exactly: the row is
    still written on first chat, by _consume_pending.

    Rung 1 (agent fails before any token, no writes landed) falls back to
    `_start_session_agent` — the JSON route's own pipeline, on the fast
    tier (D2). `stream_agent_turn` guarantees AT MOST one of `on_complete`
    (`_stash`, below) / `nonstream_fallback` (`_fallback`, below) runs per
    turn — never both — so PENDING_SESSIONS is stashed at most once:
    `_stash` on the streamed-success path, `_start_session_agent`
    internally on the Rung-1 fallback path. A Rung-2 error (failure after
    the greeting started streaming) stashes NOTHING for this session_id —
    the client never received it in a `done` event, so a retry simply mints
    a fresh session.
    """
    await guard_off_loop(require_self, body.user_id, request)
    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )
    session_id = str(uuid.uuid4())

    course_id = body.course_id or await _get_course_id_for_topic(body.topic, body.user_id)
    offering_id = await run_in_threadpool(_session_offering, body, course_id)

    user_message = (
        f"Student wants to learn about: {body.topic}\n\n"
        "Begin the session with a warm greeting and your first question or explanation."
    )

    agent, assembled, run_kwargs, deps = await run_in_threadpool(
        _prepare_chat_run,
        user_id=body.user_id,
        session_id=session_id,
        course_id=course_id,
        mode=body.mode,
        user_message=user_message,
        message_history=[],
        use_shared_context=body.use_shared_context,
        request_id=request_id,
        model_pref=body.model_pref,
    )
    # No extra model override here: _prepare_chat_run already applied the
    # seam-aware fast/smart preference (_resolve_model_pref), and the agent's
    # own model is _LoopSafeGoogleModel in real mode / FunctionModel under
    # SAPLING_MODEL_MODE=function — forcing a GoogleModel here would bypass
    # the e2e seam and re-create the cross-loop client problem #453 solved.

    def _stash(reply: str, graph_update: dict, mastery_changes: list) -> dict:
        # Streamed agent path succeeded. Same lazy contract as the JSON
        # route: nothing hits `sessions` until the first chat turn calls
        # _consume_pending. Mutually exclusive with `_fallback` below — see
        # the docstring above.
        stash_pending(session_id, {
            "user_id": body.user_id,
            "mode": body.mode,
            "topic": body.topic,
            "course_id": course_id,
            "offering_id": offering_id,
            "use_shared_context": body.use_shared_context,
            "assistant_reply": reply,
            "graph_update": graph_update,
        })
        return {"session_id": session_id, "graph_state": get_graph(body.user_id)}

    async def _fallback() -> dict:
        # Rung 1 only (agent failed before any token, no writes landed).
        # Reuses the SAME session_id already minted above — via
        # `session_id=` — so this turn only ever has one session_id,
        # whichever path serves it. `_start_session_agent` stashes
        # PENDING_SESSIONS itself; `_stash` above must NOT also run, and
        # stream_agent_turn enforces that exclusivity (at most one of
        # on_complete/nonstream_fallback executes per turn — see
        # stream_agent_turn's docstring). model_pref="fast" (D2): the
        # second chance runs on the fast tier.
        return await _start_session_agent(body, session_id, model_pref="fast",
                                          request_id=request_id)

    def _usage(run_result) -> None:
        # #118: same hook as /chat/stream — the opener runs the same
        # chat_tutor agent, so it rolls up under the same feature/task. Explicit
        # request_id, as in /chat/stream.
        record_agent_usage(
            run_result, feature="chat_tutor", task="chat_tutor", user_id=body.user_id,
            request_id=request_id,
        )

    async def event_stream():
        async for ev in stream_agent_turn(
            agent=agent,
            user_message=assembled,
            run_kwargs=run_kwargs,
            deps=deps,
            on_complete=_stash,
            nonstream_fallback=_fallback,
            on_usage=_usage,
            request_id=request_id,
            continuation=lambda rr: _continuation_text(agent, rr, run_kwargs, request_id=request_id),
        ):
            yield sapling_event_to_sse(ev)

    return EventSourceResponse(
        event_stream(),
        headers={"X-Request-ID": request_id, "Cache-Control": SSE_CACHE_CONTROL},
    )


def _session_summary(session_id: str, started_at: str, ended_at: str | None = None) -> dict:
    """The end-of-session summary: concepts touched (from the transcript's
    graph_update_json) and minutes from start to ``ended_at`` (now if None).
    Reads only — safe to recompute for a repeat end."""
    msgs = table("messages").select(
        "graph_update_json",
        filters={"session_id": f"eq.{session_id}"},
    )

    concepts_covered = set()
    for msg in msgs:
        if msg["graph_update_json"]:
            try:
                gu = msg["graph_update_json"]
                if isinstance(gu, str):
                    gu = json.loads(gu)
                for upd in gu.get("updated_nodes", []):
                    concepts_covered.add(upd["concept_name"])
                for nn in gu.get("new_nodes", []):
                    concepts_covered.add(nn["concept_name"])
            except Exception:
                pass

    return {
        "concepts_covered": list(concepts_covered),
        "mastery_changes": [],
        "new_connections": [],
        "time_spent_minutes": _elapsed_minutes(started_at, until=ended_at),
        "recommended_next": [],
    }


def _stored_session_summary(session_id: str) -> dict:
    """What a repeat /end-session returns (#761): the summary the closing
    call stored, or — if that call hasn't written it yet — the same summary
    recomputed up to the stored ended_at. Never writes."""
    rows = table("sessions").select(
        "started_at,ended_at,summary_json",
        filters={"id": f"eq.{session_id}"},
        limit=1,
    )
    row = rows[0] if rows else {}
    stored = row.get("summary_json")
    if stored:
        try:
            summary = decrypt_json_column(stored)
            if isinstance(summary, dict):
                return summary
        except Exception:
            logger.warning("stored session summary unreadable; recomputing", exc_info=True)
    return _session_summary(session_id, row.get("started_at") or "", row.get("ended_at"))


@router.post("/end-session")
def end_session(body: EndSessionBody, request: Request):
    if body.user_id:
        require_self(body.user_id, request)
    else:
        body.user_id = get_session_user_id(request)
    # A session already ended while still pending has no row and no pending
    # entry left; its tombstone is what proves the caller ended it (#761).
    ended_while_pending = discarded_reason(body.session_id, body.user_id) == "ended"
    if not ended_while_pending:
        require_session_owner(body.session_id, body.user_id)
    empty = {
        "concepts_covered": [],
        "mastery_changes": [],
        "new_connections": [],
        "time_spent_minutes": 0,
        "recommended_next": [],
    }
    # Discard under the materialisation lock so a concurrent first turn can't
    # insert the row after we drop the entry. A pending session whose row was
    # never attempted has nothing in the DB to end. One whose materialisation
    # attempted the row (and then failed, say on the greeting) may have a
    # row, so it is ended in the DB too, as is one that materialised while
    # we waited. The discard leaves an "ended" tombstone, so a turn racing
    # this end answers 409 instead of writing into a session with no row.
    popped = discard_if_pending(body.session_id, user_id=body.user_id, reason="ended")
    if popped is not None and not _session_row_may_exist(popped):
        return {"summary": empty}

    session_rows = table("sessions").select(
        "user_id,started_at",
        filters={"id": f"eq.{body.session_id}"},
    )
    if not session_rows:
        if popped is not None or ended_while_pending:
            return {"summary": empty}  # the attempted row write never landed
        raise HTTPException(status_code=404, detail=_SESSION_NOT_FOUND)
    session = session_rows[0]

    # #761: the end is CONDITIONAL on the session still being open, and the
    # returned rows say whether THIS call closed it. Only that call awards,
    # emits session.ended and runs the session_* achievements — which are
    # computed from ended_at, so an unconditional re-end let a student move
    # ended_at to a chosen hour and farm Early Bird / Night Owl / Deep Focus.
    # A repeat end returns the stored summary and changes nothing.
    ended_at = datetime.now(timezone.utc).isoformat()
    closed = table("sessions").update(
        {"ended_at": ended_at},
        filters={"id": f"eq.{body.session_id}", "ended_at": "is.null"},
    )
    if not closed:
        return {"summary": _stored_session_summary(body.session_id), "achievements_earned": []}

    # The row above is the commit point for "session completed" — award
    # immediately after it, keyed on the session id. Only the call that
    # closed the session gets here; the xp_events idempotency key is a
    # second line of defence.
    award_xp_safe(
        body.user_id, "session_completed",
        source_type="session", source_id=body.session_id,
    )

    # touch_streak_safe shares this exact commit point: it's the same
    # post-"session completed" moment as the XP award above, past the
    # pending-session early return, and touch_streak's own same-day check
    # makes a double end-session call a no-op just like the xp_events key
    # does for the award above. Run it before the login_streak achievement
    # check below so that check sees today's advanced streak_count.
    touch_streak_safe(body.user_id)

    summary = _session_summary(body.session_id, session["started_at"], ended_at)
    elapsed_minutes = summary["time_spent_minutes"]
    concepts_covered = summary["concepts_covered"]

    # #117: session.ended for real (materialized) sessions only — the pending
    # early-return above emits nothing. concepts_covered is a COUNT; the
    # concept names never enter the payload. No timestamps in payload either
    # (created_at is a DB default).
    events_service.log_event(
        "session.ended",
        category="usage",
        user_id=body.user_id,
        payload={
            "session_id": body.session_id,
            "time_spent_minutes": elapsed_minutes,
            "concepts_covered": len(concepts_covered),
        },
    )

    table("sessions").update(
        {"summary_json": encrypt_json(summary)},
        filters={"id": f"eq.{body.session_id}"},
    )

    # Check for achievements after session end
    newly_earned = []
    try:
        from services.achievement_service import check_achievements
        newly_earned = check_achievements(body.user_id, "login_streak", {})
        newly_earned += check_achievements(body.user_id, "session_count", {})
        # A finished session is the only thing that advances these. Without
        # them `deep-focus` (session_minutes), `early-bird`
        # (session_before_hour), `night-owl` (session_after_midnight) and
        # `perfect-week` (goal_streak) are live badges nothing can award.
        # Fired here, after the sessions row has its ended_at, because every
        # one of these stats is computed from ended_at.
        newly_earned += check_achievements(body.user_id, "session_minutes", {})
        newly_earned += check_achievements(body.user_id, "session_before_hour", {})
        newly_earned += check_achievements(body.user_id, "session_after_midnight", {})
        # goal_streak counts days that met daily_goal_xp; the session_completed
        # award above may well be what tipped today over the line.
        newly_earned += check_achievements(body.user_id, "goal_streak", {})
    except Exception:
        pass

    return {"summary": summary, "achievements_earned": newly_earned}


@router.get("/sessions/{user_id}")
async def list_sessions(user_id: str, request: Request, limit: int = 10):
    await guard_off_loop(require_self, user_id, request)
    sessions = await table("sessions").aselect(
        "id,user_id,topic,mode,offering_id,started_at,ended_at",
        filters={"user_id": f"eq.{user_id}"},
        order="started_at.desc",
        limit=limit,
    )
    # One message-count read per session, concurrently rather than in turn.
    counts = await asyncio.gather(*(
        table("messages").aselect("id", filters={"session_id": f"eq.{s['id']}"})
        for s in sessions
    ))
    # Sessions key on the offering; the frontend speaks abstract course ids.
    # Map each offering → its abstract course once.
    offering_to_course: dict[str, str | None] = {}
    result = []
    for s, msgs in zip(sessions, counts):
        off_id = s.get("offering_id")
        if off_id and off_id not in offering_to_course:
            offering_to_course[off_id] = await run_in_threadpool(offering_course_id, off_id)
        result.append({
            "id": s["id"],
            "topic": s["topic"],
            "mode": s["mode"],
            "course_id": offering_to_course.get(off_id),
            "started_at": s["started_at"],
            "ended_at": s.get("ended_at"),
            "message_count": len(msgs),
            "is_active": s.get("ended_at") is None,
        })
    return {"sessions": result}


@router.patch("/sessions/{session_id}")
def rename_session(session_id: str, body: RenameSessionBody, request: Request):
    require_self(body.user_id, request)
    topic = body.topic.strip()
    if not topic or len(topic) > 120:
        raise HTTPException(status_code=400, detail="Topic must be 1-120 characters")

    require_session_owner(session_id, body.user_id)
    # A pending session: rename the copy a later materialisation will write
    # (and the row too if an earlier attempt may already have written it).
    if rename_pending(session_id, topic):
        return {"updated": True, "session": {"id": session_id, "topic": topic}}

    table("sessions").update(
        {"topic": topic},
        filters={"id": f"eq.{session_id}"},
    )
    return {"updated": True, "session": {"id": session_id, "topic": topic}}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, request: Request, user_id: str | None = Query(None)):
    if user_id:
        require_self(user_id, request)
    else:
        user_id = get_session_user_id(request)
    # Idempotent and unrevealing (#709 review): a missing OR foreign session is a
    # no-op 200 — nothing is deleted, and the answer never says whether the id
    # exists. A second delete (another tab, a double click) still succeeds.
    if not session_owned_by(session_id, user_id):
        return {"deleted": True}
    # Every delete leaves a "deleted" tombstone (#761): a turn already past
    # its ownership check answers 404 at its next write instead of an FK
    # failure (or, for a pending session, instead of materialising a row the
    # student just deleted).
    popped = discard_if_pending(session_id, user_id=user_id, reason="deleted", always=True)
    if popped is not None and not _session_row_may_exist(popped):
        return {"deleted": True}
    # A row may exist (an attempted materialisation, one that finished while
    # we waited, or a live session): delete it. Both deletes are no-ops if not.
    table("messages").delete({"session_id": f"eq.{session_id}"})
    table("sessions").delete({"id": f"eq.{session_id}"})
    return {"deleted": True}


@router.get("/sessions/{session_id}/resume")
async def resume_session(session_id: str, request: Request):
    user_id = await guard_off_loop(get_session_user_id, request)
    await arequire_session_owner(session_id, user_id)
    # .get(), not `in` + [...]: a concurrent first turn or delete can drop the
    # entry in between. Gone means it materialised (or was discarded): read
    # the DB below.
    p = await aget_pending(session_id)
    if p is not None:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "session": {
                "id": session_id,
                "user_id": p["user_id"],
                "topic": p["topic"],
                "mode": p["mode"],
                "course_id": p.get("course_id"),
                "started_at": now,
                "ended_at": None,
            },
            "messages": [
                {
                    "id": "pending_assistant",
                    "role": "assistant",
                    "content": p["assistant_reply"],
                    "created_at": now,
                },
            ],
        }

    session_rows = await table("sessions").aselect(
        "id,user_id,topic,mode,started_at,ended_at,offering_id",
        filters={"id": f"eq.{session_id}"},
    )
    if not session_rows:
        raise HTTPException(status_code=404, detail=_SESSION_NOT_FOUND)

    # Expose the abstract course id (derived from the offering) for the
    # frontend, alongside the stored offering id.
    session = dict(session_rows[0])
    session["course_id"] = await run_in_threadpool(offering_course_id, session.get("offering_id"))

    msgs = await table("messages").aselect(
        "id,role,content,created_at",
        filters={"session_id": f"eq.{session_id}"},
        order="created_at.asc",
    )
    return {
        "session": session,
        "messages": [
            {**m, "content": decrypt_if_present(m["content"])} for m in msgs
        ],
    }


async def _action_turn(body: ActionBody, request: Request) -> dict:
    """One hint/confused/skip turn on chat_tutor_agent (#151a, D3-A1):
    same "[ACTION: ...]" user message the legacy pipeline sent, full prior
    history, persist assistant-only (today's shape — action turns never
    write a user row). Graph writes land in-band via the agent's tools.

    Function-mode note: dispatch is by task, and this runs task
    "chat_tutor" — the E2E lane's chat_tutor handler covers it with no new
    handler registration.
    """
    action_prompts = {
        "hint": "The student asked for a hint. Give a small scaffold or clue without giving away the answer.",
        "confused": "The student said they are confused. Identify the likely point of confusion and re-explain with a different analogy.",
        "skip": "The student wants to skip this concept. Acknowledge and transition to the next recommended concept.",
    }
    action_message = f"[ACTION: {action_prompts.get(body.action_type, '')}]"

    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )

    # Session keys on the offering; the graph + shared context key on the
    # abstract course derived from it.
    course_id, message_history = await asyncio.gather(
        _session_course_id(body.session_id), _load_message_history(body.session_id),
    )

    agent, assembled, run_kwargs, deps = await run_in_threadpool(
        _prepare_chat_run,
        user_id=body.user_id,
        session_id=body.session_id,
        course_id=course_id,
        mode=body.mode,
        user_message=action_message,
        message_history=message_history,
        use_shared_context=body.use_shared_context,
        request_id=request_id,
        model_pref=body.model_pref,
    )

    result = record_agent_usage(
        await agent.run(assembled, **run_kwargs),
        feature="chat_tutor", task="chat_tutor", user_id=body.user_id,
        request_id=request_id,
    )
    # History-bearing run (`_load_message_history` above), so `.output` alone
    # would hand back the previous turn's assistant message when this turn's
    # model response carries no text part — and `save_message` below would
    # persist that duplicate — and is only the FINAL model response anyway,
    # dropping text written before a tool call (ADR 0030). See `_new_run_text`.
    reply = _new_run_text(result)
    if not reply.strip():
        # #153: degenerate whitespace-only output, or a turn that ended after
        # tool calls with no text at all. Finish the turn if the model will
        # (#646) — an action turn has no fallback rung at all, so the
        # alternative is failing work the tools already did.
        try:
            rescued = await _continuation_text(agent, result, run_kwargs, request_id=request_id)
        except Exception:
            logger.warning(
                "Continuation after a textless action turn failed", exc_info=True
            )
            rescued = None
        if rescued:
            logger.info("Textless action turn rescued by a continuation")
            reply = rescued
        else:
            # Surface through the guardrail mapping rather than persisting an
            # empty or stale assistant row.
            raise UnexpectedModelBehavior(
                "chat_tutor produced no action reply text this turn"
            )

    graph_update = merge_graph_updates(deps.graph_updates)
    await save_message(body.session_id, "assistant", reply, graph_update or None)
    return {"reply": reply, "graph_update": graph_update}


@router.post("/action")
async def action(body: ActionBody, request: Request):
    await guard_off_loop(require_self, body.user_id, request)
    await _open_turn_session(body.session_id, body.user_id)
    return await _agent_turn_or_http_error(
        _action_turn(body, request), what="action agent"
    )


@router.post("/mode-switch")
async def mode_switch(body: ModeSwitchBody, request: Request):
    await guard_off_loop(require_self, body.user_id, request)
    if body.new_mode not in MODE_DISPLAY_NAMES:
        # sessions.mode is CHECK-constrained to these three; refuse before
        # the write rather than surface the constraint as a 500.
        raise HTTPException(status_code=422, detail="Unknown tutor mode")
    await _open_turn_session(body.session_id, body.user_id)
    # #761: the switch is a session state change, not just a message — the
    # stored mode is what the session list and resume report.
    await table("sessions").aupdate(
        {"mode": body.new_mode},
        filters={"id": f"eq.{body.session_id}", "ended_at": "is.null"},
    )
    student_name = (await run_in_threadpool(get_user_name, body.user_id)).split()[0]
    session_rows = await table("sessions").aselect(
        "topic", filters={"id": f"eq.{body.session_id}"}, limit=1
    )
    topic = session_rows[0]["topic"] if session_rows else "this topic"
    
    mode_label = MODE_DISPLAY_NAMES.get(body.new_mode, body.new_mode)

    reply = (
        f"Got it, {student_name}! Switching to {mode_label} mode. "
        f"We'll continue with {topic}, let's keep going!"
    )
    await save_message(body.session_id, "assistant", reply)
    return {"reply": reply}
