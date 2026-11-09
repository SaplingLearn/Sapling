"""
Social routes — study rooms, room messages, matching, the student directory
and friends.

The handlers check the caller (``require_self`` / the session user) and call
``services/social/`` (#118), which holds the reads, writes, agent call and
achievement dispatch; ``_social_errors`` maps that package's domain errors to
the status codes these routes always answered.
"""
import logging
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Query, Request

from models import CreateRoomBody, JoinRoomBody, MatchBody, PublicJoinBody, SendMessageBody, EditMessageBody, ToggleReactionBody, LeaveRoomBody, FriendRequestBody
from services.auth_guard import require_self, get_session_user_id
from services.social import (
    Conflict,
    Forbidden,
    InvalidRequest,
    NotFound,
    RateLimited,
    SocialError,
    UpstreamError,
    directory,
    friends,
    matching,
    messages,
    overview,
    rooms,
)

# Moved to services/social/ (#118); re-exported so imports and patches of the
# old names on this module keep working.
from services.social.directory import _LISTABLE_USER_FILTERS, _visible_profile_ids  # noqa: F401  (re-export, #118)
from services.social.friends import (  # noqa: F401  (re-export, #118)
    DECLINE_COOLDOWN,
    _are_friends,
    _decline_cooldown_ends,
    _load_request,
    _request_status,
    _resolve_pending,
)
from services.social.messages import _message_in_room  # noqa: F401  (re-export, #118)
from services.social.rooms import (  # noqa: F401  (re-export, #118)
    _is_banned,
    _live_members,
    _require_member,
    _touch_room,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_ERROR_STATUS = {
    InvalidRequest: 400, Forbidden: 403, NotFound: 404, Conflict: 409,
    RateLimited: 429, UpstreamError: 502,
}


@contextmanager
def _social_errors():
    """Map a ``services.social`` domain error to its HTTP status, same detail."""
    try:
        yield
    except SocialError as e:
        raise HTTPException(status_code=_ERROR_STATUS[type(e)], detail=e.detail)


@router.post("/rooms/create")
def create_room(body: CreateRoomBody, request: Request):
    require_self(body.user_id, request)
    with _social_errors():
        return rooms.create_room(body)


@router.get("/public-rooms")
def list_public_rooms(request: Request, user_id: str = Query(...)):
    """Public rooms (#405): is_public=true rooms, joinable without an invite.
    The select never includes invite_code, so the public listing cannot leak
    the private join path."""
    require_self(user_id, request)
    with _social_errors():
        return rooms.list_public_rooms(user_id)


@router.post("/public-rooms/{room_id}/join")
def join_public_room(room_id: str, body: PublicJoinBody, request: Request):
    require_self(body.user_id, request)
    with _social_errors():
        return rooms.join_public_room(room_id, body)


@router.post("/rooms/join")
def join_room(body: JoinRoomBody, request: Request):
    require_self(body.user_id, request)
    with _social_errors():
        return rooms.join_room(body)


@router.get("/rooms/{user_id}")
def get_user_rooms(user_id: str, request: Request):
    require_self(user_id, request)
    with _social_errors():
        return rooms.get_user_rooms(user_id)


@router.get("/rooms/{room_id}/overview")
def room_overview(room_id: str, request: Request):
    viewer_id = get_session_user_id(request)
    with _social_errors():
        return overview.room_overview(room_id, viewer_id)


@router.get("/rooms/{room_id}/activity")
def room_activity(room_id: str, request: Request):
    viewer_id = get_session_user_id(request)
    with _social_errors():
        return overview.room_activity(room_id, viewer_id)


@router.post("/rooms/{room_id}/match")
def match_partners(room_id: str, body: MatchBody, request: Request):
    require_self(body.user_id, request)
    with _social_errors():
        return matching.match_partners(room_id, body)


@router.post("/school-match")
def school_match(body: MatchBody, request: Request):
    """Match the requesting user against students at their school who share
    none of their study rooms (room-mates are what /rooms/{id}/match is for).

    Candidates follow the same visibility rules as the /students directory
    (#115): same school only (``academics.school_peer_user_ids``; no school →
    no matches, fail closed), ``profile_visibility='private'`` opts out, and
    only listable accounts (no stubs, pending or soft-deleted users). The
    payload carries per-concept mastery comparisons, so a looser scope here
    would expose more than the directory itself does.
    """
    require_self(body.user_id, request)
    with _social_errors():
        return matching.school_match(body)


@router.post("/rooms/{room_id}/leave")
def leave_room(room_id: str, body: LeaveRoomBody, request: Request):
    require_self(body.user_id, request)
    with _social_errors():
        return rooms.leave_room(room_id, body)


@router.delete("/rooms/{room_id}/members/{member_id}")
def kick_member(room_id: str, member_id: str, request: Request, requester_id: str = Query(...)):
    require_self(requester_id, request)
    with _social_errors():
        return rooms.kick_member(room_id, member_id, requester_id)


@router.get("/rooms/{room_id}/messages")
def get_room_messages(room_id: str, request: Request, before: str | None = None, limit: int = 50):
    viewer_id = get_session_user_id(request)
    with _social_errors():
        return messages.get_room_messages(room_id, viewer_id, before, limit)


@router.post("/rooms/{room_id}/messages")
def send_room_message(room_id: str, body: SendMessageBody, request: Request):
    require_self(body.user_id, request)
    with _social_errors():
        return messages.send_room_message(room_id, body)


@router.delete("/rooms/{room_id}/messages/{message_id}")
def delete_room_message(room_id: str, message_id: str, request: Request, user_id: str = Query(...)):
    require_self(user_id, request)
    with _social_errors():
        return messages.delete_room_message(room_id, message_id, user_id)


@router.patch("/rooms/{room_id}/messages/{message_id}")
def edit_room_message(room_id: str, message_id: str, body: EditMessageBody, request: Request):
    require_self(body.user_id, request)
    with _social_errors():
        return messages.edit_room_message(room_id, message_id, body)


@router.post("/rooms/{room_id}/messages/{message_id}/reactions")
def toggle_reaction(room_id: str, message_id: str, body: ToggleReactionBody, request: Request):
    require_self(body.user_id, request)
    with _social_errors():
        return messages.toggle_reaction(room_id, message_id, body)


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
    with _social_errors():
        return directory.get_students(user_id)


@router.post("/friends/request")
def send_friend_request(body: FriendRequestBody, request: Request):
    require_self(body.from_user_id, request)
    with _social_errors():
        return friends.send_friend_request(body)


@router.post("/friends/requests/{request_id}/accept")
def accept_friend_request(request_id: str, user_id: str, request: Request):
    require_self(user_id, request)
    with _social_errors():
        return friends.accept_friend_request(request_id, user_id)


@router.post("/friends/requests/{request_id}/decline")
def decline_friend_request(request_id: str, user_id: str, request: Request):
    require_self(user_id, request)
    with _social_errors():
        return friends.decline_friend_request(request_id, user_id)


@router.delete("/friends/requests/{request_id}")
def cancel_friend_request(request_id: str, user_id: str, request: Request):
    """The sender withdraws a PENDING request (#764). The row is deleted, so
    the pair can be requested again later; a decline cannot be dodged this
    way because only pending rows are cancellable."""
    require_self(user_id, request)
    with _social_errors():
        return friends.cancel_friend_request(request_id, user_id)


@router.delete("/friends/{friend_id}")
def remove_friend(friend_id: str, user_id: str, request: Request):
    require_self(user_id, request)
    with _social_errors():
        return friends.remove_friend(friend_id, user_id)


@router.get("/friends/requests")
def list_friend_requests(user_id: str, request: Request):
    require_self(user_id, request)
    with _social_errors():
        return friends.list_friend_requests(user_id)


@router.get("/friends/{user_id}")
def list_friends(user_id: str, request: Request):
    require_self(user_id, request)
    with _social_errors():
        return friends.list_friends(user_id)
