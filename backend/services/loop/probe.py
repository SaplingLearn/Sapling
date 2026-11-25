"""POST /probe/next (PKG-08): the probe's next item, or the plan.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from starlette.requests import Request
from agents.tools.check import CHANNEL_FOR_FORMAT
from learning import planner
from learning import grade_checkpoint
from learning import probe as probe_policy
from learning.checks import is_servable, posttest_reserves, pretest_form
from learning.goals import goal_version
from learning.loop_state_store import reported_hashes, revealed_hashes, seen_hashes
from learning.help_ledger import record_posed
from learning.params import BKT_L0, PROBE_MAX_SKILLS, PROBE_SESSION_CAP
from models import ProbeNextBody
from services.tutor import _consume_pending
from services.feature_flags import flag_on

from services.loop.flags import _GRADING_CLAIM
from services.loop.state import (
    _gate,
    _load_loop_state,
    _now_s,
    _pending_grade,
    _refuse_while_closing,
    _request_id,
    _session_scope,
    _update_loop_state,
)
from services.loop.reveals import _ledger
from services.loop.planning import (
    _check_goal_version,
    _claim_live,
    _emit_probe_done,
    _goal_scope_for,
    _learning_scope_payload,
    _plan_prereq_edges,
    _plan_states,
    _preparing,
    _probe_course_has_items,
    _probe_doc,
    _probe_history,
    _probe_items,
    PROBE_MATCHED_PRETEST_FLAG,
    _probe_plan_read_limit,
    _require_phase,
    _unanchored_skills,
    _update_if_changed,
)
from services.loop.practice import _pose_payload

#: The loop phases the probe moves between: it runs in `probe` and hands over to `plan`.
PROBE_PHASE = "probe"
PLAN_PHASE = "plan"

#: The probe's stop reasons (probe.stop_reason) chosen here; the rest come
#: from learning.probe.diagnostic_summary.
STOP_ITEM_BANK_EXHAUSTED = "item_bank_exhausted"
STOP_SESSION_LIMIT = "session_limit"
STOP_OBSERVED_BOUNDARIES = "observed_boundaries"
STOP_COVERAGE_LIMIT = "coverage_limit"

#: The help ledger's source for an item the probe posed (A93).
_LEDGER_SOURCE = "probe"


@dataclass(frozen=True)
class _ProbeBank:
    """What one /probe/next call selects from, read before the compare-and-set:
    the skill set, the goal scope, the mastery states, the items and the hashes
    a selection may never (or only last) serve."""

    version: object
    now: float
    skills: list[str]
    scope: set[str] | None
    states: dict
    items: list
    revealed: set[str]
    seen: set[str]
    reserves: set[str]
    by_hash: dict
    unanchored: frozenset


def _fixed_skills(state: dict) -> list | None:
    """The skill set the probe's first call fixed, or None before it."""
    return (state.get("probe") or {}).get("skills") if isinstance(state.get("probe"), dict) else None


def _finish_without_items(body: ProbeNextBody, state: dict, course_id, version, request_id) -> dict:
    """A course with no check items: the probe ends at once (`no_check_items`,
    A23/A26), recording the goal scope it would have covered."""
    empty_scope = []
    if state.get("goal"):
        goal_states = _plan_states(body.user_id, course_id)
        goal_edges = _plan_prereq_edges(body.user_id, list(goal_states))
        empty_scope = sorted(_goal_scope_for(state, goal_states, goal_edges) or [])

    def finish_empty(doc: dict) -> None:
        _require_phase(doc, PROBE_PHASE)
        _check_goal_version(doc, version)
        pr = _probe_doc(doc)
        pr["scope"] = empty_scope
        pr["stop_reason"] = STOP_ITEM_BANK_EXHAUSTED
        pr["skills"] = []
        pr["current"] = None
        doc["phase"] = PLAN_PHASE

    saved = _update_loop_state(body.session_id, finish_empty)
    _emit_probe_done(saved, body.user_id, request_id)
    return {
        "done": True,
        "phase": PLAN_PHASE,
        "no_check_items": True,
        # A128: the student's own upload is still being drafted — the UI says
        # "preparing" instead of "no check items" (present only when true)
        **_preparing(body.user_id, course_id, no_items=True),
        **_learning_scope_payload(saved, body.session_id),
    }


def _probe_skills(state: dict, fixed: list | None, states: dict, edges, scope) -> list[str]:
    """The probe's skills: on the first call the goal targets, the outer fringe
    of the course graph and the goal scope, capped at PROBE_MAX_SKILLS; after
    it the fixed set, still inside the graph and the scope."""
    if fixed is None:
        fringe = planner.outer_fringe(states, edges)
        targets = list((state.get("goal") or {}).get("target_node_ids") or [])
        candidates = targets + fringe + (sorted(scope) if scope is not None else [])
        return list(dict.fromkeys(n for n in candidates if scope is None or n in scope))[:PROBE_MAX_SKILLS]
    return [s for s in fixed if isinstance(s, str) and s in states and (scope is None or s in scope)]


def _probe_bank(body: ProbeNextBody, state: dict, course_id, fixed, version) -> _ProbeBank:
    """Read everything a selection needs, in the route's read order."""
    states = _plan_states(body.user_id, course_id)
    edges = _plan_prereq_edges(body.user_id, list(states))
    scope = _goal_scope_for(state, states, edges)
    skills = _probe_skills(state, fixed, states, edges, scope)
    items = _probe_items(body.user_id, course_id, skills)
    # A113: an item the student reported is never posed again, like a revealed one
    revealed = (revealed_hashes(body.user_id) | reported_hashes(body.user_id)) if items else set()
    seen = seen_hashes(body.user_id) if items else set()
    reserves = {  # A23, A126: every concept's protected post-test items
        qh
        for n in {it.node_id for it in items}
        for qh in posttest_reserves([it for it in items if it.node_id == n])
    }
    by_hash = {it.question_hash: it for it in items}
    # spec §13 A130 (flag probe_matched_pretest, off by default): the skills
    # whose next graded answer is their pretest — no graded probe answer in
    # this session and no anchor in the journal — start on a form parallel to
    # their post-test reserves. Off: no anchors read, nothing steered.
    unanchored = (
        _unanchored_skills(body.user_id, skills, _probe_history(state))
        if items and flag_on(PROBE_MATCHED_PRETEST_FLAG, body.user_id)
        else frozenset()
    )
    return _ProbeBank(
        version=version, now=_now_s(), skills=skills, scope=scope, states=states, items=items,
        revealed=revealed, seen=seen, reserves=reserves, by_hash=by_hash, unanchored=unanchored,
    )


def _refresh_node_practice(node: str, practice: dict, bank: _ProbeBank, excluded: set, current_hash) -> str | None:
    """Keep `node`'s teaching-practice reserve fresh (separate from the delayed
    post-test, stable across answers and goal changes) and return its matched
    pretest form (A130), if any. `excluded` is what was asked or is unavailable."""
    eligible = [it.question_hash for it in bank.items if it.node_id == node
                and it.question_hash not in bank.reserves | bank.revealed | bank.seen | excluded
                and it.question_hash != current_hash and is_servable(it)]
    # A130: what a pretest form may not be (the reserves are its own rule)
    spent = bank.revealed | bank.seen | excluded | ({current_hash} - {None})
    forms_bank = [it for it in bank.items if it.node_id == node] if node in bank.unanchored else []
    best = pretest_form(forms_bank, spent) if forms_bank else None
    if practice.get(node) not in eligible:
        practice.pop(node, None)
        # A130: teaching keeps another fresh item when there is one, so
        # the probe can ask the best form; with only the form fresh,
        # teaching keeps it (the reserve predates the flag)
        spare = [qh for qh in eligible if best is None or qh != best.question_hash] or eligible
        if spare:
            practice[node] = max(spare)
    if forms_bank:
        form = pretest_form(forms_bank, spent | {practice.get(node)} - {None})
        if form is not None:
            return form.question_hash
    return None


def _refresh_practice(pr: dict, practice: dict, bank: _ProbeBank, asked: set, current_hash) -> dict[str, str]:
    """Every skill's practice reserve, refreshed; returns node → its matched
    pretest form (A130)."""
    forms: dict[str, str] = {}
    excluded = asked | set(pr["unavailable"])
    for node in bank.skills:
        form = _refresh_node_practice(node, practice, bank, excluded, current_hash)
        if form is not None:
            forms[node] = form
    return forms


def _available_difficulties(pr: dict, bank: _ProbeBank, practice_hashes: set) -> dict:
    return {
        n: sorted({it.difficulty for it in bank.items if it.node_id == n
                   and it.question_hash not in bank.reserves | bank.revealed | practice_hashes
                   and is_servable(it)})
        for n in pr["scope"]
    }


def _serve_current_again(pr: dict, cur, bank: _ProbeBank, out: dict) -> bool:
    """A posed item not yet answered is served again (True). One withdrawn
    (A23), held (A124, A123) or left under a stale claim (C2) is never asked
    again: it is marked unavailable and the probe moves past it (False)."""
    if not (isinstance(cur, dict) and cur.get("question_hash")):
        return False
    qh = cur["question_hash"]
    if (not cur.get(_GRADING_CLAIM) or _claim_live(cur, bank.now)) and qh in bank.by_hash:
        out["item"] = bank.by_hash[qh]  # posed and not answered: the same item again
        return True
    if qh not in pr["unavailable"]:
        pr["unavailable"].append(qh)
    pr["current"] = None
    return False


def _next_item(pr: dict, bank: _ProbeBank, asked: set, practice_hashes: set, forms: dict):
    """learning.probe's next item; seen items only when nothing unseen is left."""
    per_node = Counter(h.get("node_id") for h in pr["history"])
    skill_states = {n: bank.states.get(n, BKT_L0) for n in pr["skills"]}

    def pick(extra_never: set[str]):
        never = (bank.reserves | practice_hashes | bank.revealed | set(pr["unavailable"]) | extra_never) - asked
        candidates = [
            it
            for it in bank.items
            if it.question_hash in asked or (it.question_hash not in never and is_servable(it))
        ]
        return probe_policy.next_probe_item(
            skill_states,
            candidates,
            asked,
            channel_for_format=CHANNEL_FOR_FORMAT,
            asked_per_node=per_node,
            history=pr["history"],
            # A130: only with a form to ask, so the flag-off call is the one before it
            **({"pretest_forms": forms} if forms else {}),
        )

    return pick(bank.seen) or pick(set())


def _end_probe(doc: dict, pr: dict, out: dict, reason: str) -> None:
    pr["stop_reason"] = reason
    doc["phase"] = PLAN_PHASE
    out["done"] = True


def _exhausted_reason(pr: dict) -> str:
    """Why a probe with no next item stops: the diagnostic's reason, widened to
    `coverage_limit` when the scope holds skills the probe did not cover."""
    reason = probe_policy.diagnostic_summary(pr["history"], skills=pr["skills"])["stop_reason"]
    if reason == STOP_OBSERVED_BOUNDARIES and set(pr["scope"]) - set(pr["skills"]):
        reason = STOP_COVERAGE_LIMIT
    return reason or STOP_ITEM_BANK_EXHAUSTED


def _pose_next(pr: dict, item, bank: _ProbeBank, out: dict) -> None:
    if item.question_hash not in pr["presented"]:
        pr["presented"].append(item.question_hash)
    pr["current"] = {
        "check_item_id": item.id,
        "question_hash": item.question_hash,
        "node_id": item.node_id,
        "difficulty": item.difficulty,
        "channel": CHANNEL_FOR_FORMAT[item.format],
        "previously_seen": item.question_hash in bank.seen,
    }
    out["item"] = item
    out["new"] = True


def _start_probe_doc(doc: dict, bank: _ProbeBank) -> dict:
    """The checks every selection write makes first, and the probe document
    with its skill set, scope and presented list in place."""
    _require_phase(doc, PROBE_PHASE)
    _check_goal_version(doc, bank.version)
    _refuse_while_closing(doc, bank.now)
    doc["phase"] = PROBE_PHASE  # explicit from the first item on
    pr = _probe_doc(doc)
    if pr.get("skills") is None:
        pr["skills"] = list(bank.skills)
    pr["scope"] = sorted(bank.scope) if bank.scope is not None else list(bank.skills)
    pr.setdefault("presented", [])
    return pr


def _select(doc: dict, bank: _ProbeBank, out: dict) -> None:
    """The selection's compare-and-set mutate (it may run more than once, each
    time on a fresher document); what the caller serves lands in `out`."""
    out.clear()
    pr = _start_probe_doc(doc, bank)
    cur = pr.get("current")
    if isinstance(cur, dict) and grade_checkpoint.KEY in cur:
        out["pending_grade"] = _pending_grade(doc)
        return
    # Keep fresh teaching practice separately from the delayed posttest.
    # The reserved question stays stable across answers and goal changes.
    practice = pr.setdefault("practice_reserves", {})
    asked = {h.get("question_hash") for h in pr["history"]}
    current_hash = cur.get("question_hash") if isinstance(cur, dict) else None
    forms = _refresh_practice(pr, practice, bank, asked, current_hash)  # A130: node → its form
    practice_hashes = set(practice.values())
    pr["available_difficulties"] = _available_difficulties(pr, bank, practice_hashes)
    if _serve_current_again(pr, cur, bank, out):
        return
    asked = {h.get("question_hash") for h in pr["history"]}
    if len(set(pr["presented"]) | asked | set(pr["unavailable"])) >= PROBE_SESSION_CAP:
        _end_probe(doc, pr, out, STOP_SESSION_LIMIT)
        return
    item = _next_item(pr, bank, asked, practice_hashes, forms)
    if item is None:
        _end_probe(doc, pr, out, _exhausted_reason(pr))
        return
    _pose_next(pr, item, bank, out)


def _pose_response(body: ProbeNextBody, item, saved: dict) -> dict:
    pose = _pose_payload(item)  # prompt + letter/text options only (A22), never the key
    return {
        "done": False,
        "check_item_id": item.id,
        "question_hash": pose["question_hash"],
        "node_id": item.node_id,
        "format": pose["format"],
        "difficulty": pose["difficulty"],
        "prompt": pose["prompt"],
        "options": pose["options"],
        **_learning_scope_payload(saved, body.session_id),
    }


def probe_next(body: ProbeNextBody, request: Request) -> dict:
    """The next probe item (Behaviour 10): no model call (so no A20 rate limit;
    the cheap per-user read limit instead). The
    skill set is fixed on the first call — the outer fringe of the course graph,
    capped at PROBE_MAX_SKILLS — or, for a course with no check items, the probe
    ends at once (`no_check_items`, A23/A26). A posed item is served again until
    it is answered (never a skip); one left under a stale grading claim is
    moved past. Selection never serves a concept's post-test reserve (A23), an
    item whose answer this student has been shown (`revealed_hashes`), one they
    reported (`reported_hashes`, A113), one the
    grader could not grade (`unavailable`), or one with no final answer (A34);
    an item the student already has evidence on (`seen_hashes`) only when no
    unseen one is left (review's A23 fallback). Asked items always count toward
    the per-skill cap, by the recorded observations."""
    _gate(body.user_id, request)
    _probe_plan_read_limit(body.user_id)
    _consume_pending(body.session_id, body.user_id)
    _, course_id = _session_scope(body.session_id, body.user_id)
    state = _load_loop_state(body.session_id)
    _require_phase(state, PROBE_PHASE)
    if _pending_grade(state):
        return {"done": False, "pending_grade": _pending_grade(state), **_learning_scope_payload(state, body.session_id)}
    request_id = _request_id(request)
    version = goal_version(state)
    fixed = _fixed_skills(state)
    if fixed is None and not _probe_course_has_items(course_id):
        return _finish_without_items(body, state, course_id, version, request_id)
    bank = _probe_bank(body, state, course_id, fixed, version)
    out: dict = {}
    saved = _update_if_changed(body.session_id, state, lambda doc: _select(doc, bank, out))
    if out.get("pending_grade"):
        return {"done": False, "pending_grade": out["pending_grade"], **_learning_scope_payload(saved, body.session_id)}
    if out.get("done"):
        _emit_probe_done(saved, body.user_id, request_id)
        return {"done": True, "phase": PLAN_PHASE, **_learning_scope_payload(saved, body.session_id)}
    item = out["item"]
    if out.get("new"):  # A93: posed — in the scan set until graded
        _ledger(record_posed, body.user_id, item.question_hash, source=_LEDGER_SOURCE, session_id=body.session_id)
    return _pose_response(body, item, saved)
