from __future__ import annotations

import uuid
import json
import os
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request

from db.connection import table
from models import StartSessionBody, ChatBody, EndSessionBody, ActionBody, ModeSwitchBody
from services.auth_guard import require_self, get_session_user_id
from services.encryption import encrypt_if_present, encrypt_json, decrypt_if_present, decrypt_json
from services.gemini_service import call_gemini_multiturn, extract_graph_update
from services.graph_service import get_graph, apply_graph_update

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
    
    # First, check if topic matches a course code or name in user's enrolled courses
    try:
        enrolled = table("user_courses").select(
            "course_id,courses!inner(course_code,course_name)",
            filters={"user_id": f"eq.{user_id}"},
        )
        for row in enrolled:
            course = row.get("courses", {}) if isinstance(row.get("courses"), dict) else {}
            course_code = course.get("course_code", "")
            course_name = course.get("course_name", "")
            
            # Match on course_code (exact or case-insensitive)
            if topic_trim.upper() == course_code.upper():
                return row["course_id"]
            # Match on course_name
            if topic_trim.lower() == course_name.lower():
                return row["course_id"]
            # Same label as graph subject roots (graph_service)
            label = f"{course_code} - {course_name}" if course_code else course_name
            if label and topic_trim == label:
                return row["course_id"]
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


def _get_session_course_id(session_id: str) -> str:
    """Get the course_id from a session if it exists."""
    rows = table("sessions").select("course_id", filters={"id": f"eq.{session_id}"}, limit=1)
    if rows and rows[0].get("course_id"):
        return rows[0]["course_id"]
    return ""


def _get_course_documents(user_id: str, course_id: str) -> list:
    """Fetch uploaded document summaries and concept notes for a user's course."""
    if not course_id:
        return []
    try:
        docs = table("documents").select(
            "file_name,category,summary,concept_notes",
            filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
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
    rows = table("users").select("name", filters={"id": f"eq.{user_id}"})
    if not rows:
        return "Student"
    return decrypt_if_present(rows[0]["name"]) or "Student"


def _consume_pending(session_id: str, user_id: str) -> None:
    """If session was started lazily, persist session row + first assistant message before user/chat."""
    if session_id not in PENDING_SESSIONS:
        return
    pending = PENDING_SESSIONS.pop(session_id)
    if pending["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Session user mismatch")
    
    # Include course_id in session creation
    session_data = {
        "id": session_id,
        "user_id": user_id,
        "mode": pending["mode"],
        "topic": pending["topic"],
    }
    if pending.get("course_id"):
        session_data["course_id"] = pending["course_id"]
    
    table("sessions").insert(session_data)
    save_message(session_id, "assistant", pending["assistant_reply"], pending["graph_update"])


def _ensure_session_ready(session_id: str, user_id: str) -> None:
    """For action/mode-switch: materialize lazy session if still pending."""
    _consume_pending(session_id, user_id)


@router.post("/start-session")
def start_session(body: StartSessionBody, request: Request):
    require_self(body.user_id, request)
    session_id = str(uuid.uuid4())

    student_name = get_user_name(body.user_id)
    graph_data = get_graph(body.user_id)
    
    # Use course_id from body, or try to resolve from topic
    course_id = body.course_id or _get_course_id_for_topic(body.topic, body.user_id)
    documents = _get_course_documents(body.user_id, course_id)
    
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
        raw = call_gemini_multiturn(system_prompt, [], user_message)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

    reply, graph_update = extract_graph_update(raw)
    apply_graph_update(body.user_id, graph_update, course_id=course_id)
    
    PENDING_SESSIONS[session_id] = {
        "user_id": body.user_id,
        "mode": body.mode,
        "topic": body.topic,
        "course_id": course_id,
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
def chat(body: ChatBody, request: Request):
    require_self(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)
    save_message(body.session_id, "user", body.message)

    student_name = get_user_name(body.user_id)
    graph_data = get_graph(body.user_id)
    # Exclude the just-saved user message so history is prior turns only
    history = get_conversation_history(body.session_id)[:-1]
    
    # Get course_id from session if available
    course_id = _get_session_course_id(body.session_id)
    documents = _get_course_documents(body.user_id, course_id)
    
    system_prompt = build_system_prompt(
        body.mode, student_name, json.dumps(graph_data, indent=2),
        course_id=course_id, use_shared_context=body.use_shared_context,
        documents=documents,
    )

    try:
        raw = call_gemini_multiturn(system_prompt, history, body.message)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

    reply, graph_update = extract_graph_update(raw)
    save_message(body.session_id, "assistant", reply, graph_update)
    mastery_changes = apply_graph_update(body.user_id, graph_update, course_id=course_id)

    return {"reply": reply, "graph_update": graph_update, "mastery_changes": mastery_changes}


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
        "id,user_id,topic,mode,course_id,started_at,ended_at",
        filters={"user_id": f"eq.{user_id}"},
        order="started_at.desc",
        limit=limit,
    )
    result = []
    for s in sessions:
        msgs = table("messages").select("id", filters={"session_id": f"eq.{s['id']}"})
        result.append({
            "id": s["id"],
            "topic": s["topic"],
            "mode": s["mode"],
            "course_id": s.get("course_id"),
            "started_at": s["started_at"],
            "ended_at": s.get("ended_at"),
            "message_count": len(msgs),
            "is_active": s.get("ended_at") is None,
        })
    return {"sessions": result}


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
        "id,user_id,topic,mode,started_at,ended_at,course_id",
        filters={"id": f"eq.{session_id}"},
    )
    if not session_rows:
        raise HTTPException(status_code=404, detail="Session not found")
    if session_rows[0].get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Session user mismatch")

    msgs = table("messages").select(
        "id,role,content,created_at",
        filters={"session_id": f"eq.{session_id}"},
        order="created_at.asc",
    )
    return {
        "session": session_rows[0],
        "messages": [
            {**m, "content": decrypt_if_present(m["content"])} for m in msgs
        ],
    }


@router.post("/action")
def action(body: ActionBody, request: Request):
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
    
    # Get course_id from session
    course_id = _get_session_course_id(body.session_id)
    documents = _get_course_documents(body.user_id, course_id)
    
    system_prompt = build_system_prompt(
        body.mode, student_name, json.dumps(graph_data, indent=2),
        course_id=course_id, use_shared_context=body.use_shared_context,
        documents=documents,
    )
    action_message = f"[ACTION: {action_prompts.get(body.action_type, '')}]"

    try:
        raw = call_gemini_multiturn(system_prompt, history, action_message)
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
