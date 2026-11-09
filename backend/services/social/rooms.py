"""
backend/services/social/rooms.py

Study rooms: create, the public listing and both join paths (invite code
and public), membership, leave (ownership hand-on / room delete) and kick
(a kick is a ban, #764).

Moved verbatim out of ``routes/social.py`` (#118); the route keeps the
caller checks (``require_self`` / the session user) and maps
``services.social.errors`` to HTTP statuses.
"""
from __future__ import annotations

import logging
import random
import string
import uuid
from datetime import datetime, timezone

from db.connection import table
from models import CreateRoomBody, JoinRoomBody, LeaveRoomBody, PublicJoinBody
from services.profiles import live_user_ids
from services.social.errors import Forbidden, InvalidRequest, NotFound
from services.social_cache_service import invalidate as invalidate_summary

# The route's logger name, kept so log filters and caplog keep matching.
logger = logging.getLogger("routes.social")


def _touch_room(room_id: str) -> None:
    """Bump rooms.updated_at on membership changes (#405 gave it a writer;
    message traffic is deliberately left alone — the 0033 realtime publication
    owns that flow)."""
    table("rooms").update(
        {"updated_at": datetime.now(timezone.utc).isoformat()},
        {"id": f"eq.{room_id}"},
    )


def _is_banned(room_id: str, user_id: str) -> bool:
    """A kick records a room_bans row (#764); both join paths refuse it."""
    return bool(table("room_bans").select(
        "user_id", filters={"room_id": f"eq.{room_id}", "user_id": f"eq.{user_id}"},
    ))


def _require_member(room_id: str, user_id: str) -> None:
    membership = table("room_members").select(
        "user_id", filters={"room_id": f"eq.{room_id}", "user_id": f"eq.{user_id}"}
    )
    if not membership:
        raise Forbidden("Not a member of this room")


def _live_members(member_rows) -> list[str]:
    """Room member ids minus soft-deleted accounts (#115), in row order: a
    deleted student's name and graph must not stay on the room's pages."""
    ids = [r["user_id"] for r in member_rows or []]
    live = live_user_ids(ids) if ids else set()
    return [i for i in ids if i in live]


def create_room(body: CreateRoomBody):
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
        # Post-commit: the room already exists, so a failing badge check must
        # not fail the create. Logged, never swallowed — a silent `pass` here
        # is how the `friendships.id` 400 stayed invisible for a whole wave.
        logger.exception(
            "achievement dispatch failed after room create user=%s room=%s",
            body.user_id, room_id,
        )

    return {"room_id": room_id, "invite_code": invite_code}


def list_public_rooms(user_id: str):
    """Public rooms (#405): is_public=true rooms, joinable without an invite.
    The select never includes invite_code, so the public listing cannot leak
    the private join path."""
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


def join_public_room(room_id: str, body: PublicJoinBody):
    # created_by is selected because the achievement dispatch below needs it —
    # owned_room_members is the OWNER's stat, not the joiner's.
    rooms = table("rooms").select(
        "id,is_public,created_by", filters={"id": f"eq.{room_id}"}
    )
    if not rooms:
        raise NotFound("Room not found")
    if not rooms[0].get("is_public"):
        raise Forbidden("This room is invite-only")
    if _is_banned(room_id, body.user_id):
        raise Forbidden("You were removed from this room")
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

    # #405's public rooms are a SECOND way into a room, so they must dispatch
    # exactly what the invite-code path (join_room) dispatches. Without this,
    # `room-leader` (Grovekeeper: create a study room five people join) only
    # advanced for owners whose members happened to arrive by invite code — the
    # same badge, earnable or not depending on which join button the fifth
    # member pressed. Fired unconditionally (not only on a fresh membership),
    # mirroring join_room: a repeat join is a cheap re-evaluation, and the
    # owner's badge must not depend on the joiner's click history.
    try:
        from services.achievement_service import check_achievements
        check_achievements(body.user_id, "rooms_joined", {})
        # The owner is rooms.created_by, NOT the joining user — dispatching for
        # body.user_id would evaluate the wrong user's rooms.
        owner = rooms[0].get("created_by")
        if owner:
            check_achievements(owner, "owned_room_members", {})
    except Exception:
        logger.exception(
            "achievement dispatch failed after public room join user=%s room=%s",
            body.user_id, room_id,
        )

    return {"joined": True, "room_id": room_id}


def join_room(body: JoinRoomBody):
    room_rows = table("rooms").select(
        "id,name,topic,course,owner_id,created_by,invite_code,created_at,updated_at,is_public",
        filters={"invite_code": f"eq.{body.invite_code.strip().upper()}"},
    )
    if not room_rows:
        raise NotFound("Room not found")
    room = room_rows[0]
    if _is_banned(room["id"], body.user_id):
        raise Forbidden("You were removed from this room")

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
        logger.exception(
            "achievement dispatch failed after room join user=%s room=%s",
            body.user_id, room["id"],
        )

    return {"room": {**room, "member_count": len(members)}}


def get_user_rooms(user_id: str):
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


def leave_room(room_id: str, body: LeaveRoomBody):
    # #115: only a member can leave. The delete's own result is the
    # membership test (atomic, no read-then-act window): a non-member used to
    # fall through and bump the room's updated_at, invalidate its summary,
    # read back its owner_id and, for a room whose owner had gone, hand
    # ownership on, all for a room they were never in. Same 403 as every
    # other non-member room action.
    removed = table("room_members").delete(
        {"room_id": f"eq.{room_id}", "user_id": f"eq.{body.user_id}"}
    )
    if not removed:
        raise Forbidden("Not a member of this room")
    invalidate_summary(room_id)

    # #764: a room is owned by a MEMBER, or it does not exist.
    remaining = table("room_members").select(
        "user_id,joined_at",
        filters={"room_id": f"eq.{room_id}"},
        order="joined_at.asc,user_id.asc",
    ) or []
    if not remaining:
        # The last member left: delete the room, which kills its invite code.
        # Its children (members, messages + reactions, activity, summary,
        # bans) cascade (20261106055333_state_machines_audit.sql).
        table("rooms").delete({"id": f"eq.{room_id}"})
        return {"left": True, "room_deleted": True, "owner_id": None}

    room_rows = table("rooms").select("owner_id", filters={"id": f"eq.{room_id}"}) or []
    owner_id = room_rows[0].get("owner_id") if room_rows else None
    member_ids = {m["user_id"] for m in remaining}
    if room_rows and owner_id not in member_ids:
        # The owner left (or, for a room orphaned before #764, had already
        # gone): hand ownership to the earliest remaining member. Conditional
        # on owner_id still being the stale value, so two concurrent leaves
        # cannot both transfer and the later one cannot clobber the earlier.
        new_owner = remaining[0]["user_id"]
        moved = table("rooms").update(
            {"owner_id": new_owner, "updated_at": datetime.now(timezone.utc).isoformat()},
            {"id": f"eq.{room_id}", "owner_id": f"eq.{owner_id}"},
        )
        if moved:
            return {"left": True, "room_deleted": False, "owner_id": new_owner}
    _touch_room(room_id)
    return {"left": True, "room_deleted": False, "owner_id": owner_id}


def kick_member(room_id: str, member_id: str, requester_id: str):
    room_rows = table("rooms").select(
        "id,name,topic,course,owner_id,created_by,invite_code,created_at,updated_at,is_public",
        filters={"id": f"eq.{room_id}"},
    )
    if not room_rows:
        raise NotFound("Room not found")
    # #405: authorization keys on owner_id (real, transferable ownership) —
    # created_by stays the immutable creator record and no longer gates.
    if room_rows[0]["owner_id"] != requester_id:
        raise Forbidden("Only the room owner can kick members")
    if member_id == requester_id:
        # Kicking yourself would leave the room owned by a non-member; leaving
        # is the path that hands ownership on.
        raise InvalidRequest("Leave the room instead of kicking yourself")
    # #764: a kick is a ban. Record it BEFORE removing the membership so a
    # rejoin racing the kick is already refused by the join paths.
    table("room_bans").upsert(
        {"room_id": room_id, "user_id": member_id, "banned_by": requester_id},
        on_conflict="room_id,user_id",
        ignore_duplicates=True,
    )
    table("room_members").delete({"room_id": f"eq.{room_id}", "user_id": f"eq.{member_id}"})
    _touch_room(room_id)
    invalidate_summary(room_id)
    return {"kicked": True}
