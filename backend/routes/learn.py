import uuid
import json
import os
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from db.connection import table
from models import StartSessionBody, ChatBody, EndSessionBody, ActionBody, ModeSwitchBody
from services.gemini_service import call_gemini, call_gemini_multiturn, extract_graph_update
from services.graph_service import get_graph, apply_graph_update
from services.activity_service import log_room_activity

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


def _resolve_course(topic: str, user_id: str) -> str:
    """Return the subject/course the topic belongs to, or '' if unknown."""
    if not topic:
        return ""
    subject_match = table("graph_nodes").select(
        "subject", filters={"user_id": f"eq.{user_id}", "subject": f"eq.{topic}"}, limit=1
    )
    if subject_match:
        return topic
    concept_match = table("graph_nodes").select(
        "subject", filters={"user_id": f"eq.{user_id}", "concept_name": f"eq.{topic}"}, limit=1
    )
    if concept_match:
        return concept_match[0].get("subject") or ""
    course_match = table("courses").select(
        "course_name", filters={"user_id": f"eq.{user_id}", "course_name": f"eq.{topic}"}, limit=1
    )
    if course_match:
        return topic
    return ""


def _get_session_topic(session_id: str) -> str:
    rows = table("sessions").select("topic", filters={"id": f"eq.{session_id}"}, limit=1)
    return rows[0]["topic"] if rows else ""


def _get_course_documents(user_id: str, course_name: str) -> list:
    """Fetch uploaded document summaries and key takeaways for a user's course."""
    if not course_name:
        return []
    try:
        course_rows = table("courses").select(
            "id", filters={"user_id": f"eq.{user_id}", "course_name": f"eq.{course_name}"}, limit=1
        )
        if not course_rows:
            return []
        course_id = course_rows[0]["id"]
        docs = table("documents").select(
            "file_name,category,summary,key_takeaways",
            filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        )
        return docs or []
    except Exception:
        return []


def build_system_prompt(
    mode: str,
    student_name: str,
    graph_json: str,
    last_summary: str = "",
    course_name: str = "",
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
            if doc.get("key_takeaways") and isinstance(doc["key_takeaways"], list):
                lines.append("Key points:\n" + "\n".join(f"- {t}" for t in doc["key_takeaways"]))
            doc_blocks.append("\n".join(lines))
        if doc_blocks:
            parts.append(
                "COURSE MATERIALS (ground your explanations and examples in these):\n\n"
                + "\n\n---\n\n".join(doc_blocks)
            )

    if use_shared_context and course_name:
        ctx = get_course_context(course_name)
        if ctx:
            shared_block = (
                SHARED_CONTEXT_TEMPLATE
                .replace("{course_name}", course_name)
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
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def save_message(session_id: str, role: str, content: str, graph_update: dict = None):
    table("messages").insert({
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "role": role,
        "content": content,
        "graph_update_json": graph_update if graph_update else None,
        "created_at": datetime.utcnow().isoformat(),
    })


def get_user_name(user_id: str) -> str:
    rows = table("users").select("name", filters={"id": f"eq.{user_id}"})
    return rows[0]["name"] if rows else "Student"


def _make_session_name(topic: str, mode: str) -> str:
    """Generate a descriptive sentence summarising the session topic. Falls back to topic on error."""
    mode_note = {
        "socratic": "question-based exploration",
        "expository": "direct explanation",
        "teachback": "student explains the material back",
    }.get(mode, mode)
    try:
        prompt = (
            f"Write a 4–6 word phrase (no verb needed) describing a tutoring session.\n"
            f"Topic: {topic}\n"
            f"Style: {mode_note}\n\n"
            f"Reply with ONLY the phrase. No quotes. No period."
        )
        name = call_gemini(prompt, max_output_tokens=30).strip().strip('"\'').strip('.').strip()
        return name[:80] if name else topic
    except Exception:
        return topic


def _enforce_session_limit(user_id: str, course_name: str, limit: int = 10) -> None:
    """Delete the oldest session(s) for this user+course so at most `limit - 1` remain before the new insert."""
    filters = {"user_id": f"eq.{user_id}"}
    if course_name:
        filters["course_name"] = f"eq.{course_name}"
    sessions = table("sessions").select("id", filters=filters, order="started_at.asc")
    excess = len(sessions) - limit + 1
    for i in range(max(0, excess)):
        old_id = sessions[i]["id"]
        table("messages").delete({"session_id": f"eq.{old_id}"})
        table("sessions").delete({"id": f"eq.{old_id}"})


def _consume_pending(session_id: str, user_id: str) -> None:
    """If session was started lazily, persist session row + first assistant message before user/chat."""
    if session_id not in PENDING_SESSIONS:
        return
    pending = PENDING_SESSIONS.pop(session_id)
    if pending["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Session user mismatch")
    course_name = pending.get("course_name", "")
    # Enforce session limit — skip silently if name/course_name columns not migrated yet
    try:
        _enforce_session_limit(user_id, course_name)
    except Exception:
        pass
    # Core insert — always works on the base schema
    table("sessions").insert({
        "id": session_id,
        "user_id": user_id,
        "mode": pending["mode"],
        "topic": pending["topic"],
    })
    # Set generated name + course — skip silently if columns don't exist yet (run migration)
    try:
        name = _make_session_name(pending["topic"], pending["mode"])
        table("sessions").update(
            {"name": name, "course_name": course_name or None},
            filters={"id": f"eq.{session_id}"},
        )
    except Exception:
        pass
    save_message(session_id, "assistant", pending["assistant_reply"], pending["graph_update"])


def _ensure_session_ready(session_id: str, user_id: str) -> None:
    """For action/mode-switch: materialize lazy session if still pending."""
    _consume_pending(session_id, user_id)


@router.post("/start-session")
def start_session(body: StartSessionBody):
    session_id = str(uuid.uuid4())

    student_name = get_user_name(body.user_id)
    graph_data = get_graph(body.user_id)
    course_name = _resolve_course(body.topic, body.user_id)
    documents = _get_course_documents(body.user_id, course_name)
    system_prompt = build_system_prompt(
        body.mode, student_name, json.dumps(graph_data, indent=2),
        course_name=course_name, use_shared_context=body.use_shared_context,
        documents=documents,
    )
    user_message = (
        f"Student wants to learn about: {body.topic}\n\n"
        "Begin the session with a warm greeting and your first question or explanation."
    )

    try:
        raw = call_gemini_multiturn(system_prompt, [], user_message)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

    reply, graph_update = extract_graph_update(raw)
    apply_graph_update(body.user_id, graph_update)
    PENDING_SESSIONS[session_id] = {
        "user_id": body.user_id,
        "mode": body.mode,
        "topic": body.topic,
        "course_name": course_name,
        "use_shared_context": body.use_shared_context,
        "assistant_reply": reply,
        "graph_update": graph_update,
    }

    return {
        "session_id": session_id,
        "initial_message": reply,
        "graph_state": get_graph(body.user_id),
    }


@router.post("/chat")
def chat(body: ChatBody):
    _consume_pending(body.session_id, body.user_id)
    save_message(body.session_id, "user", body.message)

    student_name = get_user_name(body.user_id)
    graph_data = get_graph(body.user_id)
    # Exclude the just-saved user message so history is prior turns only
    history = get_conversation_history(body.session_id)[:-1]
    topic = _get_session_topic(body.session_id)
    course_name = _resolve_course(topic, body.user_id)
    documents = _get_course_documents(body.user_id, course_name)
    system_prompt = build_system_prompt(
        body.mode, student_name, json.dumps(graph_data, indent=2),
        course_name=course_name, use_shared_context=body.use_shared_context,
        documents=documents,
    )

    try:
        raw = call_gemini_multiturn(system_prompt, history, body.message)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

    reply, graph_update = extract_graph_update(raw)
    save_message(body.session_id, "assistant", reply, graph_update)
    mastery_changes = apply_graph_update(body.user_id, graph_update)

    return {"reply": reply, "graph_update": graph_update, "mastery_changes": mastery_changes}


@router.post("/end-session")
def end_session(body: EndSessionBody):
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
        {"summary_json": summary},
        filters={"id": f"eq.{body.session_id}"},
    )

    try:
        n = len(concepts_covered)
        detail = f"Covered {n} concept{'s' if n != 1 else ''}"
        log_room_activity(session["user_id"], "session_completed", detail=detail)
    except Exception:
        pass

    return {"summary": summary}


@router.get("/sessions/{user_id}")
def list_sessions(user_id: str, limit: int = 10, course_name: str | None = Query(None)):
    filters: dict = {"user_id": f"eq.{user_id}"}
    if course_name:
        filters["course_name"] = f"eq.{course_name}"
    sessions = table("sessions").select(
        "*",
        filters=filters,
        order="started_at.desc",
        limit=limit,
    )
    result = []
    for s in sessions:
        msgs = table("messages").select("id", filters={"session_id": f"eq.{s['id']}"})
        result.append({
            "id": s["id"],
            "topic": s["topic"],
            "name": s.get("name"),
            "course_name": s.get("course_name"),
            "mode": s["mode"],
            "started_at": s["started_at"],
            "ended_at": s.get("ended_at"),
            "message_count": len(msgs),
            "is_active": s.get("ended_at") is None,
        })
    return {"sessions": result}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, user_id: str | None = Query(None)):
    if session_id in PENDING_SESSIONS:
        pending = PENDING_SESSIONS[session_id]
        if user_id and pending["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Session user mismatch")
        PENDING_SESSIONS.pop(session_id, None)
        return {"deleted": True}
    # Delete child messages before the session to satisfy the FK constraint
    try:
        table("messages").delete({"session_id": f"eq.{session_id}"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete session messages: {e}")
    try:
        table("sessions").delete({"id": f"eq.{session_id}"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete session: {e}")
    return {"deleted": True}


@router.get("/sessions/{session_id}/resume")
def resume_session(session_id: str):
    if session_id in PENDING_SESSIONS:
        p = PENDING_SESSIONS[session_id]
        now = datetime.utcnow().isoformat()
        return {
            "session": {
                "id": session_id,
                "user_id": p["user_id"],
                "topic": p["topic"],
                "mode": p["mode"],
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
        "id,user_id,topic,mode,started_at,ended_at",
        filters={"id": f"eq.{session_id}"},
    )
    if not session_rows:
        raise HTTPException(status_code=404, detail="Session not found")

    msgs = table("messages").select(
        "id,role,content,created_at",
        filters={"session_id": f"eq.{session_id}"},
        order="created_at.asc",
    )
    return {
        "session": session_rows[0],
        "messages": msgs,
    }


@router.post("/action")
def action(body: ActionBody):
    _ensure_session_ready(body.session_id, body.user_id)
    action_prompts = {
        "hint": "The student asked for a hint. Give a small scaffold or clue without giving away the answer.",
        "confused": "The student said they are confused. Identify the likely point of confusion and re-explain with a different analogy.",
        "skip": "The student wants to skip this concept. Acknowledge and transition to the next recommended concept.",
    }

    student_name = get_user_name(body.user_id)
    graph_data = get_graph(body.user_id)
    history = get_conversation_history(body.session_id)
    topic = _get_session_topic(body.session_id)
    course_name = _resolve_course(topic, body.user_id)
    documents = _get_course_documents(body.user_id, course_name)
    system_prompt = build_system_prompt(
        body.mode, student_name, json.dumps(graph_data, indent=2),
        course_name=course_name, use_shared_context=body.use_shared_context,
        documents=documents,
    )
    action_message = f"[ACTION: {action_prompts.get(body.action_type, '')}]"

    try:
        raw = call_gemini_multiturn(system_prompt, history, action_message)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

    reply, graph_update = extract_graph_update(raw)
    save_message(body.session_id, "assistant", reply, graph_update)
    apply_graph_update(body.user_id, graph_update)
    return {"reply": reply, "graph_update": graph_update}


@router.post("/mode-switch")
def mode_switch(body: ModeSwitchBody):
    _ensure_session_ready(body.session_id, body.user_id)
    student_name = get_user_name(body.user_id).split()[0]
    topic = _get_session_topic(body.session_id)
    mode_label = MODE_DISPLAY_NAMES.get(body.new_mode, body.new_mode)

    reply = (
        f"Got it, {student_name}! Switching to {mode_label} mode. "
        f"We'll continue with {topic}, let's keep going!"
    )
    save_message(body.session_id, "assistant", reply)

    try:
        table("sessions").update(
            {"mode": body.new_mode},
            filters={"id": f"eq.{body.session_id}"},
        )
    except Exception:
        pass

    return {"reply": reply, "mode": body.new_mode}
