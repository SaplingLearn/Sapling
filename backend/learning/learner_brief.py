"""The learner brief (research N9 "Context builder"; spec §3.4, §13 A13/A19).

A bounded (≤ LEARNER_BRIEF_MAX_CHARS) description of where this student
stands in the course, built from structured sources only — never from
`messages`: the goal (exam proximity, A13 — no syllabus-week resolver
exists), the weakest in-play concepts (decayed `p_known`, band, FSRS due
date), the last LEARNER_BRIEF_LAST_CLOSES session closes (summary + plan) and
the open misconception keys. A trusted header line, then the body inside the
untrusted-content envelope: close summaries are model text written from
student transcripts and concept names can come from student documents, so
the body's control tags are neutralised too (spec §13 A51).

Built ONCE per session and stored encrypted in `sessions.loop_brief` (A19):
at `/plan/approve`, or on the first loop turn of a session that has no plan.
The loop serves it as the first history message, part of the stable prefix;
it is never rebuilt within a session and never lives in `loop_state` or
`close_json`. `build_brief` never raises (a failed section is omitted with a
WARNING naming the exception class); `store_brief` lets DB errors propagate
to its callers, which catch them.
"""

from __future__ import annotations

import logging

from db.connection import table
from learning.bkt import band
from learning.learner_state import read_states
from learning.params import (
    BKT_L0,
    LEARNER_BRIEF_LAST_CLOSES,
    LEARNER_BRIEF_MAX_CHARS,
    LEARNER_BRIEF_MAX_MISCONCEPTIONS,
    LEARNER_BRIEF_TOP_STATES,
)
from learning.session_close import ensure_session_row
from services.academics import course_offering_ids
from services.encryption import decrypt_json_column, encrypt_if_present
from services.exam_proximity import days_until_next_exam
from services.prompt_safety import (
    neutralise_control_tags,
    untrusted_envelope_overhead,
    wrap_untrusted,
)

logger = logging.getLogger("sapling.learning.learner_brief")

BRIEF_HEADER = "LEARNER BRIEF (this student's prior sessions and current estimates):\n"
_SOURCE = "learner brief"
_ELLIPSIS = "…"


def _goal_section(user_id: str, course_id: str | None) -> str:
    days = days_until_next_exam(user_id, course_id)
    if days is None:
        return ""
    if days == 0:
        return "goal: exam today"
    return f"goal: next exam in {days} day{'' if days == 1 else 's'}"


def _states_section(user_id: str, node_ids: list[str]) -> str:
    ids = list(dict.fromkeys(n for n in node_ids or [] if n))
    if not ids:
        return ""
    states = read_states(user_id, ids)
    # A node with no learner_state row is at the BKT prior (learner_state.read_state).
    ranked = sorted(ids, key=lambda n: states[n].p_known if n in states else BKT_L0)
    top = ranked[:LEARNER_BRIEF_TOP_STATES]
    rows = table("graph_nodes").select(
        "id,concept_name",
        filters={"user_id": f"eq.{user_id}", "id": f"in.({','.join(top)})"},
    )
    names = {r["id"]: r.get("concept_name") for r in rows or [] if r.get("id")}
    lines = []
    for node in top:
        if not names.get(node):
            continue  # never an id alone: the model needs the name
        state = states.get(node)
        p = state.p_known if state is not None else BKT_L0
        due_at = state.fsrs_due_at if state is not None else None
        due = due_at.isoformat()[:10] if due_at else "none"
        lines.append(f"- {names[node]}: p={p:.2f} band={band(p)} due={due}")
    return "weakest concepts:\n" + "\n".join(lines) if lines else ""


def _read_closes(user_id: str, course_id: str | None) -> list[dict]:
    """The last closes of this course, newest first, decrypted. Sessions key
    on the offering stamped by `resolve_offering`, so the course's offerings
    come from `course_offering_ids` (not the enrollment-derived
    `user_offering_ids_for_course`, which diverges at a term rollover);
    ownership is the `user_id` filter."""
    offerings = course_offering_ids(course_id) if course_id else []
    if offerings is None:
        raise LookupError("course offerings unknown")
    if not offerings:
        return []
    rows = table("sessions").select(
        "id,started_at,close_json,close_phase",
        filters={
            "user_id": f"eq.{user_id}",
            "offering_id": f"in.({','.join(offerings)})",
            "close_json": "not.is.null",
        },
        order="started_at.desc",
        limit=LEARNER_BRIEF_LAST_CLOSES,
    )
    closes = []
    for row in rows or []:
        try:
            close = decrypt_json_column(row.get("close_json"))
        except Exception as exc:
            logger.warning(
                "learner_brief: close %s skipped (%s)", row.get("id"), type(exc).__name__
            )
            continue
        if isinstance(close, dict):
            closes.append(close)
    return closes


def _closes_section(closes: list[dict]) -> str:
    lines = []
    for close in closes:
        summary = (close.get("summary") or "").strip()
        if not summary:
            continue
        plan = (close.get("if_then") or "").strip()
        lines.append(f"- {summary}" + (f" | plan: {plan}" if plan else ""))
    return "recent sessions:\n" + "\n".join(lines) if lines else ""


def _open_misconception_keys(
    user_id: str, node_ids_in_play: list[str], closes: list[dict]
) -> list[str]:
    """PKG-10 repoints this hook at the `misconceptions` table. Until then it
    reads only the closes: the union of their open keys, order preserved."""
    keys: list[str] = []
    for close in closes:
        keys += [k for k in close.get("misconceptions") or [] if isinstance(k, str) and k]
    return list(dict.fromkeys(keys))


def _section(name: str, build) -> str:
    try:
        return build() or ""
    except Exception as exc:
        logger.warning("learner_brief: %s section skipped (%s)", name, type(exc).__name__)
        return ""


def _fit(sections: list[str], budget: int) -> str:
    """Sections joined by newlines while they fit; the first that does not is
    cut to the remaining room with an ellipsis and every later one dropped."""
    body = ""
    for sec in sections:
        candidate = f"{body}\n{sec}" if body else sec
        if len(candidate) <= budget:
            body = candidate
            continue
        room = budget - len(body) - (1 if body else 0) - len(_ELLIPSIS)
        if room > 0:
            body = (f"{body}\n" if body else "") + sec[:room] + _ELLIPSIS
        break
    return body


def build_brief(user_id: str, course_id: str | None, node_ids_in_play: list[str]) -> str:
    """The brief, or "" when there is nothing to say. Never raises; for ANY
    input `len(result) <= LEARNER_BRIEF_MAX_CHARS`."""
    closes: list[dict] = []

    def closes_block() -> str:
        closes.extend(_read_closes(user_id, course_id))
        return _closes_section(closes)

    def keys_block() -> str:
        keys = _open_misconception_keys(user_id, node_ids_in_play, closes)
        keys = keys[:LEARNER_BRIEF_MAX_MISCONCEPTIONS]
        return "open misconceptions: " + ", ".join(keys) if keys else ""

    sections = [
        _section("goal", lambda: _goal_section(user_id, course_id)),
        _section("states", lambda: _states_section(user_id, node_ids_in_play)),
        _section("closes", closes_block),
        _section("misconceptions", keys_block),
    ]
    sections = [neutralise_control_tags(s) for s in sections if s]
    if not sections:
        return ""
    budget = LEARNER_BRIEF_MAX_CHARS - len(BRIEF_HEADER) - untrusted_envelope_overhead(_SOURCE)
    while budget > 0:
        brief = BRIEF_HEADER + wrap_untrusted(_fit(sections, budget), source=_SOURCE)
        excess = len(brief) - LEARNER_BRIEF_MAX_CHARS
        if excess <= 0:
            return brief
        budget -= excess  # delimiter neutralisation grew the body: re-cut tighter
    return ""


def store_brief(
    session_id: str,
    user_id: str,
    course_id: str | None,
    node_ids: list[str],
    *,
    row_defaults: dict | None = None,
) -> str:
    """Build the brief and store it encrypted on the session (A19), through
    the A11 insert-if-missing helper. An empty brief is written too (a
    non-null ciphertext), so `loop_brief IS NULL` means exactly "not built
    yet". A missing row with no defaults writes nothing (the next loop turn
    builds it). Returns the brief. DB errors propagate."""
    brief = build_brief(user_id, course_id, node_ids)
    if not ensure_session_row(session_id, user_id, row_defaults):
        logger.warning("learner_brief: sessions row %s missing; brief not stored", session_id)
        return brief
    table("sessions").update(
        {"loop_brief": encrypt_if_present(brief)}, filters={"id": f"eq.{session_id}"}
    )
    return brief
