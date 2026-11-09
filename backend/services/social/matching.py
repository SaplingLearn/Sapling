"""
backend/services/social/matching.py

Study-partner matching: within a room (members only, #764) and across
the viewer's school (directory visibility rules, #115).

Moved verbatim out of ``routes/social.py`` (#118); the route keeps the
caller checks (``require_self`` / the session user) and maps
``services.social.errors`` to HTTP statuses.
"""
from __future__ import annotations

from db.connection import table
from services import academics
from services.graph_service import get_graph
from services.matching_service import find_study_matches
from services.profiles import get_display_name, get_display_names
from services.social.directory import _LISTABLE_USER_FILTERS, _visible_profile_ids
from services.social.errors import UpstreamError
from services.social.rooms import _live_members, _require_member
from models import MatchBody


def match_partners(room_id: str, body: MatchBody):
    # Members' graphs are room-private (#764): the same gate as the overview.
    _require_member(room_id, body.user_id)
    member_id_rows = table("room_members").select("user_id", filters={"room_id": f"eq.{room_id}"})
    member_ids = _live_members(member_id_rows)

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
        raise UpstreamError(f"Gemini error: {e}")
    return {"matches": matches}


def school_match(body: MatchBody):
    """Match the requesting user against students at their school who share
    none of their study rooms (room-mates are what /rooms/{id}/match is for).

    Candidates follow the same visibility rules as the /students directory
    (#115): same school only (``academics.school_peer_user_ids``; no school →
    no matches, fail closed), ``profile_visibility='private'`` opts out, and
    only listable accounts (no stubs, pending or soft-deleted users). The
    payload carries per-concept mastery comparisons, so a looser scope here
    would expose more than the directory itself does.
    """
    peer_ids = academics.school_peer_user_ids(body.user_id)

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

    candidate_ids = _visible_profile_ids(set(peer_ids) - excluded_ids)
    school_users = table("users").select(
        "id",
        filters={"id": f"in.({','.join(candidate_ids)})", **_LISTABLE_USER_FILTERS},
    ) if candidate_ids else []

    # Names live on user_profiles (0024); resolve in bulk and decrypt.
    school_ids = [u["id"] for u in school_users or []]
    name_map = get_display_names(school_ids) if school_ids else {}
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
        raise UpstreamError(f"Matching error: {e}")

    return {"matches": matches}
