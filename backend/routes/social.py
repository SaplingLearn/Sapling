import uuid
import random
import string
from datetime import datetime, timezone
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query, Request

from agents._run import run_agent_sync
from agents.deps import SaplingDeps
from agents.social_summary import social_summary_agent
from agents.usage import record_agent_usage
from db.connection import table
from models import CreateRoomBody, JoinRoomBody, MatchBody, PublicJoinBody, SendMessageBody, EditMessageBody, ToggleReactionBody, LeaveRoomBody, FriendRequestBody
from services.auth_guard import require_self, get_session_user_id
from services.achievement_service import check_achievements
from services.encryption import encrypt_if_present, decrypt_if_present
from services.profiles import get_display_name, get_display_names
from services.graph_service import get_graph
from services import academics
from services.matching_service import find_study_matches
from services.request_context import current_request_id
from services.social_cache_service import get_cached_summary, save_summary, invalidate as invalidate_summary

router = APIRouter()


def _touch_room(room_id: str) -> None:
    """Bump rooms.updated_at on membership changes (#405 gave it a writer;
    message traffic is deliberately left alone — the 0033 realtime publication
    owns that flow)."""
    table("rooms").update(
        {"updated_at": datetime.now(timezone.utc).isoformat()},
        {"id": f"eq.{room_id}"},
    )


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
        # #405 semantics: owner_id is REAL ownership (transferable later),
        # seeded to the creator; is_public gates the invite-less public join.
        "owner_id": body.user_id,
        "topic": body.topic,
        "course": body.course,
        "is_public": body.is_public,
    })
    table("room_members").insert({"room_id": room_id, "user_id": body.user_id})
    invalidate_summary(room_id)

    # Creating a room seeds owned_room_members at 1. Below the shipped
    # threshold of 5, but the stat is admin-configurable from the wiki, so the
    # create path dispatches it too rather than only the join path.
    try:
        from services.achievement_service import check_achievements
        check_achievements(body.user_id, "owned_room_members", {})
    except Exception:
        pass

    return {"room_id": room_id, "invite_code": invite_code}


@router.get("/public-rooms")
def list_public_rooms(request: Request, user_id: str = Query(...)):
    """Public rooms (#405): is_public=true rooms, joinable without an invite.
    The select never includes invite_code, so the public listing cannot leak
    the private join path."""
    require_self(user_id, request)
    rooms = table("rooms").select(
        "id,name,topic,course,owner_id,created_by,created_at,updated_at,is_public",
        filters={"is_public": "eq.true"},
    ) or []
    out = []
    for room in rooms:
        members = table("room_members").select(
            "user_id", filters={"room_id": f"eq.{room['id']}"},
        ) or []
        # Explicit projection (never a row spread): the public payload cannot
        # leak invite_code even if the row carries it.
        out.append({
            "id": room["id"],
            "name": room.get("name"),
            "topic": room.get("topic"),
            "course": room.get("course"),
            "owner_id": room.get("owner_id"),
            "created_by": room.get("created_by"),
            "created_at": room.get("created_at"),
            "updated_at": room.get("updated_at"),
            "is_public": True,
            "member_count": len(members),
        })
    return {"rooms": out}


@router.post("/public-rooms/{room_id}/join")
def join_public_room(room_id: str, body: PublicJoinBody, request: Request):
    require_self(body.user_id, request)
    rooms = table("rooms").select("id,is_public", filters={"id": f"eq.{room_id}"})
    if not rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    if not rooms[0].get("is_public"):
        raise HTTPException(status_code=403, detail="This room is invite-only")
    existing = table("room_members").select(
        "room_id", filters={"room_id": f"eq.{room_id}", "user_id": f"eq.{body.user_id}"},
    )
    if not existing:
        # UPSERT, not insert: the pre-read is only a "did we actually add"
        # signal, so a double-click racing itself must no-op on the
        # room_members PK rather than surface a raw 500 (PR #485 review;
        # same shape as #464's check-then-act finding).
        table("room_members").upsert(
            {"room_id": room_id, "user_id": body.user_id}, on_conflict="room_id,user_id",
        )
        _touch_room(room_id)
        invalidate_summary(room_id)
    return {"joined": True, "room_id": room_id}


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
        table("room_members").upsert(
            {"room_id": room["id"], "user_id": body.user_id}, on_conflict="room_id,user_id",
        )
        _touch_room(room["id"])
        invalidate_summary(room["id"])

    members = table("room_members").select("user_id", filters={"room_id": f"eq.{room['id']}"})

    # Check for achievements after room join
    try:
        from services.achievement_service import check_achievements
        check_achievements(body.user_id, "rooms_joined", {})
        # owned_room_members (`room-leader`/Grovekeeper: build a room five
        # people join) is the ROOM CREATOR's stat, not the joiner's — a join
        # advances someone else's badge. Dispatching it for body.user_id would
        # evaluate the wrong user's rooms and the owner would never be granted.
        owner = room.get("created_by")
        if owner:
            check_achievements(owner, "owned_room_members", {})
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
        # Names live on user_profiles (0024); resolve in bulk and decrypt.
        name_map = get_display_names(member_ids)
        for uid in member_ids:
            members.append({
                "user_id": uid,
                "name": name_map.get(uid, ""),
                "graph": get_graph(uid),
            })

    member_summaries = []
    for m in members:
        nodes = m["graph"]["nodes"]
        mastered = [n["concept_name"] for n in nodes if n["mastery_tier"] == "mastered"]
        struggling = [n["concept_name"] for n in nodes if n["mastery_tier"] == "struggling"]
        member_summaries.append(f"{m['name']}: mastered {mastered}, struggling with {struggling}")

    ai_summary = get_cached_summary(room_id, member_summaries)
    if ai_summary is None:
        try:
            from db.connection import _client  # opaque pass-through for SaplingDeps
            deps = SaplingDeps(
                user_id=viewer_id,  # already resolved at the membership gate above
                course_id=None,
                supabase=_client,
                request_id=current_request_id() or "",
                session_id=room_id,
            )
            user_message = (
                "Summarize this study group's collective knowledge:\n"
                + "\n".join(member_summaries)
            )
            result = record_agent_usage(
                run_agent_sync(social_summary_agent.run(user_message, deps=deps)),
                feature="social", task="social_summary",
            )
            ai_summary = result.output.summary
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
    user_name_map = get_display_names(user_ids) if user_ids else {}

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
        # Names live on user_profiles (0024); resolve in bulk and decrypt.
        name_map = get_display_names(member_ids)
        members_with_graphs = [
            {"user_id": uid, "name": name_map.get(uid, ""), "graph": get_graph(uid)}
            for uid in member_ids
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
        "id",
        filters={"id": f"not.in.({','.join(excl_list)})"},
    )

    # Names live on user_profiles (0024); resolve in bulk and decrypt.
    school_ids = [u["id"] for u in school_users]
    name_map = get_display_names(school_ids)
    members_with_graphs = [
        {"user_id": uid, "name": name_map.get(uid, ""), "graph": get_graph(uid)}
        for uid in school_ids
    ]

    requester_graph = get_graph(body.user_id)
    requester_name = get_display_name(body.user_id) or body.user_id

    all_members = [
        {"user_id": body.user_id, "name": requester_name, "graph": requester_graph}
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
    _touch_room(room_id)
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
    # #405: authorization keys on owner_id (real, transferable ownership) —
    # created_by stays the immutable creator record and no longer gates.
    if room_rows[0]["owner_id"] != requester_id:
        raise HTTPException(status_code=403, detail="Only the room owner can kick members")
    table("room_members").delete({"room_id": f"eq.{room_id}", "user_id": f"eq.{member_id}"})
    _touch_room(room_id)
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
    # Over-fetch one row so `has_more` is exact: if the DB returns more than
    # `limit`, an extra page exists. (Using `len(rows) == limit` reports a
    # phantom "load more" at exact page boundaries — issue #131.)
    rows = table("room_messages").select(
        "id,room_id,user_id,user_name,text,image_url,image_width,image_height,reply_to_id,is_deleted,edited_at,created_at",
        filters=filters,
        order="created_at.desc",
        limit=limit + 1,
    )
    if not rows:
        return {"messages": [], "has_more": False}
    has_more = len(rows) > limit
    rows = rows[:limit]  # drop the probe row before reversing
    rows = list(reversed(rows))

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
                "text": None if rr.get("is_deleted") else decrypt_if_present(rr.get("text")),
            }

    enriched = []
    for r in rows:
        mid = r["id"]
        emoji_map = reactions_by_msg.get(mid, {})
        r["text"] = decrypt_if_present(r.get("text"))
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
        "text": encrypt_if_present(body.text or None),
        "image_url": body.image_url or None,
        "image_width": body.image_width or None,
        "image_height": body.image_height or None,
        "reply_to_id": body.reply_to_id or None,
    })

    if row:
        row[0]["text"] = decrypt_if_present(row[0].get("text"))

    # Check for achievements after message send. Posting is the only thing
    # that advances room_replies (`helping-hand`: answer in someone else's
    # room) and rooms_active (`social-butterfly`: post in five different
    # rooms), so this is their only possible dispatch point.
    try:
        from services.achievement_service import check_achievements
        check_achievements(body.user_id, "post_count", {})
        check_achievements(body.user_id, "room_replies", {})
        check_achievements(body.user_id, "rooms_active", {})
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
        {"text": encrypt_if_present(body.text), "edited_at": datetime.now(timezone.utc).isoformat()},
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
    """A lightweight directory of students who share the viewer's school.

    Scoped for #342. Before this, the endpoint returned a profile for *every*
    user in the DB to any authenticated caller — the `user_id` was bound and
    never used, so it authenticated without authorizing. Two boundaries now
    apply:

    - **School scope**: only users enrolled at the same school as the viewer
      (via ``academics.school_peer_user_ids``). An empty scope (viewer not
      enrolled / course carries no school) yields an empty directory — fail
      closed, mirroring the enrollment-scoping pattern in ``calendar.py``.
    - **profile_visibility**: users who set their profile to ``private`` opt out
      of the directory entirely. ``public`` and ``school`` are both listed (the
      endpoint is already school-scoped, so they're equivalent here).

    The payload is deliberately lightweight — name, streak, course names — and
    carries **no mastery data**: per-concept mastery is academic-performance
    information that belongs on the profile page (which already gates detail on
    profile_visibility), not in a browsable directory.
    """
    user_id = get_session_user_id(request)

    peer_ids = academics.school_peer_user_ids(user_id)
    if not peer_ids:
        return {"students": []}
    peer_list = sorted(peer_ids)

    # Honor profile_visibility: drop 'private' users from the listing. Users with
    # no settings row default to 'public' (the column default), so they stay.
    settings_rows = table("user_settings").select(
        "user_id,profile_visibility",
        filters={"user_id": f"in.({','.join(peer_list)})"},
    ) or []
    hidden = {
        s["user_id"] for s in settings_rows if s.get("profile_visibility") == "private"
    }
    visible_ids = [uid for uid in peer_list if uid not in hidden]
    if not visible_ids:
        return {"students": []}

    users = table("users").select(
        "id,streak_count", filters={"id": f"in.({','.join(visible_ids)})"}
    ) or []
    # Display names live on user_profiles (0024); resolve in bulk and decrypt.
    name_map = get_display_names([u["id"] for u in users])

    # A user's courses resolve through the enrollment chain
    # (enrollments → course_offerings → courses); the abstract `courses` catalog
    # no longer carries a per-user row. Read the offering's abstract course name
    # via the embedded join and dedup, since one abstract course may have several
    # offerings (per term/section) the user is enrolled in.
    enrollment_rows = table("enrollments").select(
        "user_id,course_offerings(courses(course_name))",
        filters={"user_id": f"in.({','.join(visible_ids)})"},
    ) or []
    courses_by_user: dict = defaultdict(set)
    for e in enrollment_rows:
        offering = e.get("course_offerings") or {}
        course = offering.get("courses") or {} if isinstance(offering, dict) else {}
        course_name = course.get("course_name") if isinstance(course, dict) else None
        if course_name:
            courses_by_user[e["user_id"]].add(course_name)

    students = [
        {
            "user_id": u["id"],
            "name": name_map.get(u["id"], ""),
            "streak": u.get("streak_count") or 0,
            "courses": sorted(courses_by_user[u["id"]]),
        }
        for u in users
    ]
    students.sort(key=lambda s: (s["name"] or ""))
    return {"students": students}


# ── Friends ──────────────────────────────────────────────────────────────────

def _are_friends(user_id: str, other_id: str) -> bool:
    rows = table("friendships").select(
        "friend_id", filters={"user_id": f"eq.{user_id}", "friend_id": f"eq.{other_id}"}
    )
    return bool(rows)


@router.post("/friends/request")
def send_friend_request(body: FriendRequestBody, request: Request):
    require_self(body.from_user_id, request)
    if body.from_user_id == body.to_user_id:
        raise HTTPException(status_code=400, detail="You can't friend yourself")
    if _are_friends(body.from_user_id, body.to_user_id):
        raise HTTPException(status_code=409, detail="Already friends")
    # Deliberately only the exact (from, to) pair — a pending REVERSE request
    # is left alone rather than auto-accepted or rejected. Mutual pending
    # requests are legal and harmless now that accept_friend_request is
    # idempotent: whichever is accepted first makes the other a no-op that
    # still resolves its row. Auto-accepting here would silently create a
    # friendship from a click that only meant "send a request".
    existing = table("friend_requests").select(
        "id,status",
        filters={
            "from_user_id": f"eq.{body.from_user_id}",
            "to_user_id": f"eq.{body.to_user_id}",
        },
    )
    if existing:
        if existing[0].get("status") == "pending":
            raise HTTPException(status_code=409, detail="Request already pending")
        # A row for this (from_user_id, to_user_id) pair already exists —
        # declined, or accepted-then-unfriended (remove_friend only deletes
        # the symmetric friendships rows, it deliberately leaves the
        # historical friend_requests row in place). UNIQUE(from_user_id,
        # to_user_id) means a second insert here would 409/500 on the
        # constraint, so reactivate the existing row instead of inserting
        # a duplicate.
        result = table("friend_requests").update(
            {
                "status": "pending",
                "responded_at": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            filters={"id": f"eq.{existing[0]['id']}"},
        )
        return {"request": result[0] if result else None}
    result = table("friend_requests").insert({
        "from_user_id": body.from_user_id,
        "to_user_id": body.to_user_id,
        "status": "pending",
    })
    return {"request": result[0] if result else None}


def _load_request(request_id: str, user_id: str) -> dict:
    rows = table("friend_requests").select(
        "id,from_user_id,to_user_id,status", filters={"id": f"eq.{request_id}"}
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Request not found")
    req = rows[0]
    if req["to_user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not your request to answer")
    return req


@router.post("/friends/requests/{request_id}/accept")
def accept_friend_request(request_id: str, user_id: str, request: Request):
    require_self(user_id, request)
    req = _load_request(request_id, user_id)
    a, b = req["from_user_id"], req["to_user_id"]

    # Accepting is idempotent. friendships is PRIMARY KEY (user_id, friend_id),
    # so a second write of the same pair is a duplicate-key 500 — and since the
    # request row would stay `pending`, it 500d on every retry, permanently.
    # Two ways in, neither needing an adversary:
    #   1. a plain double-click / retry on a request already accepted;
    #   2. mutual requests — send_friend_request only checks the exact
    #      (from, to) pair, never the reverse, so A->B and B->A can both sit
    #      pending; accepting one makes the other's accept a duplicate.
    # Case (1) is the status check, case (2) is the _are_friends check. Both
    # still resolve the request row so a stale `pending` stops surfacing as an
    # actionable incoming request forever.
    already = req.get("status") != "pending" or _are_friends(a, b)

    if not already:
        # Symmetric rows: "my friends" stays a plain equality filter.
        # upsert, not insert: two simultaneous accepts (a real double-click
        # fires both before either has updated the status) both read `pending`,
        # so the check above cannot close the race on its own — the write has
        # to tolerate the conflict too.
        table("friendships").upsert([
            {"user_id": a, "friend_id": b},
            {"user_id": b, "friend_id": a},
        ], on_conflict="user_id,friend_id")

    table("friend_requests").update(
        {"status": "accepted", "responded_at": datetime.now(timezone.utc).isoformat()},
        filters={"id": f"eq.{request_id}"},
    )
    if already:
        return {"accepted": True}

    check_achievements(a, "friends_count")
    check_achievements(b, "friends_count")
    return {"accepted": True}


@router.post("/friends/requests/{request_id}/decline")
def decline_friend_request(request_id: str, user_id: str, request: Request):
    require_self(user_id, request)
    _load_request(request_id, user_id)
    table("friend_requests").update(
        {"status": "declined", "responded_at": datetime.now(timezone.utc).isoformat()},
        filters={"id": f"eq.{request_id}"},
    )
    return {"declined": True}


@router.delete("/friends/{friend_id}")
def remove_friend(friend_id: str, user_id: str, request: Request):
    require_self(user_id, request)
    table("friendships").delete(
        filters={"user_id": f"eq.{user_id}", "friend_id": f"eq.{friend_id}"}
    )
    table("friendships").delete(
        filters={"user_id": f"eq.{friend_id}", "friend_id": f"eq.{user_id}"}
    )
    return {"removed": True}


@router.get("/friends/requests")
def list_friend_requests(user_id: str, request: Request):
    require_self(user_id, request)
    incoming = table("friend_requests").select(
        "id,from_user_id,created_at",
        filters={"to_user_id": f"eq.{user_id}", "status": "eq.pending"},
    ) or []
    outgoing = table("friend_requests").select(
        "id,to_user_id,created_at",
        filters={"from_user_id": f"eq.{user_id}", "status": "eq.pending"},
    ) or []
    ids = [r["from_user_id"] for r in incoming] + [r["to_user_id"] for r in outgoing]
    names = get_display_names(ids) if ids else {}
    return {
        "incoming": [
            {**r, "name": names.get(r["from_user_id"], "Someone")} for r in incoming
        ],
        "outgoing": [
            {**r, "name": names.get(r["to_user_id"], "Someone")} for r in outgoing
        ],
    }


@router.get("/friends/{user_id}")
def list_friends(user_id: str, request: Request):
    # Self-only for now: a friends list is arguably shareable with other
    # users later (product decision), but the safe default until that's
    # decided is that only the account owner can list their own friends.
    require_self(user_id, request)
    rows = table("friendships").select("friend_id", filters={"user_id": f"eq.{user_id}"})
    ids = [r["friend_id"] for r in rows or []]
    if not ids:
        return {"friends": []}
    users = table("users").select(
        "id,level,total_xp", filters={"id": f"in.({','.join(ids)})"}
    ) or []
    names = get_display_names(ids)
    return {"friends": [
        {
            "user_id": u["id"],
            "name": names.get(u["id"], "Someone"),
            "level": u.get("level") or 1,
            "total_xp": u.get("total_xp") or 0,
        }
        for u in users
    ]}
