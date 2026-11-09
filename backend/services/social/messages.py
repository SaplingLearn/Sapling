"""
backend/services/social/messages.py

Room messages: the paged transcript, post (reply must quote a message in
the same room, #115), edit, delete (content removed, #764) and reactions.

Moved verbatim out of ``routes/social.py`` (#118); the route keeps the
caller checks (``require_self`` / the session user) and maps
``services.social.errors`` to HTTP statuses.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from db.connection import table
from models import EditMessageBody, SendMessageBody, ToggleReactionBody
from services.encryption import decrypt_if_present, encrypt_if_present
from services.social.errors import Conflict, Forbidden, InvalidRequest, NotFound
from services.social.rooms import _require_member

# The route's logger name, kept so log filters and caplog keep matching.
logger = logging.getLogger("routes.social")


def _message_in_room(room_id: str, message_id: str | None) -> str | None:
    """The canonical id of `message_id` when it names a message IN `room_id`,
    else None (#115).

    A message id alone is not an authorization: room_messages ids are global,
    so any route that takes one alongside a room must check the pair, or a
    member of room X can act on (or quote) a message that lives in room Y.
    "No such message", "not a uuid" and "a message in another room" are all
    the same None, so callers answer one 404 and leak no existence oracle.
    """
    if not message_id:
        return None
    try:
        canonical = str(uuid.UUID(str(message_id)))
    except ValueError:
        return None
    rows = table("room_messages").select(
        "id", filters={"id": f"eq.{canonical}", "room_id": f"eq.{room_id}"},
    )
    return canonical if rows else None


def get_room_messages(room_id: str, viewer_id: str, before: str | None = None, limit: int = 50):
    _require_member(room_id, viewer_id)

    limit = max(1, min(200, limit))
    filters = {"room_id": f"eq.{room_id}"}
    if before:
        # Validate as ISO 8601 so an attacker can't inject PostgREST operators
        # (e.g. `null`, `is.null`, `gt.2026-01-01`) into the filter value.
        try:
            datetime.fromisoformat(before.replace("Z", "+00:00"))
        except ValueError:
            raise InvalidRequest("`before` must be an ISO 8601 timestamp")
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
        # Room-scoped (#115): a reply can only quote a message in THIS room.
        # The post path now refuses a foreign reply_to_id, but rows stored
        # before that check may still point across rooms; they render with no
        # snippet rather than another room's decrypted text.
        reply_rows = table("room_messages").select(
            "id,user_name,text,is_deleted",
            filters={"id": f"in.({','.join(reply_ids)})", "room_id": f"eq.{room_id}"},
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


def send_room_message(room_id: str, body: SendMessageBody):
    membership = table("room_members").select(
        "user_id", filters={"room_id": f"eq.{room_id}", "user_id": f"eq.{body.user_id}"}
    )
    if not membership:
        raise Forbidden("Not a member of this room")

    # #115: a reply must quote a message in this same room. Unchecked, a
    # member of a shared room could set reply_to_id to a message from a room
    # they are not in, and every member's transcript would render that
    # message's decrypted text as the reply snippet.
    reply_to_id = None
    if body.reply_to_id:
        reply_to_id = _message_in_room(room_id, body.reply_to_id)
        if reply_to_id is None:
            raise NotFound("Message not found")

    row = table("room_messages").insert({
        "room_id": room_id,
        "user_id": body.user_id,
        "user_name": body.user_name,
        "text": encrypt_if_present(body.text or None),
        "image_url": body.image_url or None,
        "image_width": body.image_width or None,
        "image_height": body.image_height or None,
        "reply_to_id": reply_to_id,
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
        logger.exception(
            "achievement dispatch failed after room message user=%s room=%s",
            body.user_id, room_id,
        )

    return {"message": row[0] if row else {}}


def delete_room_message(room_id: str, message_id: str, user_id: str):
    # Room-scoped (wave-1 §10): a message id alone is not the pair the path names.
    rows = table("room_messages").select("user_id", filters={"id": f"eq.{message_id}", "room_id": f"eq.{room_id}"})
    if not rows:
        raise NotFound("Message not found")
    if rows[0]["user_id"] != user_id:
        raise Forbidden("Cannot delete another user's message")
    # #764: a delete removes the content, not just hides it. Before this the
    # ciphertext (and image link) stayed in the row behind the flag, so a
    # "deleted" message was still recoverable by anyone holding the key.
    table("room_messages").update(
        {"is_deleted": True, "text": None, "image_url": None},
        filters={"id": f"eq.{message_id}", "room_id": f"eq.{room_id}", "user_id": f"eq.{user_id}"},
    )
    return {"deleted": True}


def edit_room_message(room_id: str, message_id: str, body: EditMessageBody):
    rows = table("room_messages").select(
        "user_id,is_deleted", filters={"id": f"eq.{message_id}", "room_id": f"eq.{room_id}"})
    if not rows:
        raise NotFound("Message not found")
    if rows[0]["user_id"] != body.user_id:
        raise Forbidden("Cannot edit another user's message")
    if rows[0].get("is_deleted"):
        raise InvalidRequest("Cannot edit a deleted message")
    # #764: conditional on is_deleted=false, so an edit racing a delete cannot
    # write fresh text onto the just-deleted (and just-cleared) message.
    edited = table("room_messages").update(
        {"text": encrypt_if_present(body.text), "edited_at": datetime.now(timezone.utc).isoformat()},
        filters={"id": f"eq.{message_id}", "room_id": f"eq.{room_id}", "user_id": f"eq.{body.user_id}",
                 "is_deleted": "eq.false"},
    )
    if not edited:
        raise Conflict("Cannot edit a deleted message")
    return {"edited": True}


def toggle_reaction(room_id: str, message_id: str, body: ToggleReactionBody):
    # #115: only a member reacts, and only to a message in this room. Neither
    # was checked, so anyone holding a message id could add (or remove their
    # own) reaction rows on a message in a room they were never in.
    _require_member(room_id, body.user_id)
    message_id = _message_in_room(room_id, message_id)
    if message_id is None:
        raise NotFound("Message not found")
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
