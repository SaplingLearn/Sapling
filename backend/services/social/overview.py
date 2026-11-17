"""
backend/services/social/overview.py

A room's overview (members, their graphs, the cached AI group summary)
and its activity feed. Both are member-only.

Moved verbatim out of ``routes/social.py`` (#118); the route keeps the
caller checks (``require_self`` / the session user) and maps
``services.social.errors`` to HTTP statuses.
"""
from __future__ import annotations

import json
import logging
import re

from agents._run import run_agent_sync
from agents.deps import SaplingDeps
from agents.social_summary import social_summary_agent
from agents.usage import record_agent_usage
from db.connection import table
from services.graph_service import get_graph
from services.llm_budget import budget_error_in
from services.profiles import get_display_names, live_user_ids
from services.prompt_safety import wrap_untrusted
from services.request_context import current_request_id
from services.social.errors import NotFound
from services.social.rooms import _live_members, _require_member
from services.social_cache_service import get_cached_summary, save_summary

# The route's logger name, kept so log filters and caplog keep matching.
logger = logging.getLogger("routes.social")


def room_overview(room_id: str, viewer_id: str):
    _require_member(room_id, viewer_id)

    room_rows = table("rooms").select(
        "id,name,topic,course,owner_id,created_by,invite_code,created_at,updated_at,is_public",
        filters={"id": f"eq.{room_id}"},
    )
    if not room_rows:
        raise NotFound("Room not found")
    room = room_rows[0]

    member_id_rows = table("room_members").select("user_id", filters={"room_id": f"eq.{room_id}"})
    member_ids = _live_members(member_id_rows)

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

    # M9: the model never sees a member's name. Each member is "Member N"
    # in the prompt (and in the cached summary); the names go back in, in
    # code, when the summary is served. Concept names are graph text the
    # members wrote, so they reach the model inside the untrusted envelope.
    # The cache key carries user id -> label, so a cached summary's "Member
    # N" always maps back to the member it was written about.
    labels: dict[str, str] = {}
    prompt_lines: list[str] = []
    member_summaries: list[str] = []  # the cache key, never sent to the model
    for i, m in enumerate(members, 1):
        label = f"Member {i}"
        labels[label] = m["name"]
        nodes = m["graph"]["nodes"]
        mastered = [n["concept_name"] for n in nodes if n["mastery_tier"] == "mastered"]
        struggling = [n["concept_name"] for n in nodes if n["mastery_tier"] == "struggling"]
        line = (
            f"{label}: mastered {json.dumps(mastered, ensure_ascii=False)}, "
            f"struggling with {json.dumps(struggling, ensure_ascii=False)}"
        )
        prompt_lines.append(line)
        member_summaries.append(f"{m['user_id']}|{line}")

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
                "Summarize this study group's collective knowledge. Members are "
                "labelled Member 1 to Member " + str(len(prompt_lines)) + "; refer "
                "to them only by those labels.\n"
                + wrap_untrusted("\n".join(prompt_lines), source=MEMBER_CONCEPTS_SOURCE)
            )
            result = record_agent_usage(
                run_agent_sync(social_summary_agent.run(user_message, deps=deps)),
                feature="social", task="social_summary",
            )
            ai_summary = result.output.summary
            save_summary(room_id, member_summaries, ai_summary)
        except Exception as e:
            budget = budget_error_in(e)  # #838: say the daily budget refused it (not cached)
            if budget is None:
                logger.warning("room summary generation failed: %s", type(e).__name__)
            ai_summary = budget.detail if budget is not None else (
                "This study group has complementary strengths across multiple subjects.")

    return {"room": room, "members": members, "ai_summary": name_members(ai_summary, labels)}


#: Envelope label on the members' concept lists. A trusted literal.
MEMBER_CONCEPTS_SOURCE = "study group members' concept names"

_MEMBER_LABEL = re.compile(r"\bMember (\d+)\b")


def name_members(summary: str, labels: dict[str, str]) -> str:
    """Put members' display names back in place of the "Member N" labels the
    model wrote. A label with no member (or no name) is left as written."""
    if not summary or not labels:
        return summary

    def _name(match: re.Match) -> str:
        return labels.get(match.group(0)) or match.group(0)

    return _MEMBER_LABEL.sub(_name, summary)


def room_activity(room_id: str, viewer_id: str):
    _require_member(room_id, viewer_id)

    activity_rows = table("room_activity").select(
        "id,room_id,user_id,activity_type,concept_name,detail,created_at",
        filters={"room_id": f"eq.{room_id}"},
        order="created_at.desc",
        limit=20,
    )

    live = live_user_ids([a["user_id"] for a in activity_rows])  # #832: drop deleted students
    activity_rows = [a for a in activity_rows if a["user_id"] in live]
    user_name_map = get_display_names(sorted(live)) if live else {}

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
