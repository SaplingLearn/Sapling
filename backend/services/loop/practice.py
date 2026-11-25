"""The next check (spec §10): band control (A122), the target difficulty,
worked examples, the isomorph re-ask and `_activate_next_item`.
"""
from __future__ import annotations

from services.loop.errors import HTTPException
from learning import ladder, policy
from learning import prequestion as prequestion_rules
from learning.checks import is_servable, select_item, serve_quality
from learning.multi_concept import STEP_KEY as MULTI_CONCEPT_STEP_KEY
from learning.multi_concept import is_multi_concept
from learning.goals import attempted_nodes
from learning.ladder import Rung
from learning.misconceptions import (
    attempts_for_node,
    attempts_of,
    set_confront,
    slip_or_misconception,
)
from learning.loop_state_store import reported_hashes, revealed_hashes, seen_hashes
from learning.params import (
    SURFACE_FAMILIARITY_UNKNOWN,
    CHECK_ITEM_DIFFICULTIES,
    LOOP_CHECK_DIFFICULTY_BY_BAND,
    LOOP_CHECKS_PER_CONCEPT,
)
from services import varied_practice

from services.loop.constants import _MC_REASON
from services.loop.state import _step_state, _steps
from services.loop.learner import (
    _BAND_CEILING,
    _band_ceiling_delta,
    _band_of,
    _learner_state,
    _learner_view,
    _prereq_proficient,
)
from services.loop.context import _RETRIEVAL_FAILED_VALUE, _RETRIEVAL_KEY, _take_retrieval_mark
from services.loop.planning import _practice_pool
from services.loop.cursor import _advance_cursor, CURSOR_REASON_KEY, _MOVE_REASONS
from services.loop.next_probe_hint import preferred_next_question_hash


def _count_feedback_and_move(state: dict, entry: dict) -> None:
    """A27: one more graded check on the concept; the cursor advances at the
    cap — unless the band controller's verdict on this grade (spec §13 A122)
    already moved it: stop practice, wheel-spin, prerequisite repair. The
    feedback turn's own compare-and-set mutate (and, read-only on a copy,
    spec §13 A138's prequestion trial) runs it."""
    state["concept_checks"] = int(state.get("concept_checks") or 0) + 1
    state["teach_turns"] = 0
    moved = _apply_band_control(state, entry)
    if not moved and state["concept_checks"] >= LOOP_CHECKS_PER_CONCEPT:
        _advance_cursor(state)


# ── Band control on the plan (spec §3.3, §13 A122) ──────────────────────────
#: loop_state key: node id → the target difficulty band control set for that
#: concept's next item this session (ids → ints only; read by activation)
_BAND_DIFFICULTY = "band_difficulty"


#: the graded step's key holding the verdict _finish_check_checkpoint stored
_BAND_CONTROL = "band_control"


def _repaired(plan: dict, concept: str, prereq: str) -> bool:
    """This concept already sent the student to this prerequisite in the
    session (`plan["repairs"]`): each (concept, prerequisite) repair runs at
    most once a session, so repairs never cycle."""
    return any(
        isinstance(r, dict) and r.get("for") == concept and r.get("node_id") == prereq
        for r in plan.get("repairs") or []
    )


def _repair_cursor(
    state: dict, prereq: str, action: policy.BandAction, *, replace: bool
) -> None:
    """Prerequisite repair (§3.3): teaching moves to `prereq` NOW — it takes the
    plan slot at the cursor, so activation, the band and the ceiling follow it.
    REPAIR_RETURN (`replace` False) puts the concept right after it, to be
    practised again once the prerequisite's checks are done; REPAIR_REPLACE
    (wheel-spin: stop more-of-the-same) drops the concept from the rest of the
    session, and a goal session records it attempted, as _advance_cursor would.
    A later occurrence of `prereq` in the plan moves up to here. Recorded in
    `plan["repairs"]` (ids and the enum only)."""
    plan = state["plan"]
    approved = [n for n in plan.get("approved") or [] if isinstance(n, str)]
    cursor = int(plan.get("cursor") or 0)
    concept = state["concept"]
    ahead = [n for n in approved[cursor + 1 :] if n != prereq]
    plan["approved"] = approved[:cursor] + [prereq] + ([] if replace else [concept]) + ahead
    plan["repairs"] = [
        *(plan.get("repairs") or []),
        {"node_id": prereq, "for": concept, "action": action.value},
    ]
    if replace and state.get("goal"):
        # an exhausted session frontier is an attempt, never a claim of proficiency
        plan["attempted"] = list(dict.fromkeys([*attempted_nodes(state), concept]))
        plan["checked_nodes"] = list(
            dict.fromkeys([*(plan.get("checked_nodes") or []), concept])
        )
    set_confront(state, None)  # PKG-10 (F2): a marker never outlives its concept
    state["concept"] = prereq
    state["teach_turns"] = 0
    state["concept_checks"] = 0


def _apply_band_control(state: dict, entry: dict) -> bool:
    """Apply the band controller's verdict on the graded step `entry` (spec §3.3,
    §13 A122) as its feedback turn is served — inside that turn's
    compare-and-set mutate, from the stored verdict alone (no reads). The next
    item's difficulty: `state["band_difficulty"][node]` (activation reads it).
    The concept's ceiling clause: `state["band_ceiling"][node]` (−1 / +1 rung,
    `policy.ceiling_delta`; every ceiling on the concept reads it through
    `_band_ceiling_delta`, gates unchanged; HOLD keeps the last one).
    The cursor: policy.cursor_move — STOP_PRACTICE leaves the concept,
    WHEELSPIN stops more-of-the-same (repairing the weakest unproficient
    prerequisite in its place when there is one), EASIER_CHECK_PREREQS repairs
    a weak prerequisite first and comes back. True when the cursor moved, so
    the per-concept check count does not move it again. A verdict on a concept
    the cursor has left, or a session without a plan, moves nothing."""
    verdict = entry.get(_BAND_CONTROL)
    if not isinstance(verdict, dict):
        return False
    try:
        action = policy.BandAction(verdict.get("action"))
    except ValueError:
        return False
    node = entry.get("node_id")
    if not isinstance(node, str) or not node:
        return False
    target = verdict.get("difficulty")
    if type(target) is int and target in CHECK_ITEM_DIFFICULTIES:
        targets = state.get(_BAND_DIFFICULTY)
        state[_BAND_DIFFICULTY] = {**(targets if isinstance(targets, dict) else {}), node: target}
    # §3.3's ceiling clause, from the action itself (never a stored number):
    # HARDER −1 rung, EASIER_CHECK_PREREQS +1; the band's ceiling only
    delta = policy.ceiling_delta(action)
    if delta:
        deltas = state.get(_BAND_CEILING)
        state[_BAND_CEILING] = {**(deltas if isinstance(deltas, dict) else {}), node: delta}
    plan = state.get("plan")
    if node != state.get("concept") or not isinstance(plan, dict):
        return False
    prereq = verdict.get("repair")
    available = (
        isinstance(prereq, str) and bool(prereq) and prereq != node
        and not _repaired(plan, node, prereq)
    )
    move = policy.cursor_move(action, repair_available=available)
    if move is policy.CursorMove.STAY:
        return False
    # spec §13 A121 × A122: every move records why the cursor moved
    # (mark_cursor_reason, read by plan_focus); a plan-order advance clears it
    wheelspin = action is policy.BandAction.WHEELSPIN
    if move is policy.CursorMove.ADVANCE:
        if _advance_cursor(state) and wheelspin:
            mark_cursor_reason(state, "wheelspin_moved")  # moved on, no prerequisite to repair
    else:
        _repair_cursor(state, prereq, action, replace=move is policy.CursorMove.REPAIR_REPLACE)
        mark_cursor_reason(state, "wheelspin_moved" if wheelspin else "prerequisite_repair")
    return True


def _target_difficulty(state: dict, node_id: str, band: str) -> int:
    """The difficulty an activated item on the concept targets (select_item falls
    back to the nearest): the band controller's target for the concept this
    session when a verdict set one (spec §13 A122: HARDER one step up,
    EASIER_CHECK_PREREQS one step down from the graded item's), else the band's
    LOOP_CHECK_DIFFICULTY_BY_BAND."""
    targets = state.get(_BAND_DIFFICULTY)
    target = targets.get(node_id) if isinstance(targets, dict) else None
    if type(target) is int and target in CHECK_ITEM_DIFFICULTIES:
        return target
    return LOOP_CHECK_DIFFICULTY_BY_BAND[band]


def _worked_example_shown(state: dict, node_id: str) -> bool:
    """A worked example was already shown on this concept this session: one of
    its steps opened on the worked example AND reached H4 (spec §13 A122's
    near-transfer rule — the next item is attempted, not shown worked)."""
    return any(
        isinstance(e, dict)
        and e.get("node_id") == node_id
        and e.get("worked_first") is True
        and int(e.get("rung") or 0) >= int(Rung.H4)
        for e in (state.get("steps") or {}).values()
    )


def mark_cursor_reason(state: dict, reason: str) -> None:
    """THE HOOK for a cursor move that is not plan order (spec §13 A121 × A122).
    A122's band control calls it right after it moves `plan.cursor` / `concept`
    (`_apply_band_control`): "prerequisite_repair" after a repair that comes
    back (EASIER_CHECK_PREREQS), "wheelspin_moved" after wheel-spin's move — a
    repair in the concept's place, or moving on when there is none — so the v2
    tutor's teach turns say why the plan is on the new concept (`plan_focus`).
    The next plan-order advance (`_advance_cursor`) clears it. PKG-10's isomorph
    re-ask moves no cursor: plan_focus reads it off the attempt log, exactly
    while the re-ask is pending."""
    if reason not in _MOVE_REASONS:
        raise ValueError(f"not a cursor move reason: {reason!r} (expected one of {_MOVE_REASONS})")
    plan = state.get("plan")
    if isinstance(plan, dict):
        plan[CURSOR_REASON_KEY] = reason


def plan_focus(state: dict) -> tuple[str, str] | None:
    """Spec §13 A121 (`loop_tutor_v2`): (the plan's current concept node, why
    the cursor is there), from loop state only — never from text. The reason
    is "isomorph_reask" when the session's last attempt on the concept was
    `unknown` (its next check re-asks an isomorph, `_isomorph_after_unknown`),
    else the reason a non-plan-order move recorded (`mark_cursor_reason`),
    else "plan_order". None with no plan, a finished plan or no concept. Pure:
    `state` is never changed."""
    plan = state.get("plan")
    concept = state.get("concept")
    if not isinstance(plan, dict) or plan.get("done") or not isinstance(concept, str) or not concept:
        return None
    tail = attempts_for_node(attempts_of(dict(state)), concept)  # a copy: attempts_of may add the log
    if tail and slip_or_misconception(tail) == "unknown":
        return concept, "isomorph_reask"
    moved = plan.get(CURSOR_REASON_KEY)
    return concept, moved if moved in _MOVE_REASONS else "plan_order"


def _isomorph_after_unknown(
    state: dict, node_id: str, items: list, exclude: set, *, familiarity: dict | None = None
):
    """PKG-10 (spec §3.3 "unknown → re-ask an isomorph"; §13 A27): when the
    session's last attempt on this concept was `unknown`, the isomorph of that
    attempt's item (policy.next_isomorph) among the site's own candidates —
    everything `exclude` leaves (seen, revealed, session hashes, the post-test
    reserve; A23), servable only (A34) — else None (the normal pick).
    `familiarity` (spec §13 A140, varied_isomorphs on): among isomorphs of
    equal quality, the one whose surface the student has met least first."""
    tail = attempts_for_node(attempts_of(state), node_id)
    if not tail or slip_or_misconception(tail) != "unknown":
        return None
    last = next((i for i in items if i.question_hash == tail[-1].question_hash), None)
    if last is None:
        return None
    # spec §13 A129: next_isomorph takes the FIRST isomorph in the given
    # order — every isomorph is equal under its rule (same concept, format and
    # difficulty) — so the candidates go best-first by serve_quality; ties keep
    # the bank's (created_at, id) order (a stable sort)
    candidates = (i for i in items if i.question_hash not in exclude and is_servable(i))
    if familiarity is None:
        return policy.next_isomorph(last, sorted(candidates, key=serve_quality))
    # spec §13 A140: then the least familiar surface (the re-ask's "different
    # surface", §3.3, read off the stored descriptors)
    return policy.next_isomorph(
        last,
        sorted(
            candidates,
            key=lambda i: (
                *serve_quality(i),
                familiarity.get(i.question_hash, SURFACE_FAMILIARITY_UNKNOWN),
            ),
        ),
    )


def _activate_next_item(
    user_id: str,
    course_id: str,
    state: dict,
    *,
    now: float,
    session_id: str | None = None,
) -> str | None:
    """The ONLY code that SETS the document's `current` (the spec's `active`;
    feedback and withdrawal only clear it). For the current plan concept: its
    items, minus everything the student has seen or had revealed, every hash
    already keyed in this session and the concept's post-test reserve (A23);
    the band's target difficulty; formats from `policy.practice_formats` (rotate
    by checks so far; generative free/teachback preferred on the segment-close
    check, W1.3). A concept with nothing servable advances the cursor and tries
    the next (at most once per remaining concept). No plan → None (teaching
    only). Writes no evidence and runs no model. An item the student reported
    (A113) is excluded like a seen or revealed one."""
    concept = state.get("concept")
    if not concept:
        return None
    excluded = _excluded_hashes(user_id, state)
    # spec §13 A140 / A141: the student's two varied-practice dials, read once
    # per activation; both off → every pick below is exactly the plain one
    varied, combos = varied_practice.varied_on(user_id), varied_practice.multi_concept_on(user_id)
    while True:
        item = learner = band = None
        items, exclude = _concept_pool(user_id, course_id, concept, excluded, state)
        if items:
            item, learner, band = _pick_item(
                user_id, course_id, state, concept, items, exclude, excluded,
                varied=varied, combos=combos, session_id=session_id,
            )
        if item is not None:
            return _open_step(user_id, state, concept, item, learner, band, now)
        if not _advance_cursor(state, no_items=True):
            return None
        concept = state["concept"]


#: The 503 detail when a goal session's practice pool cannot be read.
_PRACTICE_UNAVAILABLE = "Practice availability unavailable; retry"


def _excluded_hashes(user_id: str, state: dict) -> set:
    """Everything the student has seen, had revealed or reported (A23, A113),
    every hash already keyed in this session and (spec §13 A138) every item
    this session posed as a prequestion (empty with the flag off) — its
    answer is shown, or its stem was seen. A goal session's failed read is a
    503 (retry); otherwise it propagates."""
    try:
        return (
            seen_hashes(user_id)
            | revealed_hashes(user_id)
            | reported_hashes(user_id)
            | set(state.get("steps") or {})
            | prequestion_rules.session_hashes(state)
        )
    except Exception as exc:
        if state.get("goal"):
            raise HTTPException(status_code=503, detail=_PRACTICE_UNAVAILABLE) from exc
        raise


def _concept_pool(user_id: str, course_id: str, concept: str, excluded: set, state: dict):
    """`_practice_pool` for the concept; a goal session's failed read is a 503."""
    try:
        return _practice_pool(user_id, course_id, concept, excluded)
    except Exception as exc:
        if state.get("goal"):
            raise HTTPException(status_code=503, detail=_PRACTICE_UNAVAILABLE) from exc
        raise


def _pick_item(
    user_id: str,
    course_id: str,
    state: dict,
    concept: str,
    items: list,
    exclude: set,
    excluded: set,
    *,
    varied: bool,
    combos: bool,
    session_id: str | None,
):
    """(item or None, learner state, band) for a concept with items: the
    isomorph re-ask after an unknown (PKG-10), else a multi-concept item (A141),
    else the hinted item (W2.4b) or the band's target difficulty, format by
    format."""
    # A140: how familiar each item's surface is to the student on this
    # concept (met = seen, revealed, reported, posed this session)
    familiarity = (
        varied_practice.familiarity_for(course_id, items[0].concept_key, excluded)
        if varied
        else None
    )
    item = _isomorph_after_unknown(state, concept, items, exclude, familiarity=familiarity)
    learner = _learner_state(user_id, concept)
    band, _ = _band_of(learner)
    # W1.3: rotation + segment-close generative-core preference
    formats = policy.practice_formats(int(state.get("concept_checks") or 0))
    target = _target_difficulty(state, concept, band)
    if item is None and combos:
        # A141: the ideas-combined dial — a multi-concept item whose
        # apex is this concept, when its gate and the session dial allow
        item = varied_practice.multi_concept_pick(
            user_id, course_id, state, concept, items[0].concept_key,
            target=target, formats=formats, excluded=excluded,
        )
    # W2.4b: low-trust next-probe hint among already-eligible items.
    # Flag off → None (no decrypt, no-op). Flag on → open the latest
    # step reasoning_encrypted under the session bind and prefer();
    # a returned hash wins only if still eligible for this format pass.
    hint_qh = preferred_next_question_hash(
        user_id,
        None,
        tuple(
            (i.question_hash, i.prompt)
            for i in items
            if i.question_hash not in exclude
        ),
        session_id=session_id,
        state=state,
    )
    if item is None:
        item = _select_by_format(items, formats, hint_qh, target, exclude, familiarity)
    return item, learner, band


def _select_by_format(items: list, formats, hint_qh, target, exclude: set, familiarity):
    """Format by format: the hinted item when it is eligible in this format,
    else select_item at the target difficulty; the first hit wins."""
    for fmt in formats:
        if hint_qh:
            hinted = next(
                (
                    i
                    for i in items
                    if i.question_hash == hint_qh
                    and i.format == fmt
                    and i.question_hash not in exclude
                ),
                None,
            )
            if hinted is not None:
                return hinted
        item = select_item(
            items,
            format=fmt,
            difficulty=target,
            exclude_hashes=exclude,
            familiarity=familiarity,
        )
        if item is not None:
            return item
    return None


def _open_step(user_id: str, state: dict, concept: str, item, learner, band, now: float) -> str:
    """Make `item` the document's `current` and key its fresh step."""
    qh = item.question_hash
    state["current"] = qh
    step = {
        "rung": int(Rung.H0),
        "attempts": 0,
        "wrong": 0,
        "first_shown_at": now,
        "check_item_id": item.id,
        "node_id": concept,
        "feedback_given": False,
        # the H6 predicate (spec §3.3, A32): taught earlier in this session
        "taught": bool(state.get("teach_turns") or state.get("concept_checks")),
    }
    if is_multi_concept(item):
        # A141: counted by the session dial (one per concept a session)
        step[MULTI_CONCEPT_STEP_KEY] = True
    # spec §13 A122: a novice without the prerequisite (policy.attempt_first
    # says no) gets the worked example FIRST on the concept's first item of
    # the session; the item after it is the near-transfer, attempted
    view = _learner_view(
        learner, band=band, prereq_proficient=_prereq_proficient(user_id, concept)
    )
    if policy.opens_on_worked_example(
        view, shown_on_concept=_worked_example_shown(state, concept)
    ):
        step["worked_first"] = True
    if _take_retrieval_mark(state, concept):
        # A128: this step's teaching ran without its course material
        step[_RETRIEVAL_KEY] = _RETRIEVAL_FAILED_VALUE
    _steps(state)[qh] = step
    return qh


def _pose_payload(item, *, worked_first: bool = False) -> dict:
    """The check pose the client renders (A17: the prompt verbatim; A22: an
    mc_reason item's stored options, never rebuilt, never marked correct, no
    wrong_key). Never the reference. `worked_first` (spec §13 A122): the item
    opens on the worked example and it has not been unlocked yet — the client
    asks for it at once (/hint grants H4 with no attempt before it, the hint
    turn serves it); the key is present only when true. W4.4: `key_verified`
    is present only when `canonical_verified` (blind-key / audit already
    confirmed the key) — calm chrome only; never invent a second verifier."""
    options = None
    if item.format == _MC_REASON and item.options:
        options = [{"letter": o.letter, "text": o.text} for o in item.options]
    pose = {
        "question_hash": item.question_hash,
        "format": item.format,
        "difficulty": item.difficulty,
        "prompt": ladder.check_pose(item.prompt),
        "options": options,
    }
    if worked_first:
        pose["worked_first"] = True
    if item.canonical_verified:
        pose["key_verified"] = True  # W4.4: present only when true
    # W4.1a: visual surface with no drawable asset yet — honest withheld slot
    # (never invents a diagram). Stage B/SVG agent later; chrome is fail-closed.
    if getattr(item, "surface_representation", None) == "visual":
        pose["figure"] = {"status": "withheld"}
    return pose


def _worked_example_owed(user_id: str, state: dict, qh: str | None) -> bool:
    """Whether item `qh`'s next hint is its worked example (spec §13 A122): its
    step opened on it, is still below H4, and policy.worked_example_rung —
    re-read on the learner's state NOW — still grants it. Reads only for such a
    step (the common pose reads nothing more)."""
    entry = (state.get("steps") or {}).get(qh) if qh else None
    if not isinstance(entry, dict) or entry.get("worked_first") is not True:
        return False
    node_id = entry.get("node_id")
    if not node_id or int(entry.get("rung") or 0) >= int(Rung.H4):
        return False
    learner = _learner_state(user_id, node_id)
    band, _ = _band_of(learner)
    view = _learner_view(learner, band=band, prereq_proficient=_prereq_proficient(user_id, node_id))
    step = _step_state(state, qh)
    delta = _band_ceiling_delta(state, node_id)
    return policy.worked_example_rung(view, step, worked_first=True, band_delta=delta) is not None
