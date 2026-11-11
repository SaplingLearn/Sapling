"""What the loop knows about the student on a concept: the item's graph node,
the BKT band, prerequisites, the learner view the policy reads, the genuine
attempt rule and the band ceiling.
"""
from __future__ import annotations

import dataclasses
import config
from db.connection import table
from learning import gates, policy
from learning.bkt import band as bkt_band
from learning.multi_concept import evidence_key
from learning.ladder import Rung
from learning.learner_state import LearnerState, read_states
from learning.params import BAND_CONTROL_CEILING_STEP, BKT_L0, EDGE_PREREQ_SOURCE_IS_PREREQ
from learning.policy import LearnerView, StepState
from services.graph_service import _normalize_concept, _prerequisite_edges


# ── Learner state, band, ceiling ───────────────────────────────────────────


def _node_for_item(user_id: str, item) -> str | None:
    """The student's graph node for a course-asset item (A2): the user's
    `graph_nodes` row in the item's course whose normalised concept name is the
    item's `concept_key` — for a multi-concept item (spec §13 A141) its APEX
    concept's, where its evidence goes. None when the student has never met
    the concept."""
    key = evidence_key(item)
    rows = (
        table("graph_nodes").select(
            "id,concept_name",
            filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{item.course_id}"},
        )
        or []
    )
    for row in rows:
        if _normalize_concept(row.get("concept_name") or "") == key:
            return row.get("id")
    return None


def _learner_state(user_id: str, node_id: str | None) -> LearnerState | None:
    if not node_id:
        return None
    return read_states(user_id, [node_id]).get(node_id)


def _band_of(state: LearnerState | None) -> tuple[str, float]:
    p = state.p_known if state is not None else BKT_L0
    return bkt_band(p), p


def _band_for(user_id: str, node_id: str | None) -> tuple[str, float]:
    """(band, p_known) of a node — BKT_L0 when there is no node or no row."""
    return _band_of(_learner_state(user_id, node_id))


def _prerequisites(user_id: str, node_id: str) -> list[policy.Prerequisite]:
    """The node's prerequisite parents with their decayed p_known (BKT_L0 for a
    parent with no learner_state row); [] when it has none. Parents come from
    the read helper PKG-03's propagation uses (graph_service._prerequisite_edges),
    with the same EDGE_PREREQ_SOURCE_IS_PREREQ direction."""
    parents: list[str] = []
    for src, tgt in _prerequisite_edges(user_id, node_id):
        prereq, dependent = (src, tgt) if EDGE_PREREQ_SOURCE_IS_PREREQ else (tgt, src)
        if dependent == node_id and prereq != node_id and prereq not in parents:
            parents.append(prereq)
    if not parents:
        return []
    states = read_states(user_id, parents)
    return [
        policy.Prerequisite(p, states[p].p_known if p in states else BKT_L0) for p in parents
    ]


def _prereq_proficient(user_id: str, node_id: str) -> bool:
    """The ceiling's prerequisite input (spec §3.3): True only when the status is
    PROFICIENT — every prerequisite parent in the profic band (p_known ≥
    BAND_DEVELOP_MAX). A node with NO prerequisite edge is UNKNOWN, never
    proficient (spec §13 A122): it takes the "prerequisite not known" row, so a
    novice there gets the worked example first."""
    status = policy.prerequisite_status(_prerequisites(user_id, node_id))
    return status is policy.PrerequisiteStatus.PROFICIENT


def _learner_view(state: LearnerState | None, *, band: str, prereq_proficient: bool) -> LearnerView:
    """PKG-06's typed learner input; LearnerState's own defaults stand in for a
    node with no row (the BKT prior, no opportunities)."""
    st = state or LearnerState(user_id="", node_id="")
    return LearnerView(
        p_known=st.p_known,
        band=band,
        prereq_proficient=prereq_proficient,
        unassisted_next=st.unassisted_next,
        opps=st.opps,
        streak_unassisted=st.streak_unassisted,
        n_strong_unassisted=st.n_strong_unassisted,
    )


def _genuine(text: str, independent_s: float, band: str, variant: str = "A") -> bool:
    """Spec §3.3 genuine attempt, for hint unlocking and the shown-work floor
    only (never a grading gate, A16). `matched_non_attempt` is
    `vetoes_attempt` — never `matches_non_attempt` (HANDOFF-06; spec §13 A120:
    a phrase or plea vetoes only a message with nothing else in it)."""
    return gates.is_genuine_attempt(
        len((text or "").strip()),
        False,
        gates.vetoes_attempt(text or ""),
        independent_s,
        band,
        time_scale=config.LEARNING_GATE_TIME_SCALE,
        variant=variant,  # PKG-14: the concept's within-student arm (learning.arms.variant_for)
    )


def _ceiling_for(
    *,
    step: StepState,
    learner: LearnerView,
    message: str,
    independent_s: float,
    variant: str = "A",
    teach_attempt: bool = False,
    band_delta: int = 0,
) -> tuple[Rung, policy.CeilingReason]:
    """policy.ceiling_with_reason on typed state only (invariant 4). The shown-work
    floor applies when the step already records shown work or this message is a
    genuine attempt; exam mode is the step's own flag (False until PKG-08).
    `band_delta`: band control's ceiling clause for the concept (spec §13 A122,
    `_band_ceiling_delta`)."""
    showed = step.showed_work or _genuine(message, independent_s, learner.band, variant)
    raise_ = {"teach_attempt": True} if teach_attempt else {}  # A85; typed state only
    if band_delta:
        raise_["band_delta"] = band_delta
    return policy.ceiling_with_reason(learner, dataclasses.replace(step, showed_work=showed), **raise_)


#: loop_state key (spec §13 A122): node id → band control's ceiling delta for
#: that concept this session (−1 after HARDER, +1 after EASIER_CHECK_PREREQS;
#: set when a verdict's feedback turn is served, held through HOLD)
_BAND_CEILING = "band_ceiling"


def _band_ceiling_delta(state: dict, node_id: str | None) -> int:
    """The concept's band-control ceiling delta in this session (0 when none,
    or for a malformed stored value: no adjustment is ever invented)."""
    deltas = state.get(_BAND_CEILING) if node_id else None
    delta = deltas.get(node_id) if isinstance(deltas, dict) else None
    if type(delta) is int and delta in (
        -BAND_CONTROL_CEILING_STEP,
        BAND_CONTROL_CEILING_STEP,
    ):
        return delta
    return 0


def _failed_on_concept(state: dict, node_id: str | None) -> int:
    """Failed genuine attempts this session on the concept's items (PKG-06's
    per-step `attempts`), summed across its isomorphs."""
    if not node_id:
        return 0
    return sum(
        int(entry.get("attempts") or 0)
        for entry in (state.get("steps") or {}).values()
        if isinstance(entry, dict) and entry.get("node_id") == node_id
    )


def _seconds_since(t: float | None, now: float) -> float:
    return max(0.0, now - t) if t else 0.0


# ── Item activation and the current concept (spec §9, §13 A27) ─────────────


def _concept_key_for_node(user_id: str, node_id: str) -> str | None:
    """The A2 course key of the student's node — the inverse of _node_for_item.
    One `graph_nodes` read by id, scoped to the student."""
    rows = (
        table("graph_nodes").select(
            "concept_name", filters={"id": f"eq.{node_id}", "user_id": f"eq.{user_id}"}, limit=1
        )
        or []
    )
    return _normalize_concept(rows[0].get("concept_name") or "") if rows else None
