from __future__ import annotations

import logging
import uuid
import json
import os
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request

from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from agents.chat_tutor import agent_for_mode
from agents.deps import SaplingDeps
from db.connection import table
from services.academics import offering_course_id, resolve_offering
from models import StartSessionBody, ChatBody, EndSessionBody, ActionBody, ModeSwitchBody, RenameSessionBody
from services.auth_guard import require_self, get_session_user_id
from services.encryption import encrypt_if_present, encrypt_json, decrypt_if_present, decrypt_json
from services.profiles import get_display_name
from services.gemini_service import (
    MODEL_LITE,
    MODEL_SMART,
    call_gemini_multiturn,
    extract_graph_update,
)
from services.graph_service import get_graph, apply_graph_update
from services.request_context import current_request_id

logger = logging.getLogger(__name__)

router = APIRouter()

# Lazy sessions: start-session does not write to DB until the user sends their first chat message.
# Maps session_id -> pending payload (cleared on first chat, end-session discard, or delete).
PENDING_SESSIONS: dict[str, dict] = {}

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

MODE_DISPLAY_NAMES = {
    "socratic": "Socratic (question-based)",
    "expository": "Expository (direct explanation)",
    "teachback": "Teach-back (you explain to me)",
}

# User-facing speed/quality knob for the tutor chat.
# "fast" = flash-lite (opt-in, lightweight + cheapest, no thinking),
# "smart" = pro (default, capped thinking budget for snappy reasoning).
# Anything unrecognized falls back to Pro (matches the agent default at
# `agents/_providers.py::_DEFAULTS["chat_tutor"]`) so the legacy fallback
# stays symmetric with the agent path when `body.model_pref` is None.
_MODEL_PREF_TO_MODEL = {
    "fast": MODEL_LITE,
    "smart": MODEL_SMART,
}


def _resolve_legacy_model(model_pref: str | None) -> str:
    return _MODEL_PREF_TO_MODEL.get(model_pref or "", MODEL_SMART)


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
    name = _PREF_MODEL_NAMES.get(model_pref)
    if not name:
        return None
    from agents._providers import google_model
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


def _load_prompt(name: str) -> str:
    with open(os.path.join(PROMPTS_DIR, name)) as f:
        return f.read()


PREAMBLE_TEMPLATE = _load_prompt("preamble.txt")
SHARED_CONTEXT_TEMPLATE = _load_prompt("shared_context.txt")
MODE_PROMPTS = {
    "socratic": _load_prompt("socratic.txt"),
    "expository": _load_prompt("expository.txt"),
    "teachback": _load_prompt("teachback.txt"),
}


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


def _get_course_documents(user_id: str, offering_id: str) -> list:
    """Fetch uploaded document summaries + concept notes for a user's offering.

    Documents key on the offering (0025), so the tutor grounds itself in the
    materials uploaded for this term's offering.
    """
    if not offering_id:
        return []
    try:
        docs = table("documents").select(
            "file_name,category,summary,concept_notes",
            filters={
                "user_id": f"eq.{user_id}",
                "offering_id": f"eq.{offering_id}",
                "deleted_at": "is.null",
            },
        ) or []
        for d in docs:
            d["summary"] = decrypt_if_present(d.get("summary"))
            notes_raw = d.get("concept_notes")
            if isinstance(notes_raw, str):
                d["concept_notes"] = decrypt_json(notes_raw)
        return docs
    except Exception:
        return []


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


def build_system_prompt(
    mode: str,
    student_name: str,
    graph_json: str,
    last_summary: str = "",
    course_id: str = "",
    use_shared_context: bool = True,
    documents: list | None = None,
) -> str:
    from services.course_context_service import get_course_context

    preamble = PREAMBLE_TEMPLATE.replace("{student_name}", student_name)
    preamble = preamble.replace("{graph_json}", graph_json)
    preamble = preamble.replace("{last_session_summary}", last_summary or "None")

    parts = [preamble]

    # Ground the tutor in the student's actual uploaded course materials
    if documents:
        doc_blocks = []
        for doc in documents:
            lines = [f"[{(doc.get('category') or 'document').upper()}] {doc.get('file_name', '')}"]
            if doc.get("summary"):
                lines.append(f"Summary: {doc['summary']}")
            notes = doc.get("concept_notes")
            if notes and isinstance(notes, list):
                concept_lines = []
                for n in notes:
                    if not isinstance(n, dict):
                        continue
                    name = n.get("name")
                    desc = n.get("description")
                    if not name:
                        continue
                    concept_lines.append(f"- {name}: {desc}" if desc else f"- {name}")
                if concept_lines:
                    lines.append("Key concepts:\n" + "\n".join(concept_lines))
            doc_blocks.append("\n".join(lines))
        if doc_blocks:
            parts.append(
                "COURSE MATERIALS (ground your explanations and examples in these):\n\n"
                + "\n\n---\n\n".join(doc_blocks)
            )

    if use_shared_context and course_id:
        # `course_id` is the abstract course id (resolved from the session's
        # offering by the caller). course_context keys on the abstract course,
        # so shared class-aggregate context resolves here.
        ctx = get_course_context(course_id)
        if ctx:
            course_info = _get_course_info(course_id)
            course_label = f"{course_info['course_code']} - {course_info['course_name']}" if course_info['course_code'] else course_info['course_name']
            shared_block = (
                SHARED_CONTEXT_TEMPLATE
                .replace("{course_name}", course_label)
                .replace("{shared_context_json}", json.dumps(ctx, indent=2))
            )
            parts.append(shared_block)

    parts.append(MODE_PROMPTS.get(mode, MODE_PROMPTS["socratic"]))
    return "\n\n".join(parts)


def get_conversation_history(session_id: str) -> list:
    rows = table("messages").select(
        "role,content",
        filters={"session_id": f"eq.{session_id}"},
        order="created_at.asc",
    )
    return [{"role": r["role"], "content": decrypt_if_present(r["content"])} for r in rows]


def _load_message_history(session_id: str) -> list:
    """Load the prior conversation as Pydantic AI `ModelMessage` objects.

    Reads the same encrypted `messages` rows the legacy path uses,
    decrypts at the boundary, and converts each turn into a
    `ModelRequest`/`ModelResponse` pair so chat_tutor_agent.run() can
    consume them via `message_history=` for multi-turn coherence.

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
        "created_at": datetime.utcnow().isoformat(),
    })


def get_user_name(user_id: str) -> str:
    # Display name lives on user_profiles (0024); resolve + decrypt via helper.
    return get_display_name(user_id) or "Student"


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
    save_message(session_id, "assistant", pending["assistant_reply"], pending["graph_update"])


def _ensure_session_ready(session_id: str, user_id: str) -> None:
    """For action/mode-switch: materialize lazy session if still pending."""
    _consume_pending(session_id, user_id)


@router.post("/start-session")
def start_session(body: StartSessionBody, request: Request):
    # TODO(refactor-3 follow-up): migrate `start_session` to chat_tutor_agent
    # using the same try-agent-then-legacy pattern as `chat`. Current PR scopes
    # the agent-path migration to the main `chat` route only.
    require_self(body.user_id, request)
    session_id = str(uuid.uuid4())

    student_name = get_user_name(body.user_id)
    graph_data = get_graph(body.user_id)
    
    # Use abstract course_id from body, or resolve it from the topic. The graph
    # + shared context key on this abstract id; documents + the session row key
    # on the offering it resolves to (current term).
    course_id = body.course_id or _get_course_id_for_topic(body.topic, body.user_id)
    offering_id = resolve_offering(course_id, create=True) if course_id else ""
    documents = _get_course_documents(body.user_id, offering_id)

    system_prompt = build_system_prompt(
        body.mode, student_name, json.dumps(graph_data, indent=2),
        course_id=course_id, use_shared_context=body.use_shared_context,
        documents=documents,
    )
    user_message = (
        f"Student wants to learn about: {body.topic}\n\n"
        "Begin the session with a warm greeting and your first question or explanation."
    )

    try:
        raw = call_gemini_multiturn(
            system_prompt, [], user_message, model=_resolve_legacy_model(body.model_pref)
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

    reply, graph_update = extract_graph_update(raw)
    apply_graph_update(body.user_id, graph_update, course_id=course_id)

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
        "initial_message": reply,
        "graph_state": get_graph(body.user_id),
    }


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
    """Run chat_tutor_agent and return the legacy response shape.

    Returns ``{"reply": str, "graph_update": dict, "mastery_changes": list}``.
    `graph_update` and `mastery_changes` come back empty here because
    `apply_graph_update_tool` (registered on chat_tutor) already
    persisted any graph changes during the agent run. The frontend's
    Learn-page reducer accepts empty values gracefully.

    `use_shared_context=False` flips the model into "no class-aggregate"
    mode by appending a constraint instruction to the user message —
    the chat tutor's class-aggregate tools (read_user_progress, etc.)
    aggregate per-user data, but a future shared-context tool would
    need this guard rail. Keeping the constraint in-band rather than
    branching the agent surface keeps the agent definition stable.
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

    if not use_shared_context:
        user_message = (
            user_message
            + "\n\n[Constraint: do not call any class-aggregate tool — "
            "student opted out of shared context.]"
        )

    model_override = _resolve_model_pref(model_pref)
    run_kwargs: dict = {"deps": deps, "message_history": message_history}
    if model_override is not None:
        run_kwargs["model"] = model_override

    # Cap thinking budget on every Pro run (explicit "smart" OR no-pref
    # falling through to the agent default). Skip the cap for explicit
    # "fast" (Lite has no thinking).
    if model_pref != "fast":
        run_kwargs["model_settings"] = _build_pro_model_settings()

    result = await agent.run(user_message, **run_kwargs)
    reply = result.output  # str — chat_tutor agents return plain Markdown.

    return {
        "reply": reply,
        "graph_update": {},
        "mastery_changes": [],
    }


async def _legacy_chat(body: ChatBody, request: Request) -> dict:
    """Pre-agent chat pipeline. Kept as a fallback per ADR 0001 — DO NOT
    delete in this refactor. A separate PR removes services/gemini_service.py
    after the agent path proves stable in production.

    This path persists the user message itself (matches the historical
    save order: user row first, assistant row after the LLM call).
    The agent path persists messages out-of-band in `chat()` — keeping
    that boundary inside the legacy helper avoids accidentally
    double-writing the user row when the agent succeeds.
    """
    save_message(body.session_id, "user", body.message)

    student_name = get_user_name(body.user_id)
    graph_data = get_graph(body.user_id)
    # Exclude the just-saved user message so history is prior turns only
    history = get_conversation_history(body.session_id)[:-1]

    # The session keys on the offering; documents read by offering, while the
    # graph + shared context key on the abstract course derived from it.
    offering_id = _get_session_offering_id(body.session_id)
    course_id = offering_course_id(offering_id) if offering_id else ""
    documents = _get_course_documents(body.user_id, offering_id)

    system_prompt = build_system_prompt(
        body.mode, student_name, json.dumps(graph_data, indent=2),
        course_id=course_id, use_shared_context=body.use_shared_context,
        documents=documents,
    )

    try:
        raw = call_gemini_multiturn(
            system_prompt, history, body.message, model=_resolve_legacy_model(body.model_pref)
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

    reply, graph_update = extract_graph_update(raw)
    save_message(body.session_id, "assistant", reply, graph_update)
    mastery_changes = apply_graph_update(body.user_id, graph_update, course_id=course_id)

    return {"reply": reply, "graph_update": graph_update, "mastery_changes": mastery_changes}


@router.post("/chat")
async def chat(body: ChatBody, request: Request):
    require_self(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)

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

    try:
        response = await _chat_via_agent(
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
    except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
        logger.warning(
            "Chat agent guardrails tripped; falling back to legacy",
            exc_info=e,
        )
        return await _legacy_chat(body, request)
    except HTTPException:
        # Legacy path raises HTTPException for known states (502); never
        # treat those as a reason to fall back. Re-raise.
        raise
    except Exception:
        logger.exception(
            "Unexpected chat-agent failure; falling back to legacy"
        )
        return await _legacy_chat(body, request)

    # Agent path persists messages here — the legacy helper handles its
    # own writes so a fallback doesn't double-insert. Encryption happens
    # inside save_message (`encrypt_if_present`).
    save_message(body.session_id, "user", body.message)
    save_message(body.session_id, "assistant", response["reply"])

    return response


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
        {"ended_at": datetime.utcnow().isoformat()},
        filters={"id": f"eq.{body.session_id}"},
    )

    msgs = table("messages").select(
        "graph_update_json",
        filters={"session_id": f"eq.{body.session_id}"},
    )

    try:
        elapsed_minutes = int(
            (datetime.utcnow() - datetime.fromisoformat(session["started_at"])).total_seconds() / 60
        )
    except Exception:
        elapsed_minutes = 0

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
        now = datetime.utcnow().isoformat()
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


@router.post("/action")
def action(body: ActionBody, request: Request):
    # TODO(refactor-3 follow-up): migrate `action` to chat_tutor_agent
    # using the same try-agent-then-legacy pattern as `chat`. Current PR scopes
    # the agent-path migration to the main `chat` route only.
    require_self(body.user_id, request)
    _ensure_session_ready(body.session_id, body.user_id)
    action_prompts = {
        "hint": "The student asked for a hint. Give a small scaffold or clue without giving away the answer.",
        "confused": "The student said they are confused. Identify the likely point of confusion and re-explain with a different analogy.",
        "skip": "The student wants to skip this concept. Acknowledge and transition to the next recommended concept.",
    }

    student_name = get_user_name(body.user_id)
    graph_data = get_graph(body.user_id)
    history = get_conversation_history(body.session_id)

    # Session keys on the offering; docs read by offering, graph + shared
    # context key on the abstract course derived from it.
    offering_id = _get_session_offering_id(body.session_id)
    course_id = offering_course_id(offering_id) if offering_id else ""
    documents = _get_course_documents(body.user_id, offering_id)

    system_prompt = build_system_prompt(
        body.mode, student_name, json.dumps(graph_data, indent=2),
        course_id=course_id, use_shared_context=body.use_shared_context,
        documents=documents,
    )
    action_message = f"[ACTION: {action_prompts.get(body.action_type, '')}]"

    try:
        raw = call_gemini_multiturn(
            system_prompt, history, action_message, model=_resolve_legacy_model(body.model_pref)
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

    reply, graph_update = extract_graph_update(raw)
    save_message(body.session_id, "assistant", reply, graph_update)
    apply_graph_update(body.user_id, graph_update, course_id=course_id)
    return {"reply": reply, "graph_update": graph_update}


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
