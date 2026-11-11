"""The check cursor: the leak-checked pose payload, the H6 gate and the
cursor's advance with its reason.
"""
from __future__ import annotations

from learning import gates, ladder
from learning.checks import posttest_reserves, serve_quality
from learning.goals import attempted_nodes
from learning.ladder import Rung
from learning.leak import detect_leak
from learning.misconceptions import set_confront
from learning.params import LOOP_SOURCE_CHUNKS_MAX
from services.check_item_service import list_items
from services.quiz_ask import QUIZ_ASK_ORIGIN
from services.rag_service import chunks_for_ids

from services.loop.state import _item_like, _step_state


def _auto_poses_checks(state: dict) -> bool:
    """Spec §13 A121: whether a teach turn may pose the concept's next check
    itself (A27 trigger 1). Not in a quiz-ask session (A99): its surface, the
    quiz's "Ask about this" sheet, shows no check card, so a check posed there
    would be an invisible second prompt that answers the student's next
    message with its pose. "Check me" still poses one wherever a card shows."""
    return state.get("origin") != QUIZ_ASK_ORIGIN


def _h6_ok(state: dict, qh: str | None, item_state: dict, check) -> bool:
    """Spec §3.3 H6 item predicates (§13 A32), for the one gate PKG-06 owns:
    taught (recorded at activation), practice (the ACTIVE in-session check;
    activation never selects the post-test reserve), not graded coursework (a
    missing item fails closed). Ungraded alone never admits H6."""
    return gates.h6_allowed(
        _step_state(state, qh),
        item_taught=bool((item_state or {}).get("taught")),
        item_practice=qh is not None and state.get("current") == qh,
        item_graded=check is None or bool(check.graded),
    )


def _leak_checked_payload(*, user_id: str, item, rung: Rung, reference: str | None) -> tuple:
    """A17: the deterministic H2/H4/H6 payload for `rung`, leak-checked HERE,
    in the same function, before anything can emit it (invariant 27; A34: the
    active item's structured final answer). Returns (payload | None, leaked).
    H2 passages are resolved for the requesting student through the
    visibility-aware reader; H4 never shows the concept's post-test reserve
    (A23, HANDOFF-06), so the concept's items are read whole — the reserve is
    defined over all of them — and ladder.deterministic_content keeps the
    siblings of the item's format and difficulty."""
    passages: list[str] = []
    if rung == Rung.H2:
        ids = list(item.source_chunk_ids or [])[:LOOP_SOURCE_CHUNKS_MAX]
        passages = [r["chunk_text"] for r in chunks_for_ids(ids, user_id=user_id)] if ids else []
    siblings: list = []
    reserves: frozenset[str] = frozenset()
    if rung == Rung.H4:
        concept_items = list_items(item.course_id, item.concept_key)
        reserves = posttest_reserves(concept_items)  # A23, A126: both protected items
        # spec §13 A129: deterministic_content shows the FIRST isomorph left, so
        # the siblings go best-first — a confirmed key (the worked example IS
        # its solution), then clean, never-linted, flagged; ties keep the
        # bank's (created_at, id) order (a stable sort)
        siblings = sorted(
            (s for s in concept_items if s.question_hash != item.question_hash),
            key=serve_quality,
        )
    payload = ladder.deterministic_content(
        rung,
        _item_like(item),
        [_item_like(s) for s in siblings],
        passages,
        exclude_hashes=reserves,
    )
    if payload is None:
        return None, False
    verdict = detect_leak(
        reference=reference or "",
        emitted=payload.text,
        rung=rung,
        final_answer=item.final_answer,
        canonical_answer=item.canonical_answer,
        correct_option=item.correct_option,
    )
    return payload, verdict.leaked


#: Spec §13 A121 (`loop_tutor_v2`): why the plan's cursor is on its current
#: concept, as a v2 teach turn tells the tutor (agents.loop_tutor
#: .PLAN_FOCUS_REASONS words each one). Read off loop state, never off text.
CURSOR_REASONS = ("plan_order", "prerequisite_repair", "wheelspin_moved", "isomorph_reask")


#: The two reasons a cursor MOVE records (`mark_cursor_reason`); "plan_order"
#: is the default and "isomorph_reask" is read off the attempt log.
_MOVE_REASONS = ("prerequisite_repair", "wheelspin_moved")


#: The `plan` key that records why a move that is not plan order put the
#: cursor where it is; `_advance_cursor` (plan order) clears it.
CURSOR_REASON_KEY = "cursor_reason"


def _advance_cursor(state: dict, *, no_items: bool = False) -> bool:
    """Move the plan (PKG-08's `plan = {approved, cursor}`) to its next concept,
    resetting the concept's counters; past the end the plan is done and there is
    no current concept. False when there is no next concept (or no plan)."""
    plan = state.get("plan")
    if not isinstance(plan, dict):
        return False
    plan.pop(CURSOR_REASON_KEY, None)  # spec §13 A121: a plan-order move
    set_confront(state, None)  # PKG-10 (F2): a marker never outlives its concept
    approved = list(plan.get("approved") or [])
    if state.get("goal") and state.get("concept"):
        # A finite session frontier is an attempt, not proof of proficiency.
        plan["attempted"] = list(dict.fromkeys([*attempted_nodes(state), state["concept"]]))
        if not no_items:
            plan["checked_nodes"] = list(dict.fromkeys([*(plan.get("checked_nodes") or []), state["concept"]]))
        else:
            plan["practice_unavailable_node_ids"] = list(dict.fromkeys([
                *(plan.get("practice_unavailable_node_ids") or []), state["concept"],
            ]))
    plan["cursor"] = int(plan.get("cursor") or 0) + 1
    if plan["cursor"] >= len(approved):
        plan["done"] = True
        state.pop("concept", None)
        return False
    state["concept"] = approved[plan["cursor"]]
    state["teach_turns"] = 0
    state["concept_checks"] = 0
    return True
