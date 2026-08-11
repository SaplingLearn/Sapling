from __future__ import annotations

import logging
import uuid
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from agents import TUTOR_LIMITS
from agents.chat_tutor import agent_for_mode
from agents.deps import SaplingDeps
from agents.usage import record_agent_usage
from db.connection import table
from services import events_service
from services.academics import offering_course_id, resolve_offering
from models import StartSessionBody, ChatBody, EndSessionBody, ActionBody, ModeSwitchBody, RenameSessionBody
from services.agent_events import SSE_CACHE_CONTROL, sapling_event_to_sse
from services.auth_guard import require_self, get_session_user_id
from services.chat_stream import merge_graph_updates, stream_agent_turn
from services.encryption import encrypt_if_present, encrypt_json, decrypt_if_present
from services.profiles import get_display_name
from services.graph_service import get_graph
from services.request_context import current_request_id

logger = logging.getLogger(__name__)

router = APIRouter()

# Lazy sessions: start-session does not write to DB until the user sends their first chat message.
# Maps session_id -> pending payload (cleared on first chat, end-session discard, or delete).
PENDING_SESSIONS: dict[str, dict] = {}

MODE_DISPLAY_NAMES = {
    "socratic": "Socratic (question-based)",
    "expository": "Expository (direct explanation)",
    "teachback": "Teach-back (you explain to me)",
}

# Per-request agent-model override map. Mirrors `routes.quiz._PREF_MODEL_NAMES`
# verbatim — the chat tutor and quiz routes share the same fast/smart toggle
# so a user choosing "smart" in either UI pulls the same Pro tier model.
# None falls through to model_for("chat_tutor") (default `gemini-2.5-pro`).
_PREF_MODEL_NAMES: dict[str, str] = {
    "fast": "gemini-2.5-flash-lite",
    "smart": "gemini-2.5-pro",
}

# Cap Pro's thinking budget for chat tutor turns. Dynamic thinking (-1) on
# multi-turn pedagogy can spend 10s+ in the thinking phase before any tokens
# stream; 2048 tokens is enough for the agent to plan a multi-step
# explanation without burning latency the student can feel.
_PRO_THINKING_BUDGET = 2048


def _resolve_model_pref(model_pref: str | None):
    """Build a GoogleModel override for the per-request fast/smart
    preference, or return None to use the agent's default.

    Lazy-imports `google_model` so that constructing a GoogleProvider
    (which reads `GEMINI_API_KEY` at call time) only happens when an
    override is actually requested — not at module import.
    """
    if not model_pref:
        return None
    from agents._providers import _model_mode, google_model
    if _model_mode() != "real":
        # #391 seam: the per-request fast/smart override must not bypass
        # SAPLING_MODEL_MODE by constructing a live GoogleModel — the browser
        # always sends a model_pref (ModelToggle defaults to "fast"), so
        # without this the E2E function-mode lane would silently dial Gemini
        # on every tutor turn. Fall through to the agent's default model,
        # which model_for("chat_tutor") already built for the active mode.
        return None
    name = _PREF_MODEL_NAMES.get(model_pref)
    if not name:
        return None
    return google_model(name)


def _build_pro_model_settings():
    """Return a GoogleModelSettings capping Pro's thinking budget.

    Apply this whenever the effective chat-tutor model is Pro (explicit
    "smart" pref OR no pref → agent default). Don't apply to Flash-Lite
    runs — Lite doesn't think, and passing thinking_config there would be
    wasted at best.

    Imported lazily for the same reason as `google_model` — keeps the
    GoogleProvider construction off the import path.
    """
    from google.genai.types import ThinkingConfig
    from pydantic_ai.models.google import GoogleModelSettings
    return GoogleModelSettings(
        google_thinking_config=ThinkingConfig(thinking_budget=_PRO_THINKING_BUDGET)
    )


def _get_course_id_for_topic(topic: str, user_id: str) -> str:
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
        enrolled = table("enrollments").select(
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
    node_rows = table("graph_nodes").select(
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
    subject_rows = table("graph_nodes").select(
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


def _get_session_offering_id(session_id: str) -> str:
    """Get the offering_id a session is scoped to, if any.

    Sessions key on the offering (0025); the abstract course id (the graph
    key) is derived from it via ``offering_course_id`` where needed.
    """
    rows = table("sessions").select("offering_id", filters={"id": f"eq.{session_id}"}, limit=1)
    if rows and rows[0].get("offering_id"):
        return rows[0]["offering_id"]
    return ""


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


def _load_message_history(session_id: str) -> list:
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
    """
    rows = table("messages").select(
        "role,content",
        filters={"session_id": f"eq.{session_id}"},
        order="created_at.asc",
    )

    history: list = []
    for r in rows or []:
        raw_role = (r.get("role") or "").lower()
        content = decrypt_if_present(r.get("content"))
        if not content:
            continue
        if raw_role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=str(content))]))
        elif raw_role in ("assistant", "model"):
            history.append(ModelResponse(parts=[TextPart(content=str(content))]))
        # else: drop (legacy 'system' rows have no equivalent in
        # Pydantic AI's role taxonomy and the system prompt is supplied
        # by the agent itself).
    return history


def save_message(session_id: str, role: str, content: str, graph_update: dict = None):
    table("messages").insert({
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "role": role,
        "content": encrypt_if_present(content),
        "graph_update_json": graph_update if graph_update else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def get_user_name(user_id: str) -> str:
    # Display name lives on user_profiles (0024); resolve + decrypt via helper.
    return get_display_name(user_id) or "Student"


def _elapsed_minutes(started_at_iso: str) -> int:
    """Whole minutes since ``started_at_iso``, robust to both timestamp shapes
    in the wild: tz-aware ISO (TIMESTAMPTZ reads via PostgREST, and every write
    after the #248 sweep) and legacy naive strings (pre-sweep ``utcnow()``
    writes), which are UTC by construction. The old inline
    ``utcnow() - fromisoformat(...)`` raised TypeError on the aware shape and
    silently reported 0. Returns 0 for anything unparseable."""
    try:
        started = datetime.fromisoformat(started_at_iso)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - started).total_seconds() / 60)
    except Exception:
        return 0


def _consume_pending(session_id: str, user_id: str) -> None:
    """If session was started lazily, persist session row + first assistant message before user/chat."""
    if session_id not in PENDING_SESSIONS:
        return
    pending = PENDING_SESSIONS.pop(session_id)
    if pending["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Session user mismatch")
    
    # Sessions key on the offering (0025). The pending payload carries the
    # offering id (resolved at start-session) alongside the abstract course id.
    session_data = {
        "id": session_id,
        "user_id": user_id,
        "mode": pending["mode"],
        "topic": pending["topic"],
    }
    if pending.get("offering_id"):
        session_data["offering_id"] = pending["offering_id"]

    table("sessions").insert(session_data)
    # #117: session.started once the lazy session row actually materializes.
    # The topic is free text -> content= (fingerprint only), never payload.
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
    save_message(session_id, "assistant", pending["assistant_reply"], pending["graph_update"])


def _ensure_session_ready(session_id: str, user_id: str) -> None:
    """For action/mode-switch: materialize lazy session if still pending."""
    _consume_pending(session_id, user_id)


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


async def _start_session_agent(
    body: StartSessionBody,
    session_id: str | None = None,
    *,
    model_pref: str | None = None,
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

    request_id = current_request_id() or str(uuid.uuid4())

    # Use abstract course_id from body, or resolve it from the topic. The graph
    # + shared context key on this abstract id; the session row keys on the
    # offering it resolves to (current term).
    course_id = body.course_id or _get_course_id_for_topic(body.topic, body.user_id)
    offering_id = resolve_offering(course_id, create=True) if course_id else ""

    user_message = (
        f"Student wants to learn about: {body.topic}\n\n"
        "Begin the session with a warm greeting and your first question or explanation."
    )

    agent, assembled, run_kwargs, deps = _prepare_chat_run(
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
        )
        reply = result.output  # str — chat_tutor agents return plain Markdown.
        if not reply.strip():
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
    PENDING_SESSIONS[session_id] = {
        "user_id": body.user_id,
        "mode": body.mode,
        "topic": body.topic,
        "course_id": course_id,        # abstract — graph + shared-context key
        "offering_id": offering_id,    # term-scoped — the session-row key
        "use_shared_context": body.use_shared_context,
        "assistant_reply": reply,
        "graph_update": graph_update,
    }

    return {
        "session_id": session_id,
        "reply": reply,
        "graph_update": graph_update,
        "mastery_changes": list(deps.mastery_changes),
        "graph_state": get_graph(body.user_id),
    }


@router.post("/start-session")
async def start_session(body: StartSessionBody, request: Request):
    require_self(body.user_id, request)
    result = await _agent_turn_or_http_error(
        _start_session_agent(body), what="start-session agent"
    )
    return {
        "session_id": result["session_id"],
        "initial_message": result["reply"],
        "graph_state": result["graph_state"],
    }


# Framing for the context blocks injected into every chat turn.
#
# These labels are load-bearing. They previously read as authoritative
# boundaries ("COURSE CATALOG INFO (official BU course data)"), and a model
# handed a labelled context wall with no instruction defaults to closed-book
# RAG behavior — it declined to teach Markov chains to a CS132 student on the
# grounds that they were "not in the course description". Each header now
# states the block's purpose AND what to do when it does not cover the
# question. See docs/superpowers/specs/2026-08-10-tutor-course-scope-design.md.
_CATALOG_HEADER = (
    "COURSE REFERENCE (administrative data about this course). Use ONLY if "
    "the student directly asks about the course itself — what it covers, "
    "prerequisites, credits, schedule. Never volunteer it. Never use it to "
    "decide whether a topic may be discussed."
)

_RAG_HEADER = (
    "COURSE MATERIAL (excerpts from this course's documents). Use as "
    "teaching substance when it is relevant to the question. If it does not "
    "cover the question, ignore it silently and answer from your own "
    "knowledge."
)


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
    )

    bu_code = _get_course_info(course_id).get("course_code") if course_id else None
    context_blocks: list[str] = []
    if bu_code:
        # Always inject the course catalog (prerequisites, description, credits)
        # so the agent can answer factual questions about the course without
        # relying on semantic similarity crossing a threshold. _CATALOG_HEADER
        # is what keeps "always present" from meaning "always relevant".
        catalog_text = _get_catalog_chunk(bu_code)
        if catalog_text:
            context_blocks.append(_CATALOG_HEADER + "\n\n" + catalog_text)

        # Semantic RAG: per-message retrieval for concept-level context
        from services.rag_service import retrieve_chunks, format_rag_context
        rag_chunks = retrieve_chunks(user_message, course_id=bu_code, k=5)
        rag_block = format_rag_context(rag_chunks, header=_RAG_HEADER)
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

    # Cap thinking budget on every Pro run (explicit "smart" OR no-pref
    # falling through to the agent default). Skip the cap for explicit
    # "fast" (Lite has no thinking).
    if model_pref != "fast":
        run_kwargs["model_settings"] = _build_pro_model_settings()

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
) -> dict:
    """Run chat_tutor_agent and return the wire response shape.

    Returns ``{"reply": str, "graph_update": dict, "mastery_changes": list}``.
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
    agent, user_message, run_kwargs, deps = _prepare_chat_run(
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
        )
        reply = result.output  # str — chat_tutor agents return plain Markdown.

        if not reply.strip():
            # #153 / ADR-0023 follow-up: gemini-2.5-pro occasionally follows an
            # end-of-turn tool call with a bare-newline final text. On this JSON
            # path that whitespace IS the run output; treat it as degenerate
            # model output so the caller's UnexpectedModelBehavior handling —
            # the route's 502 mapping, or the stream fallback's Rung-1 ladder —
            # applies instead of persisting an empty assistant row. (The
            # streamed path handles the same quirk inside `stream_agent_turn`.)
            # Usage was recorded above — tokens were spent.
            raise UnexpectedModelBehavior(
                "chat_tutor produced a whitespace-only reply"
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

    return {
        "reply": reply,
        "graph_update": merged_graph_update,
        # Real before/after deltas accumulated by update_mastery_tool.
        # Empty when no mastery moved this turn.
        "mastery_changes": deps.mastery_changes,
    }


async def _chat_turn_json(
    body: ChatBody, request: Request, *, model_pref: str | None = None
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
    """
    # Unify with the middleware-stamped request ID so agent traces and
    # any downstream error payloads share the same correlation key.
    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )

    # The session keys on the offering; the agent's graph tools key on the
    # abstract course derived from it.
    offering_id = _get_session_offering_id(body.session_id)
    course_id = offering_course_id(offering_id) if offering_id else ""
    # Load prior turns BEFORE writing the new user row, so the
    # message_history we hand the agent contains only the conversation
    # state up to (but not including) the current turn.
    message_history = _load_message_history(body.session_id)

    response = await _chat_via_agent(
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
    save_message(body.session_id, "user", body.message)
    graph_update = response.get("graph_update") or None
    save_message(body.session_id, "assistant", response["reply"], graph_update)

    # #117: one chat.message_sent per persisted turn. The message text is
    # fingerprinted via content= — it never enters a payload. request_id is
    # explicit: when this runs as the stream's fallback the emission happens
    # inside the SSE generator, outside the request contextvar scope.
    events_service.log_event(
        "chat.message_sent",
        category="usage",
        user_id=body.user_id,
        request_id=request_id,
        payload={"mode": body.mode, "session_id": body.session_id},
        content=body.message,
    )

    return response


@router.post("/chat")
async def chat(body: ChatBody, request: Request):
    require_self(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)
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
    (ADR 0011); retries are client-driven and idempotent via X-Request-ID.
    """
    require_self(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)

    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )

    offering_id = _get_session_offering_id(body.session_id)
    course_id = offering_course_id(offering_id) if offering_id else ""
    # Load prior turns BEFORE the new user row is written, so history is
    # conversation state up to (not including) this turn.
    message_history = _load_message_history(body.session_id)

    agent, assembled, run_kwargs, deps = _prepare_chat_run(
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

    def _persist(reply: str, graph_update: dict, mastery_changes: list) -> dict:
        # Mirrors chat()'s ordering: user row, then assistant row. Runs only
        # after the agent run completes, so a disconnect mid-generation
        # persists nothing. Encryption happens inside save_message.
        save_message(body.session_id, "user", body.message)
        save_message(body.session_id, "assistant", reply, graph_update or None)
        # #117: same event as the JSON route, from the on_complete hook so a
        # disconnected mid-generation turn emits nothing. request_id is
        # explicit — this runs inside the SSE generator, outside the request
        # contextvar scope.
        events_service.log_event(
            "chat.message_sent",
            category="usage",
            user_id=body.user_id,
            request_id=request_id,
            payload={"mode": body.mode, "session_id": body.session_id},
            content=body.message,
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
        record_agent_usage(
            run_result, feature="chat_tutor", task="chat_tutor", user_id=body.user_id,
        )

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
    require_self(body.user_id, request)
    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )
    session_id = str(uuid.uuid4())

    course_id = body.course_id or _get_course_id_for_topic(body.topic, body.user_id)
    offering_id = resolve_offering(course_id, create=True) if course_id else ""

    user_message = (
        f"Student wants to learn about: {body.topic}\n\n"
        "Begin the session with a warm greeting and your first question or explanation."
    )

    agent, assembled, run_kwargs, deps = _prepare_chat_run(
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
        PENDING_SESSIONS[session_id] = {
            "user_id": body.user_id,
            "mode": body.mode,
            "topic": body.topic,
            "course_id": course_id,
            "offering_id": offering_id,
            "use_shared_context": body.use_shared_context,
            "assistant_reply": reply,
            "graph_update": graph_update,
        }
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
        return await _start_session_agent(body, session_id, model_pref="fast")

    def _usage(run_result) -> None:
        # #118: same hook as /chat/stream — the opener runs the same
        # chat_tutor agent, so it rolls up under the same feature/task.
        record_agent_usage(
            run_result, feature="chat_tutor", task="chat_tutor", user_id=body.user_id,
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
        ):
            yield sapling_event_to_sse(ev)

    return EventSourceResponse(
        event_stream(),
        headers={"X-Request-ID": request_id, "Cache-Control": SSE_CACHE_CONTROL},
    )


@router.post("/end-session")
def end_session(body: EndSessionBody, request: Request):
    if body.user_id:
        require_self(body.user_id, request)
    else:
        body.user_id = get_session_user_id(request)
    if body.session_id in PENDING_SESSIONS:
        pending = PENDING_SESSIONS[body.session_id]
        if body.user_id and pending["user_id"] != body.user_id:
            raise HTTPException(status_code=403, detail="Session user mismatch")
        PENDING_SESSIONS.pop(body.session_id, None)
        empty = {
            "concepts_covered": [],
            "mastery_changes": [],
            "new_connections": [],
            "time_spent_minutes": 0,
            "recommended_next": [],
        }
        return {"summary": empty}

    session_rows = table("sessions").select(
        "user_id,started_at",
        filters={"id": f"eq.{body.session_id}"},
    )
    if not session_rows:
        raise HTTPException(status_code=404, detail="Session not found")
    session = session_rows[0]

    table("sessions").update(
        {"ended_at": datetime.now(timezone.utc).isoformat()},
        filters={"id": f"eq.{body.session_id}"},
    )

    msgs = table("messages").select(
        "graph_update_json",
        filters={"session_id": f"eq.{body.session_id}"},
    )

    elapsed_minutes = _elapsed_minutes(session["started_at"])

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

    summary = {
        "concepts_covered": list(concepts_covered),
        "mastery_changes": [],
        "new_connections": [],
        "time_spent_minutes": elapsed_minutes,
        "recommended_next": [],
    }

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
    except Exception:
        pass

    return {"summary": summary, "achievements_earned": newly_earned}


@router.get("/sessions/{user_id}")
def list_sessions(user_id: str, request: Request, limit: int = 10):
    require_self(user_id, request)
    sessions = table("sessions").select(
        "id,user_id,topic,mode,offering_id,started_at,ended_at",
        filters={"user_id": f"eq.{user_id}"},
        order="started_at.desc",
        limit=limit,
    )
    # Sessions key on the offering; the frontend speaks abstract course ids.
    # Map each offering → its abstract course once.
    offering_to_course: dict[str, str | None] = {}
    result = []
    for s in sessions:
        off_id = s.get("offering_id")
        if off_id and off_id not in offering_to_course:
            offering_to_course[off_id] = offering_course_id(off_id)
        msgs = table("messages").select("id", filters={"session_id": f"eq.{s['id']}"})
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

    if session_id in PENDING_SESSIONS:
        pending = PENDING_SESSIONS[session_id]
        if pending["user_id"] != body.user_id:
            raise HTTPException(status_code=403, detail="Session user mismatch")
        pending["topic"] = topic
        return {"updated": True, "session": {"id": session_id, "topic": topic}}

    owner_rows = table("sessions").select(
        "user_id", filters={"id": f"eq.{session_id}"}, limit=1
    )
    if not owner_rows:
        raise HTTPException(status_code=404, detail="Session not found")
    if owner_rows[0].get("user_id") != body.user_id:
        raise HTTPException(status_code=403, detail="Session user mismatch")

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
    if session_id in PENDING_SESSIONS:
        pending = PENDING_SESSIONS[session_id]
        if pending["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Session user mismatch")
        PENDING_SESSIONS.pop(session_id, None)
        return {"deleted": True}
    # Verify the session belongs to the authenticated user before deleting
    owner_rows = table("sessions").select(
        "user_id", filters={"id": f"eq.{session_id}"}, limit=1
    )
    if owner_rows and owner_rows[0].get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Session user mismatch")
    table("messages").delete({"session_id": f"eq.{session_id}"})
    table("sessions").delete({"id": f"eq.{session_id}"})
    return {"deleted": True}


@router.get("/sessions/{session_id}/resume")
def resume_session(session_id: str, request: Request):
    user_id = get_session_user_id(request)
    if session_id in PENDING_SESSIONS:
        p = PENDING_SESSIONS[session_id]
        if p["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Session user mismatch")
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

    session_rows = table("sessions").select(
        "id,user_id,topic,mode,started_at,ended_at,offering_id",
        filters={"id": f"eq.{session_id}"},
    )
    if not session_rows:
        raise HTTPException(status_code=404, detail="Session not found")
    if session_rows[0].get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Session user mismatch")

    # Expose the abstract course id (derived from the offering) for the
    # frontend, alongside the stored offering id.
    session = dict(session_rows[0])
    session["course_id"] = offering_course_id(session.get("offering_id"))

    msgs = table("messages").select(
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
    offering_id = _get_session_offering_id(body.session_id)
    course_id = offering_course_id(offering_id) if offering_id else ""
    message_history = _load_message_history(body.session_id)

    agent, assembled, run_kwargs, deps = _prepare_chat_run(
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
    )
    reply = result.output
    if not reply.strip():
        # #153: degenerate whitespace-only output — surface through the
        # guardrail mapping rather than persisting an empty assistant row.
        raise UnexpectedModelBehavior(
            "chat_tutor produced a whitespace-only action reply"
        )

    graph_update = merge_graph_updates(deps.graph_updates)
    save_message(body.session_id, "assistant", reply, graph_update or None)
    return {"reply": reply, "graph_update": graph_update}


@router.post("/action")
async def action(body: ActionBody, request: Request):
    require_self(body.user_id, request)
    _ensure_session_ready(body.session_id, body.user_id)
    return await _agent_turn_or_http_error(
        _action_turn(body, request), what="action agent"
    )


@router.post("/mode-switch")
def mode_switch(body: ModeSwitchBody, request: Request):
    require_self(body.user_id, request)
    _ensure_session_ready(body.session_id, body.user_id)
    student_name = get_user_name(body.user_id).split()[0]
    session_rows = table("sessions").select(
        "topic", filters={"id": f"eq.{body.session_id}"}, limit=1
    )
    topic = session_rows[0]["topic"] if session_rows else "this topic"
    
    mode_label = MODE_DISPLAY_NAMES.get(body.new_mode, body.new_mode)

    reply = (
        f"Got it, {student_name}! Switching to {mode_label} mode. "
        f"We'll continue with {topic}, let's keep going!"
    )
    save_message(body.session_id, "assistant", reply)
    return {"reply": reply}
