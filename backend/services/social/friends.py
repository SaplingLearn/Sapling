"""
backend/services/social/friends.py

Friends: requests (send / accept / decline / cancel, each a conditional
transition, #764), the decline cooldown, unfriend and the two lists.

Moved verbatim out of ``routes/social.py`` (#118); the route keeps the
caller checks (``require_self`` / the session user) and maps
``services.social.errors`` to HTTP statuses.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from db.connection import table
from models import FriendRequestBody
from services.achievement_service import check_achievements
from services.profiles import LIVE_USER_FILTER, get_display_names, live_user_ids
from services.social.errors import Conflict, Forbidden, InvalidRequest, NotFound, RateLimited

# The route's logger name, kept so log filters and caplog keep matching.
logger = logging.getLogger("routes.social")


def _are_friends(user_id: str, other_id: str) -> bool:
    rows = table("friendships").select(
        "friend_id", filters={"user_id": f"eq.{user_id}", "friend_id": f"eq.{other_id}"}
    )
    return bool(rows)


#: How long a declined request blocks the same sender from re-sending (#764).
DECLINE_COOLDOWN = timedelta(days=7)


def _decline_cooldown_ends(responded_at: str | None) -> datetime | None:
    """When the decline cooldown lifts, or None if it already has (or the
    decline carries no timestamp to measure from)."""
    if not responded_at:
        return None
    try:
        declined = datetime.fromisoformat(str(responded_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if declined.tzinfo is None:
        declined = declined.replace(tzinfo=timezone.utc)
    ends = declined + DECLINE_COOLDOWN
    return ends if ends > datetime.now(timezone.utc) else None


def _request_status(request_id: str) -> str | None:
    """Re-read a request's status after losing a conditional write; None if
    the row is gone (cancelled)."""
    rows = table("friend_requests").select("status", filters={"id": f"eq.{request_id}"})
    return rows[0].get("status") if rows else None


def _resolve_pending(request_id: str, status: str) -> list:
    """The one write every friend-request transition goes through (#764):
    pending -> `status`, conditional on the row STILL being pending. Returns
    the updated rows, so an empty list means another transition won."""
    return table("friend_requests").update(
        {"status": status, "responded_at": datetime.now(timezone.utc).isoformat()},
        filters={"id": f"eq.{request_id}", "status": "eq.pending"},
    )


def send_friend_request(body: FriendRequestBody):
    if body.from_user_id == body.to_user_id:
        raise InvalidRequest("You can't friend yourself")
    if _are_friends(body.from_user_id, body.to_user_id):
        raise Conflict("Already friends")
    # Deliberately only the exact (from, to) pair — a pending REVERSE request
    # is left alone rather than auto-accepted or rejected. Mutual pending
    # requests are legal and harmless now that accept_friend_request is
    # idempotent: whichever is accepted first makes the other a no-op that
    # still resolves its row. Auto-accepting here would silently create a
    # friendship from a click that only meant "send a request".
    existing = table("friend_requests").select(
        "id,status,responded_at",
        filters={
            "from_user_id": f"eq.{body.from_user_id}",
            "to_user_id": f"eq.{body.to_user_id}",
        },
    )
    if existing:
        status = existing[0].get("status")
        if status == "pending":
            raise Conflict("Request already pending")
        if status == "declined":
            # #764: a decline holds for DECLINE_COOLDOWN. Re-pending used to be
            # unlimited, so a declined sender could put the request straight
            # back in the recipient's inbox, forever.
            until = _decline_cooldown_ends(existing[0].get("responded_at"))
            if until is not None:
                raise RateLimited(
                    f"They declined recently. You can send another request after {until.date().isoformat()}.",
                )
        # A row for this (from_user_id, to_user_id) pair already exists —
        # declined, or accepted-then-unfriended (remove_friend only deletes
        # the symmetric friendships rows, it deliberately leaves the
        # historical friend_requests row in place). UNIQUE(from_user_id,
        # to_user_id) means a second insert here would 409/500 on the
        # constraint, so reactivate the existing row instead of inserting
        # a duplicate. created_at is re-stamped on purpose: it is the send time
        # of the LIVE request the recipient sees, and the cooldown above (keyed
        # on responded_at) is what bounds re-sends. Conditional on the status
        # we read, so a concurrent transition is a 409 rather than a blind
        # overwrite.
        result = table("friend_requests").update(
            {
                "status": "pending",
                "responded_at": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            filters={"id": f"eq.{existing[0]['id']}", "status": f"eq.{status}"},
        )
        if not result:
            raise Conflict("That request just changed. Try again.")
        return {"request": result[0]}
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
        raise NotFound("Request not found")
    req = rows[0]
    if req["to_user_id"] != user_id:
        raise Forbidden("Not your request to answer")
    return req


def accept_friend_request(request_id: str, user_id: str):
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
    #
    # "Already friends" is the ONLY thing that makes this idempotent, though —
    # NOT "not pending" on its own. Folding the two together
    # (`status != "pending" or _are_friends(...)`) meant accepting a DECLINED
    # request skipped the friendships upsert, still stamped the row
    # `accepted`, and returned {"accepted": True}: a request recorded as
    # accepted with no friendship behind it, and the sender left to work out
    # that they have to send again. A resolved request that produced no
    # friendship is not an accept to replay, it's a stale one to reject.
    if _are_friends(a, b):
        # Resolve a stale pending row, but only a PENDING one (#764): a blind
        # write here could flip a declined row to accepted.
        _resolve_pending(request_id, "accepted")
        return {"accepted": True}
    if req.get("status") != "pending":
        raise Conflict("Request is no longer pending")

    # #764: claim the transition FIRST, conditional on the row still being
    # pending, and only the winner writes the friendship. The old order (write
    # friendships, then blindly stamp `accepted`) let an accept racing a
    # decline or a cancel create a friendship out of a request that was no
    # longer there to accept.
    if not _resolve_pending(request_id, "accepted"):
        if _request_status(request_id) == "accepted":
            # A double-click's twin won the claim and writes the friendship.
            return {"accepted": True}
        raise Conflict("Request is no longer pending")

    try:
        # Symmetric rows: "my friends" stays a plain equality filter. upsert,
        # not insert, so a duplicate pair (mutual requests) cannot 500.
        table("friendships").upsert([
            {"user_id": a, "friend_id": b},
            {"user_id": b, "friend_id": a},
        ], on_conflict="user_id,friend_id")
    except Exception:
        # Hand the claim back so the request stays answerable, rather than
        # recorded as accepted with no friendship behind it.
        table("friend_requests").update(
            {"status": "pending", "responded_at": None},
            filters={"id": f"eq.{request_id}", "status": "eq.accepted"},
        )
        raise

    # Guarded like every other dispatch site in this file (:64, :144, :185).
    # The friendship rows and the request status are already committed above,
    # so a failing badge check must not 500 a request that did succeed — that
    # is exactly what happened while _count_rows selected a nonexistent `id`
    # column off `friendships`.
    try:
        check_achievements(a, "friends_count")
        check_achievements(b, "friends_count")
    except Exception:
        logger.exception(
            "achievement dispatch failed after friend accept from=%s to=%s", a, b,
        )
    return {"accepted": True}


def decline_friend_request(request_id: str, user_id: str):
    req = _load_request(request_id, user_id)
    # #764: only a PENDING request can be declined. The old blind write could
    # flip an `accepted` row to `declined` while the friendship stood.
    status = req.get("status")
    if status == "pending":
        if _resolve_pending(request_id, "declined"):
            return {"declined": True}
        status = _request_status(request_id)
    if status == "declined":
        # Already declined (a double-click's twin won): the same outcome.
        return {"declined": True}
    raise Conflict("Request is no longer pending")


def cancel_friend_request(request_id: str, user_id: str):
    """The sender withdraws a PENDING request (#764). The row is deleted, so
    the pair can be requested again later; a decline cannot be dodged this
    way because only pending rows are cancellable."""
    rows = table("friend_requests").select(
        "id,from_user_id,status", filters={"id": f"eq.{request_id}"}
    )
    if not rows:
        raise NotFound("Request not found")
    if rows[0]["from_user_id"] != user_id:
        raise Forbidden("Not your request to cancel")
    deleted = table("friend_requests").delete({
        "id": f"eq.{request_id}",
        "from_user_id": f"eq.{user_id}",
        "status": "eq.pending",
    })
    if not deleted:
        raise Conflict("Request is no longer pending")
    return {"cancelled": True}


def remove_friend(friend_id: str, user_id: str):
    table("friendships").delete(
        filters={"user_id": f"eq.{user_id}", "friend_id": f"eq.{friend_id}"}
    )
    table("friendships").delete(
        filters={"user_id": f"eq.{friend_id}", "friend_id": f"eq.{user_id}"}
    )
    return {"removed": True}


def list_friend_requests(user_id: str):
    incoming = table("friend_requests").select(
        "id,from_user_id,created_at",
        filters={"to_user_id": f"eq.{user_id}", "status": "eq.pending"},
    ) or []
    outgoing = table("friend_requests").select(
        "id,to_user_id,created_at",
        filters={"from_user_id": f"eq.{user_id}", "status": "eq.pending"},
    ) or []
    ids = [r["from_user_id"] for r in incoming] + [r["to_user_id"] for r in outgoing]
    # A pending request to or from a since-deleted account is not actionable
    # and must not keep naming them (#115).
    live = live_user_ids(ids) if ids else set()
    incoming = [r for r in incoming if r["from_user_id"] in live]
    outgoing = [r for r in outgoing if r["to_user_id"] in live]
    ids = [i for i in ids if i in live]
    names = get_display_names(ids) if ids else {}
    return {
        "incoming": [
            {**r, "name": names.get(r["from_user_id"], "Someone")} for r in incoming
        ],
        "outgoing": [
            {**r, "name": names.get(r["to_user_id"], "Someone")} for r in outgoing
        ],
    }


def list_friends(user_id: str):
    # Self-only for now: a friends list is arguably shareable with other
    # users later (product decision), but the safe default until that's
    # decided is that only the account owner can list their own friends.
    rows = table("friendships").select("friend_id", filters={"user_id": f"eq.{user_id}"})
    ids = [r["friend_id"] for r in rows or []]
    if not ids:
        return {"friends": []}
    users = table("users").select(
        "id,level,total_xp", filters={"id": f"in.({','.join(ids)})", **LIVE_USER_FILTER}
    ) or []
    names = get_display_names([u["id"] for u in users])
    return {"friends": [
        {
            "user_id": u["id"],
            "name": names.get(u["id"], "Someone"),
            "level": u.get("level") or 1,
            "total_xp": u.get("total_xp") or 0,
        }
        for u in users
    ]}
