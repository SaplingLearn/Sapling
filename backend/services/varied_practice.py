"""Varied practice on the serving side (learning-loop spec §13 A140, A141).

The two dials of adaptive practice, as reads for the loop's pickers:

- A140, cue familiarity (flag `varied_isomorphs`): `familiarity_for` ranks a
  concept's items by how familiar their surface is to the student
  (learning/surface.py) — a tie-break every picker applies after its own
  rules and A129's quality order (checks.select_item's `familiarity`).
- A141, ideas combined (flag `multi_concept_items`): `multi_concept_pick`
  chooses the multi-concept item an in-session check on a concept may pose
  instead of a single-concept one (learning/multi_concept.py's gate and dial).

Both flags are read per pick, for the student being served. Everything here
fails toward today's behaviour: a failed read gives no familiarity (the
picker's plain order) and no multi-concept item (the single-concept pick).
`note_posed` emits `learn.multi_concept_served` once a multi-concept item is
posed (the admin report's "served").
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Sequence

from learning.checks import CheckItem, is_servable, select_item
from learning.learner_state import read_states
from learning.multi_concept import (
    ComponentState,
    components_of,
    dial_open,
    gate_open,
    is_multi_concept,
)
from learning.params import CHECK_ITEM_DIFFICULTIES
from learning.surface import familiarity_by_hash
from services.events_service import log_event
from services.feature_flags import flag_on

logger = logging.getLogger("sapling.services.varied_practice")

VARIED_FLAG = "varied_isomorphs"
MULTI_CONCEPT_FLAG = "multi_concept_items"
SERVED_EVENT = "learn.multi_concept_served"


def varied_on(user_id: str | None) -> bool:
    """`varied_isomorphs` for this student (no student: off; fails closed)."""
    return bool(user_id) and flag_on(VARIED_FLAG, user_id)


def multi_concept_on(user_id: str | None) -> bool:
    """`multi_concept_items` for this student (no student: off; fails closed)."""
    return bool(user_id) and flag_on(MULTI_CONCEPT_FLAG, user_id)


def familiarity_for(
    course_id: str | None, concept_key: str | None, exposed: Collection[str]
) -> dict[str, int] | None:
    """question_hash → surface familiarity over one concept's bank, for a
    student who has met the items in `exposed` (seen, revealed, reported,
    posed this session or served today). None when the concept is unknown or
    the read failed: the picker keeps its plain order."""
    if not course_id or not concept_key:
        return None
    from services.check_item_service import concept_surfaces

    try:
        surfaces = concept_surfaces(course_id, concept_key)
    except Exception:
        logger.warning(
            "varied practice: surfaces unread (course=%s); plain order", course_id, exc_info=True
        )
        return None
    return familiarity_by_hash(surfaces, set(exposed))


def _component_states(user_id: str, course_id: str, keys: Collection[str]) -> dict[str, ComponentState]:
    """The student's decayed state per component concept key (a key the
    student has no node for is absent: not proficient)."""
    from db.connection import table
    from services.graph_service import _normalize_concept

    rows = table("graph_nodes").select(
        "id,concept_name",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    )
    nodes = {}
    for row in rows or []:
        key = _normalize_concept(row.get("concept_name") or "")
        if key in keys and row.get("id"):
            nodes.setdefault(key, row["id"])
    if not nodes:
        return {}
    states = read_states(user_id, list(nodes.values()))
    out = {}
    for key, node_id in nodes.items():
        st = states.get(node_id)
        if st is not None:
            out[key] = ComponentState(st.p_known, int(st.n_strong_unassisted or 0))
    return out


def multi_concept_pick(
    user_id: str,
    course_id: str,
    state: dict,
    node_id: str,
    apex_key: str,
    *,
    target: int,
    formats: Sequence[str],
    excluded: Collection[str],
) -> CheckItem | None:
    """The multi-concept item the concept's next in-session check poses, or
    None (the single-concept pick then runs). Spec §13 A141:

    - the dial (learning.multi_concept.dial_open): not in a goal session; only
      after a check graded on the concept this session; only while its target
      difficulty is the top one (A122: no easier step pending); at most
      MULTI_CONCEPT_PER_CONCEPT_SESSION a session;
    - the items: the course's multi-concept items whose apex is this concept,
      servable (A34; no hold, A124/A123), never one the student has met
      (`excluded`: seen, revealed, reported, posed this session) — and never
      a post-test reserve: no reserve is ever computed over them;
    - the gate (learning.multi_concept.gate_open): every component at least
      proficient for this student;
    - the choice: the fewest components first (two ideas before three), then
      the session's format rotation, then select_item's own order.
    A failed read gives None."""
    at_top = target == CHECK_ITEM_DIFFICULTIES[-1]
    if not dial_open(state.get("steps") or {}, node_id, at_top=at_top, goal=bool(state.get("goal"))):
        return None
    from services.check_item_service import multi_concept_items

    try:
        combos = [
            c
            for c in multi_concept_items(course_id, apex_key)
            if c.question_hash not in excluded and is_servable(c)
        ]
        if not combos:
            return None
        keys = {k for c in combos for k in components_of(c.concept_key) or ()}
        states = _component_states(user_id, course_id, keys)
    except Exception:
        logger.warning(
            "varied practice: multi-concept read failed (course=%s); single-concept pick",
            course_id,
            exc_info=True,
        )
        return None
    eligible = [c for c in combos if gate_open(states, components_of(c.concept_key) or ())]
    for size in sorted({len(components_of(c.concept_key)) for c in eligible}):
        pool = [c for c in eligible if len(components_of(c.concept_key)) == size]
        for fmt in formats:
            item = select_item(pool, format=fmt, difficulty=target, exclude_hashes=excluded)
            if item is not None:
                return item
    return None


def note_posed(user_id: str, session_id: str | None, item) -> None:
    """`learn.multi_concept_served` once a multi-concept item is posed (after
    the save that posed it): ids and counts only. Never raises."""
    if item is None or not is_multi_concept(item):
        return
    try:
        log_event(
            SERVED_EVENT,
            category="usage",
            user_id=user_id,
            payload={
                "course_id": item.course_id,
                "question_hash": item.question_hash,
                "components": len(components_of(item.concept_key) or ()),
                "format": item.format,
                "session_id": session_id,
            },
        )
    except Exception:
        logger.warning("varied practice: served event not logged", exc_info=True)
