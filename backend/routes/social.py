import uuid
import random
import string
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query, Request

from db.connection import table
from models import CreateRoomBody, JoinRoomBody, MatchBody, SendMessageBody, EditMessageBody, ToggleReactionBody, LeaveRoomBody
from services.auth_guard import require_self, get_session_user_id
from services.graph_service import get_graph
from services.matching_service import find_study_matches
from services.gemini_service import call_gemini
from services.social_cache_service import get_cached_summary, save_summary, invalidate as invalidate_summary

router = APIRouter()


@router.post("/rooms/create")
def create_room(body: CreateRoomBody, request: Request):
    require_self(body.user_id, request)
    invite_code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    room_id = str(uuid.uuid4())
    table("rooms").insert({
        "id": room_id,
        "name": body.room_name,
        "invite_code": invite_code,
        "created_by": body.user_id,
    })
    table("room_members").insert({"room_id": room_id, "user_id": body.user_id})
    invalidate_summary(room_id)
    return {"room_id": room_id, "invite_code": invite_code}


@router.post("/rooms/join")
def join_room(body: JoinRoomBody, request: Request):
    require_self(body.user_id, request)
    room_rows = table("rooms").select(
        "id,name,topic,course,owner_id,created_by,invite_code,created_at,updated_at,is_public",
        filters={"invite_code": f"eq.{body.invite_code.strip().upper()}"},
    )
    if not room_rows:
        raise HTTPException(status_code=404, detail="Room not found")
    room = room_rows[0]

    existing = table("room_members").select(
        "room_id",
        filters={"room_id": f"eq.{room['id']}", "user_id": f"eq.{body.user_id}"},
    )
    if not existing:
        table("room_members").insert({"room_id": room["id"], "user_id": body.user_id})
        invalidate_summary(room["id"])

    members = table("room_members").select("user_id", filters={"room_id": f"eq.{room['id']}"})

    # Check for achievements after room join
    try:
        from services.achievement_service import check_achievements
        check_achievements(body.user_id, "rooms_joined", {})
    except Exception:
        pass

    return {"room": {**room, "member_count": len(members)}}


@router.get("/rooms/{user_id}")
def get_user_rooms(user_id: str, request: Request):
    require_self(user_id, request)
    memberships = table("room_members").select("room_id", filters={"user_id": f"eq.{user_id}"})
    room_ids = [m["room_id"] for m in memberships]
    if not room_ids:
        return {"rooms": []}

    rooms = table("rooms").select(
        "id,name,topic,course,owner_id,created_by,invite_code,created_at,updated_at,is_public",
        filters={"id": f"in.({','.join(room_ids)})"},
    )
    for room in rooms:
        members = table("room_members").select("user_id", filters={"room_id": f"eq.{room['id']}"})
        room["member_count"] = len(members)
    return {"rooms": rooms}


@router.get("/rooms/{room_id}/overview")
def room_overview(room_id: str, request: Request):
    viewer_id = get_session_user_id(request)
    membership = table("room_members").select(
        "user_id", filters={"room_id": f"eq.{room_id}", "user_id": f"eq.{viewer_id}"}
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this room")

    room_rows = table("rooms").select(
        "id,name,topic,course,owner_id,created_by,invite_code,created_at,updated_at,is_public",
        filters={"id": f"eq.{room_id}"},
    )
    if not room_rows:
        raise HTTPException(status_code=404, detail="Room not found")
    room = room_rows[0]

    member_id_rows = table("room_members").select("user_id", filters={"room_id": f"eq.{room_id}"})
    member_ids = [m["user_id"] for m in member_id_rows]

    members = []
    if member_ids:
        user_rows = table("users").select(
            "id,name", filters={"id": f"in.({','.join(member_ids)})"}  # ENCRYPTED LATER
        )
        for u in user_rows:
            members.append({"user_id": u["id"], "name": u["name"], "graph": get_graph(u["id"])})  # ENCRYPTED LATER

    member_summaries = []
    for m in members:
        nodes = m["graph"]["nodes"]
        mastered = [n["concept_name"] for n in nodes if n["mastery_tier"] == "mastered"]
        struggling = [n["concept_name"] for n in nodes if n["mastery_tier"] == "struggling"]
        member_summaries.append(f"{m['name']}: mastered {mastered}, struggling with {struggling}")  # ENCRYPTED LATER

    ai_summary = get_cached_summary(room_id, member_summaries)
    if ai_summary is None:
        try:
            ai_summary = call_gemini(
                "Write a 2-3 sentence summary of this study group's collective knowledge:\n"
                + "\n".join(member_summaries)
                + "\nFocus on complementary strengths and shared goals."
            )
            save_summary(room_id, member_summaries, ai_summary)
        except Exception as e:
            print(f"Gemini summary failed: {e}")
            ai_summary = "This study group has complementary strengths across multiple subjects."

    return {"room": room, "members": members, "ai_summary": ai_summary}


@router.get("/rooms/{room_id}/activity")
def room_activity(room_id: str, request: Request):
    viewer_id = get_session_user_id(request)
    membership = table("room_members").select(
        "user_id", filters={"room_id": f"eq.{room_id}", "user_id": f"eq.{viewer_id}"}
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this room")

    activity_rows = table("room_activity").select(
        "id,room_id,user_id,activity_type,concept_name,detail,created_at",
        filters={"room_id": f"eq.{room_id}"},
        order="created_at.desc",
        limit=20,
    )

    user_ids = list(set(a["user_id"] for a in activity_rows))
    user_name_map = {}
    if user_ids:
        user_rows = table("users").select("id,name", filters={"id": f"in.({','.join(user_ids)})"})  # ENCRYPTED LATER
        user_name_map = {u["id"]: u["name"] for u in user_rows}  # ENCRYPTED LATER

    activities = [
        {
            "id": a["id"],
            "user_name": user_name_map.get(a["user_id"], a["user_id"]),
            "activity_type": a["activity_type"],
            "concept_name": a.get("concept_name"),
            "detail": a.get("detail", ""),
            "created_at": a["created_at"],
        }
        for a in activity_rows
    ]
    return {"activities": activities}


@router.post("/rooms/{room_id}/match")
def match_partners(room_id: str, body: MatchBody, request: Request):
    require_self(body.user_id, request)
    member_id_rows = table("room_members").select("user_id", filters={"room_id": f"eq.{room_id}"})
    member_ids = [m["user_id"] for m in member_id_rows]

    members_with_graphs = []
    if member_ids:
        user_rows = table("users").select("id,name", filters={"id": f"in.({','.join(member_ids)})"})  # ENCRYPTED LATER
        members_with_graphs = [
            {"user_id": u["id"], "name": u["name"], "graph": get_graph(u["id"])}  # ENCRYPTED LATER
            for u in user_rows
        ]

    try:
        matches = find_study_matches(body.user_id, members_with_graphs)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")
    return {"matches": matches}


@router.post("/school-match")
def school_match(body: MatchBody, request: Request):
    """
    Match the requesting user against all users NOT in any of their study rooms.
    """
    require_self(body.user_id, request)
    user_room_rows = table("room_members").select(
        "room_id", filters={"user_id": f"eq.{body.user_id}"}
    )
    user_room_ids = [r["room_id"] for r in user_room_rows]

    excluded_ids = set()
    if user_room_ids:
        room_member_rows = table("room_members").select(
            "user_id", filters={"room_id": f"in.({','.join(user_room_ids)})"}
        )
        excluded_ids = {r["user_id"] for r in room_member_rows}

    excluded_ids.add(body.user_id)
    excl_list = list(excluded_ids)

    school_users = table("users").select(
        "id,name",  # ENCRYPTED LATER
        filters={"id": f"not.in.({','.join(excl_list)})"},
    )

    members_with_graphs = [
        {"user_id": u["id"], "name": u["name"], "graph": get_graph(u["id"])}  # ENCRYPTED LATER
        for u in school_users
    ]

    requester_graph = get_graph(body.user_id)
    requester_rows = table("users").select("name", filters={"id": f"eq.{body.user_id}"})  # ENCRYPTED LATER
    requester_name = requester_rows[0]["name"] if requester_rows else body.user_id  # ENCRYPTED LATER

    all_members = [
        {"user_id": body.user_id, "name": requester_name, "graph": requester_graph}  # ENCRYPTED LATER
    ] + members_with_graphs

    try:
        matches = find_study_matches(body.user_id, all_members)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Matching error: {e}")

    return {"matches": matches}


@router.post("/rooms/{room_id}/leave")
def leave_room(room_id: str, body: LeaveRoomBody, request: Request):
    require_self(body.user_id, request)
    table("room_members").delete({"room_id": f"eq.{room_id}", "user_id": f"eq.{body.user_id}"})
    invalidate_summary(room_id)
    return {"left": True}


@router.delete("/rooms/{room_id}/members/{member_id}")
def kick_member(room_id: str, member_id: str, request: Request, requester_id: str = Query(...)):
    require_self(requester_id, request)
    room_rows = table("rooms").select(
        "id,name,topic,course,owner_id,created_by,invite_code,created_at,updated_at,is_public",
        filters={"id": f"eq.{room_id}"},
    )
    if not room_rows:
        raise HTTPException(status_code=404, detail="Room not found")
    if room_rows[0]["created_by"] != requester_id:
        raise HTTPException(status_code=403, detail="Only the room leader can kick members")
    table("room_members").delete({"room_id": f"eq.{room_id}", "user_id": f"eq.{member_id}"})
    invalidate_summary(room_id)
    return {"kicked": True}


@router.get("/rooms/{room_id}/messages")
def get_room_messages(room_id: str, request: Request, before: str | None = None, limit: int = 50):
    viewer_id = get_session_user_id(request)
    membership = table("room_members").select(
        "user_id", filters={"room_id": f"eq.{room_id}", "user_id": f"eq.{viewer_id}"}
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this room")

    from datetime import datetime
    limit = max(1, min(200, limit))
    filters = {"room_id": f"eq.{room_id}"}
    if before:
        # Validate as ISO 8601 so an attacker can't inject PostgREST operators
        # (e.g. `null`, `is.null`, `gt.2026-01-01`) into the filter value.
        try:
            datetime.fromisoformat(before.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="`before` must be an ISO 8601 timestamp")
        filters["created_at"] = f"lt.{before}"
    # Fetch newest-first so the slice covers the page we need, then reverse to ascending.
    rows = table("room_messages").select(
        "id,room_id,user_id,user_name,text,image_url,reply_to_id,is_deleted,edited_at,created_at",
        filters=filters,
        order="created_at.desc",
        limit=limit,
    )
    if not rows:
        return {"messages": [], "has_more": False}
    rows = list(reversed(rows))
    has_more = len(rows) == limit

    msg_ids = [r["id"] for r in rows]

    # Fetch reactions for all messages in one query
    reaction_rows = table("room_reactions").select(
        "id,message_id,user_id,emoji", filters={"message_id": f"in.({','.join(msg_ids)})"}
    ) if msg_ids else []

    reactions_by_msg: dict = {}
    for r in reaction_rows:
        mid = r["message_id"]
        if mid not in reactions_by_msg:
            reactions_by_msg[mid] = {}
        if r["emoji"] not in reactions_by_msg[mid]:
            reactions_by_msg[mid][r["emoji"]] = []
        reactions_by_msg[mid][r["emoji"]].append(r["user_id"])

    # Fetch reply_to snippets
    reply_ids = list({r["reply_to_id"] for r in rows if r.get("reply_to_id")})
    reply_map: dict = {}
    if reply_ids:
        reply_rows = table("room_messages").select(
            "id,user_name,text,is_deleted",
            filters={"id": f"in.({','.join(reply_ids)})"},
        )
        for rr in reply_rows:
            reply_map[rr["id"]] = {
                "id": rr["id"],
                "user_name": rr["user_name"],
                "text": None if rr.get("is_deleted") else rr.get("text"),
            }

    enriched = []
    for r in rows:
        mid = r["id"]
        emoji_map = reactions_by_msg.get(mid, {})
        r["reactions"] = [{"emoji": e, "user_ids": uids} for e, uids in emoji_map.items()]
        r["reply_to"] = reply_map.get(r.get("reply_to_id")) if r.get("reply_to_id") else None
        enriched.append(r)

    return {"messages": enriched, "has_more": has_more}


@router.post("/rooms/{room_id}/messages")
def send_room_message(room_id: str, body: SendMessageBody, request: Request):
    require_self(body.user_id, request)
    membership = table("room_members").select(
        "user_id", filters={"room_id": f"eq.{room_id}", "user_id": f"eq.{body.user_id}"}
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this room")

    row = table("room_messages").insert({
        "room_id": room_id,
        "user_id": body.user_id,
        "user_name": body.user_name,
        "text": body.text or None,
        "image_url": body.image_url or None,
        "reply_to_id": body.reply_to_id or None,
    })

    # Check for achievements after message send
    try:
        from services.achievement_service import check_achievements
        check_achievements(body.user_id, "post_count", {})
    except Exception:
        pass

    return {"message": row[0] if row else {}}


@router.delete("/rooms/{room_id}/messages/{message_id}")
def delete_room_message(room_id: str, message_id: str, request: Request, user_id: str = Query(...)):
    require_self(user_id, request)
    rows = table("room_messages").select("user_id", filters={"id": f"eq.{message_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Message not found")
    if rows[0]["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Cannot delete another user's message")
    table("room_messages").update({"is_deleted": True}, filters={"id": f"eq.{message_id}"})
    return {"deleted": True}


@router.patch("/rooms/{room_id}/messages/{message_id}")
def edit_room_message(room_id: str, message_id: str, body: EditMessageBody, request: Request):
    require_self(body.user_id, request)
    rows = table("room_messages").select("user_id,is_deleted", filters={"id": f"eq.{message_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Message not found")
    if rows[0]["user_id"] != body.user_id:
        raise HTTPException(status_code=403, detail="Cannot edit another user's message")
    if rows[0].get("is_deleted"):
        raise HTTPException(status_code=400, detail="Cannot edit a deleted message")
    from datetime import datetime, timezone
    table("room_messages").update(
        {"text": body.text, "edited_at": datetime.now(timezone.utc).isoformat()},
        filters={"id": f"eq.{message_id}"},
    )
    return {"edited": True}


@router.post("/rooms/{room_id}/messages/{message_id}/reactions")
def toggle_reaction(room_id: str, message_id: str, body: ToggleReactionBody, request: Request):
    require_self(body.user_id, request)
    existing = table("room_reactions").select(
        "id", filters={"message_id": f"eq.{message_id}", "user_id": f"eq.{body.user_id}", "emoji": f"eq.{body.emoji}"}
    )
    if existing:
        table("room_reactions").delete({"id": f"eq.{existing[0]['id']}"})
        return {"added": False}
    table("room_reactions").insert({
        "message_id": message_id,
        "user_id": body.user_id,
        "emoji": body.emoji,
    })
    return {"added": True}


@router.get("/students")
def get_students(request: Request):
    """Return a lightweight profile for every user in the DB."""
    user_id = get_session_user_id(request)
    users = table("users").select("id,name,streak_count")  # ENCRYPTED LATER
    courses_rows = table("courses").select("user_id,course_name")
    nodes_rows = table("graph_nodes").select("user_id,mastery_tier,concept_name,mastery_score")

    courses_by_user: dict = defaultdict(list)
    for c in courses_rows:
        courses_by_user[c["user_id"]].append(c["course_name"])

    mastery_by_user: dict = defaultdict(
        lambda: {"mastered": 0, "learning": 0, "struggling": 0, "unexplored": 0, "total": 0}
    )
    top_concepts_by_user: dict = defaultdict(list)
    for n in nodes_rows:
        uid = n["user_id"]
        tier = n["mastery_tier"]
        mastery_by_user[uid]["total"] += 1
        if tier in mastery_by_user[uid]:
            mastery_by_user[uid][tier] += 1
        if tier == "mastered":
            top_concepts_by_user[uid].append((n.get("mastery_score", 0), n["concept_name"]))

    # Sort each user's mastered concepts by score desc, keep top 4
    for uid in top_concepts_by_user:
        top_concepts_by_user[uid] = [
            name for _, name in sorted(top_concepts_by_user[uid], reverse=True)[:4]
        ]

    students = [
        {
            "user_id": u["id"],
            "name": u["name"],  # ENCRYPTED LATER
            "streak": u.get("streak_count") or 0,
            "courses": sorted(courses_by_user[u["id"]]),
            "stats": dict(mastery_by_user[u["id"]]),
            "top_concepts": top_concepts_by_user[u["id"]],
        }
        for u in users
    ]
    students.sort(key=lambda s: s["name"])  # ENCRYPTED LATER
    return {"students": students}
