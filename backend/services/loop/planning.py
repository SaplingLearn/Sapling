"""Goal and plan state shared by the probe, plan and teach paths: the goal's
scope and version, the probe document and its items, the plan read and the
goal's practice pool (spec §13 A143-A146).
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Callable
from services.loop.errors import HTTPException
import config
from db.connection import page_all, table
from learning import planner
from learning import grade_checkpoint
from learning import prequestion as prequestion_rules
from learning import probe as probe_policy
from learning.checks import CheckItem, is_servable, posttest_reserves, serve_quality
from learning.checks import unsourced as item_unsourced
from learning.evidence import PREREQ_RELATIONSHIP_TYPE, PlanningPersistenceUnavailable
from learning.planning_history import read_planning_history
from learning.fsrs import budget_select, order_due
from learning.goals import (
    public_goal,
    goal_version,
    attempted_nodes,
    planning_observations,
    scope_signature,
    progress as goal_progress,
)
from learning.posttest_store import posttest_anchors
from learning.learner_state import read_states
from learning.loop_state_store import reported_hashes, revealed_hashes, seen_hashes
from learning.params import (
    BKT_L0,
    BKT_PROFICIENT,
    CHECK_ITEM_FORMATS,
    EDGE_PREREQ_SOURCE_IS_PREREQ,
    LOOP_GRADING_CLAIM_STALE_S,
    REVIEW_DAILY_BUDGET_MIN,
    REVIEW_SECONDS_PER_CHECK,
)
from services import events_service
from services.check_item_service import (
    course_has_items,
    drafting_pending,
    items_for_concepts,
    list_items,
)
from services.graph_service import _normalize_concept
from services.prompt_safety import neutralise_control_tags, wrap_untrusted
from services.request_limits import check_rate_limit

from services.loop.state import (
    _loop_phase,
    _now_s,
    _refuse_while_closing,
    _require_teaching,
    _StateConflict,
    _update_loop_state,
)
from services.loop.history import _brief_message
from services.loop.learner import _concept_key_for_node

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


def _practice_pool(user_id: str, course_id: str, node_id: str, excluded: set[str]) -> tuple[list, set[str]]:
    """The same eligible bank for planning and actual check activation.

    A probe's practice reserve is eligible here; the delayed post-test
    reserves (both, A126) are not. Difficulty is not an availability filter:
    selection uses the nearest difficulty and rotates through all supported
    check formats. Failed reads propagate, never masquerade as an empty bank.
    """
    key = _concept_key_for_node(user_id, node_id)
    if not key:
        return [], excluded
    items = list_items(course_id, key)
    return items, excluded | posttest_reserves(items)


def _goal_practice_unavailable(user_id: str, course_id: str, state: dict, node_ids) -> set[str]:
    """Read-only, owner-scoped goal preflight. A read outage is not depletion."""
    if not node_ids:
        return set()
    try:
        excluded = (
            seen_hashes(user_id)
            | revealed_hashes(user_id)
            | reported_hashes(user_id)
            | set(state.get("steps") or {})
            | prequestion_rules.session_hashes(state)  # spec §13 A138, as activation
        )
        unavailable = set()
        for node in node_ids:
            items, excluded_for_node = _practice_pool(user_id, course_id, node, excluded)
            if not any(item.question_hash not in excluded_for_node and item.format in CHECK_ITEM_FORMATS
                       and is_servable(item) for item in items):
                unavailable.add(node)
        return unavailable
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Practice availability unavailable; retry") from exc


# ── Probe and plan (PKG-08; spec §3.3 probe row, §3.4, §9; A16, A20, A23, A27, A33, A34) ──
#
# The session document's top-level `phase` is PKG-08's: `probe` → `plan` →
# `teach` (a missing key reads `probe`, unless the plan is already approved).
# The probe lives under `probe` = {skills, history, current, unavailable,
# refusals} and the plan under `plan` = {proposed, proposed_kinds, approved,
# cursor} plus PKG-07's `concept`/`teach_turns`/`concept_checks`. Nothing here
# writes PKG-07's top-level `current` or `steps` (only `_activate_next_item`
# sets `current`, A27). No handler here reads the tutor budget or counts a tutor
# call (A20: the probe runs at every budget level; the grader's own cap lives
# inside grade(), PKG-06b) — `/probe/answer`, the one route that can run a
# model, carries the rate limit.

#: A /probe/answer whose question_hash is not the posed item's (stale client,
#: or the item was answered or moved past meanwhile).
_PROBE_NOT_POSED = "not the posed probe item"


@dataclass(frozen=True)
class _BoundItem:
    """A course check item bound to the student's graph node (A2: stored items
    key on concept_key, never node_id). Satisfies `learning.probe.ProbeItem`;
    every other attribute is the item's own. `item` is what grade_answer takes."""

    item: CheckItem
    node_id: str

    @property
    def unsourced(self) -> bool:
        """A128: drafted from extracted text after a failed index — the probe
        ranks such an item after an equal one with its sources."""
        return item_unsourced(self.item)

    @property
    def quality(self) -> tuple:
        """Spec §13 A129: checks.serve_quality — the probe ranks an item by it
        among equal challenges (a confirmed key, then clean, never-linted,
        flagged; A128's sourced item first among flagged ones)."""
        return serve_quality(self.item)

    def __getattr__(self, name: str):
        return getattr(self.item, name)


def _require_phase(doc: dict, phase: str) -> None:
    current = _loop_phase(doc)
    if current != phase:
        raise HTTPException(status_code=409, detail=f"phase is {current}")


def _validate_goal(goal, states: dict[str, float]) -> None:
    if goal is not None and not set(goal.target_node_ids) <= set(states):
        raise HTTPException(status_code=422, detail="Choose target concepts from this course")


def _goal_scope_for(state: dict, states: dict[str, float], edges) -> frozenset[str] | None:
    goal = state.get("goal")
    if not isinstance(goal, dict) or not goal.get("target_node_ids"):
        return None
    targets = goal["target_node_ids"]
    if not set(targets) <= set(states):
        raise HTTPException(status_code=422, detail="A goal concept is no longer available; edit the goal")
    return planner.goal_scope(targets, edges, nodes=states)


def _check_goal_version(doc: dict, expected: int) -> None:
    if goal_version(doc) != expected:
        raise HTTPException(status_code=409, detail="Goal changed; refresh the learning session")


def _learning_scope_payload(state: dict) -> dict:
    pr = state.get("probe") or {}
    skills = pr.get("scope", pr.get("skills", []))
    payload = {
        "goal": public_goal(state),
        "goal_version": goal_version(state),
        "diagnosis": probe_policy.diagnostic_summary(
            pr.get("history") or [], skills=skills,
            stop_reason=pr.get("stop_reason"),
            available_difficulties=pr.get("available_difficulties"),
        ),
    }
    plan = state.get("plan") if isinstance(state.get("plan"), dict) else {}
    progress = plan.get("goal_progress")
    if state.get("goal") and isinstance(progress, dict):
        payload["goal_progress"] = copy.deepcopy(progress)
    if state.get("goal"):
        payload["practice_unavailable_node_ids"] = list(plan.get("practice_unavailable_node_ids") or [])
    return payload


def _with_goal_context(history: list, state: dict, user_id: str) -> list:
    goal = public_goal(state)
    if goal is None:
        return history
    names = _plan_node_names(user_id, goal["target_node_ids"])
    text = "Student-confirmed learning goal: " + goal["text"]
    text += "\nTarget concepts: " + ", ".join(names.get(n, n) for n in goal["target_node_ids"])
    text += "\nConnect the approved prerequisites and practice to this objective."
    context = wrap_untrusted(neutralise_control_tags(text), source="student_goal")
    return [_brief_message(context), *history]


def _probe_doc(doc: dict) -> dict:
    """The document's `probe` object with every list/map present (in place)."""
    pr = doc.get("probe")
    if not isinstance(pr, dict):
        pr = doc["probe"] = {}
    pr.setdefault("history", [])
    pr.setdefault("unavailable", [])
    pr.setdefault("refusals", {})
    pr.setdefault("current", None)
    return pr


class _PlanNodesRead:
    """Read-only paging adapter; all graph writes still use graph_service."""
    def select_with_count(self, *args, **kwargs):
        return table("graph_nodes").select_with_count(*args, **kwargs)


class _PlanEdgesRead:
    def select_with_count(self, *args, **kwargs):
        return table("graph_edges").select_with_count(*args, **kwargs)


def _plan_states(user_id: str, course_id: str) -> dict[str, float]:
    """Decayed p_known for every graph node of (user, course) — one
    `graph_nodes` read, one `learner_state` read (PKG-03); BKT_L0 for a node
    with no learner_state row."""
    rows = list(page_all(
        _PlanNodesRead(), "id",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        order="id.asc",
    ))
    ids = [r["id"] for r in rows if r.get("id")]
    states = read_states(user_id, ids)
    return {n: (states[n].p_known if n in states else BKT_L0) for n in ids}


def _plan_prereq_edges(user_id: str, node_ids: list[str]) -> list[tuple[str, str]]:
    """The user's prerequisite edges among `node_ids`, oriented (prerequisite,
    dependent) by EDGE_PREREQ_SOURCE_IS_PREREQ — the direction PKG-03's
    propagation and PKG-07's `_prereq_proficient` read. One `graph_edges` read."""
    rows = list(page_all(
        _PlanEdgesRead(), "id,source_node_id,target_node_id",
        filters={"user_id": f"eq.{user_id}",
                 "relationship_type": f"eq.{PREREQ_RELATIONSHIP_TYPE}"},
        order="id.asc",
    ))
    keep = set(node_ids)
    out = []
    for e in rows:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src in keep and tgt in keep:
            out.append((src, tgt) if EDGE_PREREQ_SOURCE_IS_PREREQ else (tgt, src))
    return out


#: Spec §13 A130: the matched pretest probe start (services/feature_flags.py).
PROBE_MATCHED_PRETEST_FLAG = "probe_matched_pretest"


def _probe_history(doc: dict) -> list:
    """The probe's recorded observations, read without touching the document
    (`_probe_doc` fills defaults in place; this reads only)."""
    pr = doc.get("probe")
    history = pr.get("history") if isinstance(pr, dict) else None
    return history if isinstance(history, list) else []


def _unanchored_skills(user_id: str, skills: list[str], history: list) -> frozenset[str]:
    """Spec §13 A130: the probe's skills whose next graded answer is their
    pretest — no graded answer in this session's probe history
    (`probe.graded_strands`) and no anchor in the evidence journal: the
    `posttest_anchors` SQL function, the one anchor rule the post-test
    windows, the due read and evidence_spans share (a void row anchors
    nothing). The anchors are read only when some skill could still be
    steered. A failed read steers nothing this time — a WARNING, and the
    probe keeps its own first-item rule (the pose later records how well the
    outcome item matched whatever pretest was asked)."""
    open_skills = [n for n in skills if n not in probe_policy.graded_strands(history)]
    if not open_skills:
        return frozenset()
    try:
        rows, _ = posttest_anchors(user_id=user_id)
    except Exception as exc:
        logger.warning("probe: anchors unread (%s); no matched pretest this time", type(exc).__name__)
        return frozenset()
    anchored = {row.get("node_id") for row in rows}
    return frozenset(n for n in open_skills if n not in anchored)


def _probe_course_has_items(course_id: str) -> bool:
    """A23: one `limit=1` read; False for a session with no course."""
    return bool(course_id) and course_has_items(course_id)


def _preparing(user_id: str, course_id: str, *, no_items: bool = False) -> dict:
    """Spec §13 A128: `{"preparing": True}` while the course has no item to
    serve and the student's own upload in it is still being drafted
    (`check_item_service.drafting_pending`), else {} — present only when true.
    `no_items`: the caller already read that the course has none. Advisory
    copy, so a read that fails answers {} (the pre-A128 state), never an error."""
    try:
        if not no_items and _probe_course_has_items(course_id):
            return {}
        return {"preparing": True} if drafting_pending(user_id, course_id) else {}
    except Exception as exc:
        logger.warning("loop: the preparing state could not be read (%s)", type(exc).__name__)
        return {}


def _probe_items(user_id: str, course_id: str, node_ids: list[str]) -> list[_BoundItem]:
    """PKG-08's node → concept_key → items resolver (A2; the inverse of PKG-07's
    `_node_for_item`): one `graph_nodes` read for the nodes' names, one
    `check_items` read for their normalised keys, each item bound to the node.
    Unfiltered — the handlers drop the reserve, unavailable, revealed and
    unservable items (they must still COUNT an asked one)."""
    if not node_ids:
        return []
    rows = (
        table("graph_nodes").select(
            "id,concept_name",
            filters={
                "user_id": f"eq.{user_id}",
                "course_id": f"eq.{course_id}",
                "id": f"in.({','.join(sorted(set(node_ids)))})",
            },
        )
        or []
    )
    node_for_key: dict[str, str] = {}
    for row in sorted(rows, key=lambda r: r.get("id") or ""):
        key = _normalize_concept(row.get("concept_name") or "")
        if key and row.get("id"):
            node_for_key.setdefault(key, row["id"])  # one node per concept key
    by_key = items_for_concepts(course_id, list(node_for_key))
    return [
        _BoundItem(item, node_for_key[key])
        for key, items in by_key.items()
        if key in node_for_key
        for item in items
    ]


def _plan_node_names(user_id: str, node_ids: list[str]) -> dict[str, str]:
    """id → concept_name for the student's nodes (one `graph_nodes` read)."""
    if not node_ids:
        return {}
    rows = (
        table("graph_nodes").select(
            "id,concept_name",
            filters={"user_id": f"eq.{user_id}", "id": f"in.({','.join(sorted(set(node_ids)))})"},
        )
        or []
    )
    return {r["id"]: r.get("concept_name") or "" for r in rows if r.get("id")}


def _plan_due_reviews(
    user_id: str, node_ids: list[str], *, now: datetime | None = None
) -> list[str]:
    """The plan's review section: nodes whose FSRS review is due now
    (`fsrs_due_at ≤ now`; never reviewed = not due), in PKG-02's `order_due`
    order, capped by `budget_select` (REVIEW_DAILY_BUDGET_MIN /
    REVIEW_SECONDS_PER_CHECK). One `learner_state` read."""
    now = now or datetime.now(timezone.utc)
    due = [
        {"node_id": n, "fsrs_s": st.fsrs_s, "fsrs_last_review_at": st.fsrs_last_review_at}
        for n, st in read_states(user_id, node_ids, now=now).items()
        if st.fsrs_due_at is not None and st.fsrs_due_at <= now
    ]
    ordered = order_due(sorted(due, key=lambda r: r["node_id"]), now)
    return [
        r["node_id"]
        for r in budget_select(ordered, REVIEW_DAILY_BUDGET_MIN, REVIEW_SECONDS_PER_CHECK)
    ]


def _probe_done_payload(pr: dict) -> dict:
    """learn.probe_done (spec §6): ids and counts only."""
    history = list(pr.get("history") or [])
    return {
        "items": len(history),
        "misses": sum(1 for h in history if not h.get("correct")),
        "novice_floor": probe_policy.novice_floor(history),
        "skills": list(pr.get("skills") or []),
    }


def _emit_probe_done(saved: dict, user_id: str, request_id: str) -> None:
    events_service.log_event(
        "learn.probe_done",
        category="usage",
        user_id=user_id,
        request_id=request_id,
        payload=_probe_done_payload(_probe_doc(dict(saved))),
    )


def _probe_plan_read_limit(user_id: str) -> None:
    """A cheap per-user limit on the two no-model routes that write loop state
    (/probe/next, GET /plan): services/request_limits' in-process sliding
    window, PROBE_PLAN_READS_PER_MIN a minute. Runs after the gate. No model
    runs behind these routes, so this is not the A20 rate limit (llm_usage)."""
    retry = check_rate_limit(
        f"loop_probe_plan:{user_id}", limit=config.LOOP_PROBE_PLAN_READS_PER_MIN, window_sec=60
    )
    if retry is not None:
        raise HTTPException(
            status_code=429, detail="too many requests", headers={"Retry-After": str(retry)}
        )


def _update_if_changed(session_id: str, doc: dict, mutate: Callable[[dict], None], *, require_open: bool = False) -> dict:
    """`_update_loop_state`, skipped when `mutate` leaves the document as read
    unchanged (a re-served item, a re-GET of the same plan): the mutate runs on a
    copy first; only a real change costs a compare-and-set write."""
    trial = copy.deepcopy(doc)
    mutate(trial)
    if trial == doc:
        return trial
    return _update_loop_state(session_id, mutate, require_open=require_open)


def _claim_live(current: dict, now: float) -> bool:
    if grade_checkpoint.KEY in current:
        return True
    claimed_at = current.get("grading_claim_at")
    return bool(current.get("grading_claim")) and (
        now - float(claimed_at or 0) <= LOOP_GRADING_CLAIM_STALE_S
    )


@dataclass(frozen=True)
class _PlanView:
    states: dict[str, float]
    planning_states: dict[str, float]
    scope: frozenset[str] | None
    targets: frozenset[str]
    ready: frozenset[str]
    proposal: planner.Plan
    signature: str | None
    practice_unavailable: frozenset[str]


def _planning_observations(state: dict, user_id: str, course_id: str, nodes) -> list[dict]:
    try:
        return read_planning_history(user_id, course_id, nodes)
    except PlanningPersistenceUnavailable as exc:
        raise HTTPException(status_code=503, detail="Learning evidence unavailable; retry") from exc


def _current_plan(state: dict, user_id: str, course_id: str) -> _PlanView:
    states = _plan_states(user_id, course_id)
    edges = _plan_prereq_edges(user_id, list(states))
    scope = _goal_scope_for(state, states, edges)
    targets = frozenset((state.get("goal") or {}).get("target_node_ids") or [])
    observations = (_planning_observations(state, user_id, course_id, states)
                    if scope is not None else planning_observations(state))
    planning_states = planner.planning_states(states, observations)
    parents: dict[str, set[str]] = {}
    for prereq, dependent in edges:
        if prereq != dependent:
            parents.setdefault(dependent, set()).add(prereq)

    def siblings(node_id: str) -> list[str]:
        mine = parents.get(node_id, set())
        return sorted(m for m, ps in parents.items() if m != node_id and ps & mine)

    ready = planner.prerequisite_ready(planning_states, edges, transitive=True) if scope is not None else frozenset(states)
    attempted = set(attempted_nodes(state)) if scope is not None else set()
    fringe = planner.outer_fringe(planning_states, edges)
    reviews = list(dict.fromkeys(_plan_due_reviews(user_id, list(states)) + [
        n for n in sorted(targets) if planning_states[n] >= BKT_PROFICIENT
    ]))
    proficient = frozenset(n for n, p in planning_states.items() if p >= BKT_PROFICIENT)
    candidates = (set(fringe) | set(reviews) | {s for n in fringe for s in siblings(n) if s in proficient}
                  if scope is not None else set())
    unavailable = (_goal_practice_unavailable(
        user_id, course_id, state, sorted(candidates & scope & ready - attempted),
    ) if scope is not None else set())
    previous = state.get("plan") if isinstance(state.get("plan"), dict) else {}
    # Activation may have lost its last item after approval. Preserve that
    # exhausted attempt; new assets never reset this session's finite frontier.
    unavailable |= set(previous.get("practice_unavailable_node_ids") or []) & attempted
    proposal = planner.plan(
        fringe,
        reviews,
        siblings,
        (lambda n: n in scope and n in ready and n not in attempted and n not in unavailable) if scope is not None else None,
        proficient=proficient,
    )
    return _PlanView(states, planning_states, scope, targets, ready, proposal,
                     scope_signature(targets, scope, edges) if scope is not None else None,
                     frozenset(unavailable))


def _continue_goal(session_id: str, user_id: str, course_id: str, state: dict) -> dict:
    """Offer another finite frontier only after an explicit 'Check me' request.

    Every exhausted concept is remembered, so an unresolved/bank-starved
    foundation cannot repeat indefinitely. A new frontier still needs approval.
    """
    previous = state.get("plan") if isinstance(state.get("plan"), dict) else {}
    if not state.get("goal") or not previous.get("done"):
        return state
    version = goal_version(state)
    view = _current_plan(state, user_id, course_id)
    progress = goal_progress(state, view.planning_states, view.scope,
                             continue_available=bool(view.proposal.concepts))
    attempted = attempted_nodes(state)

    def offer(doc: dict) -> None:
        _require_teaching(doc)
        _check_goal_version(doc, version)
        _refuse_while_closing(doc, _now_s())
        plan = doc.get("plan") or {}
        if not plan.get("done") or attempted_nodes(doc) != attempted or doc.get("current"):
            raise _StateConflict()
        plan["goal_progress"] = progress
        plan["practice_unavailable_node_ids"] = sorted(view.practice_unavailable)
        if view.proposal.concepts:
            for key in ("proposed", "proposed_kinds", "scope_signature"):
                plan.pop(key, None)
            doc["phase"] = "plan"
        doc["plan"] = plan

    return _update_loop_state(session_id, offer, require_open=True)
