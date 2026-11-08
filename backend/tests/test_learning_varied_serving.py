"""Varied practice on the serving side (learning-loop spec §13 A140, A141).

A140, the cue-familiarity dial (flag `varied_isomorphs`): every picker that
chooses the next item on a concept — in-session activation, the isomorph
re-ask, review — prefers, AFTER its own rules and A129's quality order, an item
whose surface the student has not met on the concept; an item without a
descriptor ranks in the middle; with the flag off every pick is f9eca612's.
The review interleave never pairs a definitional (recall-or-definition) item
with the flag on, and is A114's order with it off.

A141, the ideas-combined dial (flag `multi_concept_items`): a concept's next
in-session check may pose a multi-concept item whose apex is the concept —
once a session, after a check graded on it, while its difficulty is at the
top, never in a goal session, and only when every component is proficient;
its answer is a partial observation on the apex.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from learning import params
from learning.checks import CheckItem, RubricItem, WrongReason, select_item, serve_quality
from learning.multi_concept import SEP, STEP_KEY, combo_key
from learning.surface import Surface
from tests.test_learn_loop_routes import ITEM, NOW, _iso, _plan_state, _unknown_attempt
from tests.test_learn_loop_routes import seams as seams  # the loop routes' fixture

T = "2026-11-01T00:00:00+00:00"


def _item(qh, fmt="free", difficulty=2, *, verified=False, lint=None, created=T, concept="k1"):
    return CheckItem(
        id=f"id-{qh}",
        course_id="c1",
        concept_key=concept,
        format=fmt,
        difficulty=difficulty,
        prompt=f"Question {qh}?",
        reference_answer=f"Because {qh}. Final answer: {qh} result.",
        rubric=[RubricItem(id="r1", text="states it")],
        common_wrong=[WrongReason(key="w", text="a wrong idea")],
        source_chunk_ids=["ch"],
        question_hash=qh,
        final_answer=f"{qh} result",
        canonical_verified=verified,
        lint_flags=lint,
        created_at=created,
    )


# ── A140: select_item ────────────────────────────────────────────────────────


def _f9eca612_select_item(items, *, format, difficulty, exclude_hashes=()):
    """checks.select_item exactly as f9eca612 shipped it (the reference)."""
    from learning.checks import is_servable

    excluded = set(exclude_hashes)
    candidates = [
        i for i in items if i.format == format and i.question_hash not in excluded and is_servable(i)
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda i: (
            abs(i.difficulty - difficulty),
            i.difficulty,
            *serve_quality(i),
            i.created_at or "",
            i.id,
        ),
    )


def test_select_item_without_familiarity_is_f9eca612s_pick_on_any_bank():
    rng = random.Random(140)
    for _ in range(600):
        bank = [
            _item(
                f"q{n}",
                rng.choice(params.CHECK_ITEM_FORMATS),
                rng.choice(params.CHECK_ITEM_DIFFICULTIES),
                verified=rng.random() < 0.4,
                lint=rng.choice([None, [], ["correct_longest"], ["unsourced"], ["key_disputed"]]),
                created=f"2026-11-0{rng.randint(1, 9)}T00:00:00+00:00",
            )
            for n in range(rng.randint(0, 12))
        ]
        exclude = {i.question_hash for i in bank if rng.random() < 0.3}
        fmt = rng.choice(params.CHECK_ITEM_FORMATS)
        difficulty = rng.choice(params.CHECK_ITEM_DIFFICULTIES)
        assert select_item(
            bank, format=fmt, difficulty=difficulty, exclude_hashes=exclude
        ) == _f9eca612_select_item(bank, format=fmt, difficulty=difficulty, exclude_hashes=exclude)
        assert select_item(
            bank, format=fmt, difficulty=difficulty, exclude_hashes=exclude, familiarity=None
        ) == _f9eca612_select_item(bank, format=fmt, difficulty=difficulty, exclude_hashes=exclude)


def test_familiarity_breaks_only_the_ties_difficulty_and_quality_leave():
    older = _item("old", created="2026-09-01T00:00:00+00:00")
    newer = _item("new", created="2026-11-05T00:00:00+00:00")
    fam = {"old": 2, "new": 0}
    assert select_item([older, newer], format="free", difficulty=2) is older  # age, flag off
    assert select_item([older, newer], format="free", difficulty=2, familiarity=fam) is newer
    # never over the difficulty target
    near = _item("near", difficulty=2)
    far = _item("far", difficulty=3)
    assert select_item([near, far], format="free", difficulty=2, familiarity={"near": 2, "far": 0}) is near
    # never over A129's quality order
    verified = _item("v", verified=True)
    plain = _item("p")
    assert select_item([verified, plain], format="free", difficulty=2, familiarity={"v": 2, "p": 0}) is verified
    # never over the format (the channel) or an exclusion
    other_format = _item("t", fmt="teachback")
    assert select_item([older, other_format], format="free", difficulty=2, familiarity={"old": 2, "t": 0}) is older
    assert select_item([older, newer], format="free", difficulty=2, exclude_hashes={"new"}, familiarity=fam) is older


def test_an_item_the_map_does_not_list_ranks_as_an_unknown_surface():
    known_new = _item("a", created="2026-11-05T00:00:00+00:00")
    unlisted = _item("b", created="2026-09-01T00:00:00+00:00")
    known_met = _item("c", created="2026-08-01T00:00:00+00:00")
    fam = {"a": 0, "c": 2}
    assert select_item([unlisted, known_met, known_new], format="free", difficulty=2, familiarity=fam) is known_new
    assert select_item([unlisted, known_met], format="free", difficulty=2, familiarity=fam) is unlisted


# ── A140: the isomorph re-ask ────────────────────────────────────────────────


def _unknown_state(qh="last"):
    return {"attempts": [{**_unknown_attempt(qh), "node_id": "node-1"}]}


def test_the_isomorph_re_ask_prefers_the_least_familiar_surface_among_equals():
    from routes.learn_loop import _isomorph_after_unknown

    last = _item("last")
    a = _item("iso-a", created="2026-09-01T00:00:00+00:00")
    b = _item("iso-b", created="2026-11-05T00:00:00+00:00")
    items = [last, a, b]
    assert _isomorph_after_unknown(_unknown_state(), "node-1", items, {"last"}) is a  # flag off
    fam = {"last": 2, "iso-a": 2, "iso-b": 0}
    assert _isomorph_after_unknown(_unknown_state(), "node-1", items, {"last"}, familiarity=fam) is b
    # quality still comes first
    verified = _item("iso-v", verified=True)
    fam["iso-v"] = 2
    assert (
        _isomorph_after_unknown(_unknown_state(), "node-1", [*items, verified], {"last"}, familiarity=fam)
        is verified
    )


# ── A140: in-session activation ──────────────────────────────────────────────


def test_flag_off_activation_reads_no_surface_and_picks_as_before(seams, monkeypatch):
    from routes.learn_loop import _activate_next_item
    from services import varied_practice

    surfaces = MagicMock()
    monkeypatch.setattr("services.check_item_service.concept_surfaces", surfaces)
    monkeypatch.setattr(varied_practice, "varied_on", lambda u: False)
    monkeypatch.setattr(varied_practice, "multi_concept_on", lambda u: False)
    old = _iso("qh-old")
    new = _iso("qh-new").model_copy(update={"created_at": "2026-11-05T00:00:00+00:00"})
    old = old.model_copy(update={"created_at": "2026-09-01T00:00:00+00:00"})
    seams.list_items.return_value = [new, old]
    st = _plan_state()
    assert _activate_next_item("u1", "c1", st, now=NOW) == "qh-old"
    surfaces.assert_not_called()
    assert seams.select_item.call_args.kwargs["familiarity"] is None


def test_varied_activation_prefers_the_surface_the_student_has_not_met(seams, monkeypatch):
    from routes.learn_loop import _activate_next_item
    from services import varied_practice

    monkeypatch.setattr(varied_practice, "varied_on", lambda u: True)
    monkeypatch.setattr(varied_practice, "multi_concept_on", lambda u: False)
    seen = _iso("qh-seen")
    old = _iso("qh-old").model_copy(update={"created_at": "2026-09-01T00:00:00+00:00"})
    new = _iso("qh-new").model_copy(update={"created_at": "2026-11-05T00:00:00+00:00"})
    seams.list_items.return_value = [seen, new, old]
    seams.seen_hashes.return_value = {"qh-seen"}
    surfaces = {
        "qh-seen": Surface("applied", "library"),
        "qh-old": Surface("applied", "library"),  # the met surface again
        "qh-new": Surface("numeric", "phone contacts"),
    }
    calls = []

    def concept_surfaces(course_id, key):
        calls.append((course_id, key))
        return surfaces

    monkeypatch.setattr("services.check_item_service.concept_surfaces", concept_surfaces)
    st = _plan_state()
    assert _activate_next_item("u1", "c1", st, now=NOW) == "qh-new"
    assert calls == [("c1", "recursion")]
    assert seams.select_item.call_args.kwargs["familiarity"] == {"qh-seen": 2, "qh-old": 2, "qh-new": 0}


def test_a_failed_surface_read_keeps_the_plain_order(seams, monkeypatch):
    from routes.learn_loop import _activate_next_item
    from services import varied_practice

    monkeypatch.setattr(varied_practice, "varied_on", lambda u: True)
    monkeypatch.setattr(varied_practice, "multi_concept_on", lambda u: False)
    monkeypatch.setattr(
        "services.check_item_service.concept_surfaces", MagicMock(side_effect=RuntimeError("down"))
    )
    old = _iso("qh-old").model_copy(update={"created_at": "2026-09-01T00:00:00+00:00"})
    new = _iso("qh-new").model_copy(update={"created_at": "2026-11-05T00:00:00+00:00"})
    seams.list_items.return_value = [new, old]
    assert _activate_next_item("u1", "c1", _plan_state(), now=NOW) == "qh-old"


# ── A140: review ─────────────────────────────────────────────────────────────


def _review_pick(monkeypatch, pool, *, seen=(), band="develop", varied=False, surfaces=None):
    from learning import review

    monkeypatch.setattr(review, "list_items", lambda *_a: pool)
    monkeypatch.setattr(review, "seen_hashes", lambda _u: set(seen))
    monkeypatch.setattr(review, "revealed_hashes", lambda _u: set())
    monkeypatch.setattr(review, "reported_hashes", lambda _u: set())
    reads = MagicMock(return_value=surfaces or {})
    monkeypatch.setattr("services.check_item_service.concept_surfaces", reads)
    selector = review._Selector("u1", served_today=set(), opened={}, varied=varied)
    concept = review._Concept(
        node={"id": "n1", "course_id": "c1", "concept_name": "k1"},
        row={"streak_unassisted": 0},
        stability=1.0,
        last_review_at=None,
        band=band,
    )
    picked = selector.item(concept, datetime(2026, 11, 8, tzinfo=timezone.utc))
    return (picked.question_hash if picked is not None else None), reads


def test_review_prefers_an_unmet_surface_in_its_fallback_pass_only_with_the_flag(monkeypatch):
    """Every item is seen, so the fallback pass serves a seen one: with the
    flag on, the one whose surface the student met least."""
    reserve = _item("f2", "free", 2)  # the post-test reserve (A23): never a review pick
    a = _item("a", "mc_reason", 2, created="2026-09-01T00:00:00+00:00")
    b = _item("b", "mc_reason", 2, created="2026-11-05T00:00:00+00:00")
    surfaces = {"a": Surface("applied", "x"), "b": None, "c": Surface("applied", "x")}
    pool = [reserve, a, b]
    picked, reads = _review_pick(monkeypatch, pool, seen={"a", "b", "c"})
    assert picked == "a" and not reads.called  # flag off: the oldest, nothing read
    # with the flag: b's unknown surface (1) before a's met one (2)
    picked, reads = _review_pick(monkeypatch, pool, seen={"a", "b", "c"}, varied=True, surfaces=surfaces)
    assert picked == "b" and reads.call_args.args == ("c1", "k1")
    # a seen item's own surface is met: once b states one, both are fully met
    # (2) and the oldest serves — a re-serve never pretends to vary the cues
    surfaces["b"] = Surface("visual", "y")
    picked, _ = _review_pick(monkeypatch, pool, seen={"a", "b", "c"}, varied=True, surfaces=surfaces)
    assert picked == "a"


def test_review_novelty_and_difficulty_still_come_first(monkeypatch):
    reserve = _item("f2", "free", 2)
    unseen = _item("u", "mc_reason", 2)
    seen_new_surface = _item("s", "mc_reason", 2)
    surfaces = {"u": Surface("applied", "x"), "s": Surface("visual", "y"), "z": Surface("applied", "x")}
    picked, _ = _review_pick(
        monkeypatch, [reserve, unseen, seen_new_surface], seen={"s", "z"}, varied=True, surfaces=surfaces
    )
    assert picked == "u"  # the strict pass (unseen) before any surface preference


# ── A140 × A114: no interleaving for definitional items ─────────────────────


def _queue(*specs):
    from learning.review import ReviewItem

    out = []
    for node, difficulty in specs:
        out.append(
            ReviewItem(
                kind="check",
                id=f"i-{node}",
                node_id=node,
                course_id="c1",
                question_hash=f"q-{node}",
                due_at=None,
                last_review_at=None,
                r=0.5,
                stability=1.0,
                format="free",
                difficulty=difficulty,
                cost_s=params.REVIEW_SECONDS_PER_CHECK,
                sr_stage="acquire",
                sr_target=3,
                sr_count=0,
            )
        )
    return out


def _interleaved(monkeypatch, queue, last=None, *, varied):
    from learning import review

    # a, b and c share the prerequisite parent p (siblings: confusable)
    monkeypatch.setattr(
        review, "_prerequisite_parents", lambda u, nodes: {n: {"p"} for n in nodes if n in "abc"}
    )
    monkeypatch.setattr(review, "open_for", lambda u, nodes: [])
    state = {"review": {"last_graded": last}} if last else {}
    return [i.node_id for i in review._interleaved("u1", queue, state, varied=varied)]


def test_the_interleave_is_a114s_with_the_flag_off(monkeypatch):
    queue = _queue(("a", 1), ("x", 2), ("b", 2), ("y", 2), ("c", 1))
    # A114 pulls a's sibling b (a definitional a included) right after a
    assert _interleaved(monkeypatch, queue, varied=False) == ["a", "b", "c", "x", "y"]


def test_a_definitional_item_is_never_pulled_forward_nor_pulls_one(monkeypatch):
    # a (difficulty 1) heads the queue but pairs with nothing; b and c (2, 3) pair
    queue = _queue(("a", 1), ("x", 2), ("b", 2), ("y", 2), ("c", 3))
    assert _interleaved(monkeypatch, queue, varied=True) == ["a", "x", "b", "c", "y"]
    # a definitional sibling is never pulled after a non-definitional one
    queue = _queue(("b", 2), ("x", 2), ("a", 1), ("c", 2))
    assert _interleaved(monkeypatch, queue, varied=True) == ["b", "c", "x", "a"]
    assert _interleaved(monkeypatch, queue, varied=False) == ["b", "a", "c", "x"]


def test_a_definitional_anchor_pairs_nothing(monkeypatch):
    queue = _queue(("x", 2), ("b", 2))
    anchor = {"key": "a", "course_id": "c1", "difficulty": 1}
    assert _interleaved(monkeypatch, queue, anchor, varied=True) == ["x", "b"]
    assert _interleaved(monkeypatch, queue, anchor, varied=False) == ["b", "x"]
    # an anchor graded with the flag off carries no difficulty: A114's anchor
    assert _interleaved(monkeypatch, queue, {"key": "a", "course_id": "c1"}, varied=True) == ["b", "x"]
    applied = {"key": "a", "course_id": "c1", "difficulty": 2}
    assert _interleaved(monkeypatch, queue, applied, varied=True) == ["b", "x"]


def test_the_graded_anchor_records_its_difficulty_only_with_the_flag():
    from learning.review import _apply_grade

    (item,) = _queue(("a", 1))
    doc: dict = {}
    _apply_grade(doc, item, correct=True, session_id="s", retention=0.9)
    assert doc["review"]["last_graded"] == {"key": "a", "course_id": "c1"}
    doc = {}
    _apply_grade(doc, item, correct=True, session_id="s", retention=0.9, varied=True)
    assert doc["review"]["last_graded"] == {"key": "a", "course_id": "c1", "difficulty": 1}


# ── A141: the multi-concept pick ─────────────────────────────────────────────

APEX, PRE, PRE2 = "learning rate", "gradient descent", "loss"


def _combo(qh, fmt="free", comps=(APEX, PRE), **over):
    return _item(qh, fmt, params.MULTI_CONCEPT_DIFFICULTY, concept=combo_key(list(comps)), **over)


def _pick(monkeypatch, combos, *, steps=None, goal=False, target=3, states=None, excluded=(), formats=("free", "teachback", "mc_reason")):
    from services import varied_practice

    monkeypatch.setattr("services.check_item_service.multi_concept_items", lambda c, k: combos)
    default = {k: (0.97, 1) for k in (APEX, PRE, PRE2)}
    monkeypatch.setattr(
        varied_practice,
        "_component_states",
        lambda u, c, keys: {
            k: varied_practice.ComponentState(*v) for k, v in (states or default).items() if k in keys
        },
    )
    state = {"steps": steps if steps is not None else {"q0": {"node_id": "n-apex", "graded_at": 1.0}}}
    if goal:
        state["goal"] = {"x": 1}
    return varied_practice.multi_concept_pick(
        "u1", "c1", state, "n-apex", APEX, target=target, formats=list(formats), excluded=set(excluded)
    )


def test_the_pick_serves_a_combination_when_the_dial_and_the_gate_allow(monkeypatch):
    pair, triple = _combo("pair"), _combo("triple", comps=(APEX, PRE, PRE2))
    assert _pick(monkeypatch, [triple, pair]) is pair  # two ideas before three
    assert _pick(monkeypatch, [triple]) is triple
    # the session's format rotation
    tb = _combo("tb", "teachback")
    assert _pick(monkeypatch, [pair, tb], formats=("teachback", "free", "mc_reason")) is tb


@pytest.mark.parametrize(
    "case",
    ["nothing graded yet", "not at the top", "goal session", "already posed", "met", "held"],
)
def test_the_dial_and_the_exclusions_close_the_pick(monkeypatch, case):
    pair = _combo("pair")
    kwargs: dict = {}
    combos = [pair]
    if case == "nothing graded yet":
        kwargs["steps"] = {}
    elif case == "not at the top":
        kwargs["target"] = 2
    elif case == "goal session":
        kwargs["goal"] = True
    elif case == "already posed":
        kwargs["steps"] = {
            "q0": {"node_id": "n-apex", "graded_at": 1.0},
            "q1": {"node_id": "n-apex", STEP_KEY: True},
        }
    elif case == "met":
        kwargs["excluded"] = {"pair"}
    elif case == "held":
        combos = [_combo("pair", lint=["key_disputed"])]
    assert _pick(monkeypatch, combos, **kwargs) is None


@pytest.mark.parametrize(
    "states",
    [
        {APEX: (0.97, 1), PRE: (params.MULTI_CONCEPT_GATE_P - 0.01, 3)},  # a component not proficient
        {APEX: (0.97, 1), PRE: (0.99, 0)},  # proficient but unconfirmed (A110 c)
        {APEX: (0.97, 1)},  # no node for a component
    ],
)
def test_the_gate_closes_the_pick(monkeypatch, states):
    assert _pick(monkeypatch, [_combo("pair")], states=states) is None


def test_a_failed_read_gives_no_combination(monkeypatch):
    from services import varied_practice

    monkeypatch.setattr(
        "services.check_item_service.multi_concept_items", MagicMock(side_effect=RuntimeError("x"))
    )
    state = {"steps": {"q0": {"node_id": "n-apex", "graded_at": 1.0}}}
    assert (
        varied_practice.multi_concept_pick(
            "u1", "c1", state, "n-apex", APEX, target=3, formats=["free"], excluded=set()
        )
        is None
    )


def test_flag_off_activation_never_reads_a_combination(seams, monkeypatch):
    from routes.learn_loop import _activate_next_item
    from services import varied_practice

    pick = MagicMock()
    monkeypatch.setattr(varied_practice, "multi_concept_pick", pick)
    monkeypatch.setattr(varied_practice, "varied_on", lambda u: False)
    monkeypatch.setattr(varied_practice, "multi_concept_on", lambda u: False)
    seams.list_items.return_value = [_iso("qh-a")]
    assert _activate_next_item("u1", "c1", _plan_state(), now=NOW) == "qh-a"
    pick.assert_not_called()


def test_multi_concept_activation_poses_the_combination_and_marks_its_step(seams, monkeypatch):
    from routes.learn_loop import _activate_next_item
    from services import varied_practice

    combo = _combo("qh-combo")
    calls = []

    def pick(user_id, course_id, state, node_id, apex_key, *, target, formats, excluded):
        calls.append((node_id, apex_key, target, list(formats)))
        return combo

    monkeypatch.setattr(varied_practice, "multi_concept_pick", pick)
    monkeypatch.setattr(varied_practice, "varied_on", lambda u: False)
    monkeypatch.setattr(varied_practice, "multi_concept_on", lambda u: True)
    seams.list_items.return_value = [_iso("qh-a")]
    st = _plan_state()
    assert _activate_next_item("u1", "c1", st, now=NOW) == "qh-combo"
    step = st["steps"]["qh-combo"]
    assert step[STEP_KEY] is True and step["node_id"] == "node-1" and step["check_item_id"] == combo.id
    assert calls == [("node-1", "recursion", 2, ["free", "teachback", "mc_reason"])]
    # an isomorph re-ask after `unknown` keeps precedence (A122 (b))
    seams.list_items.return_value = [_iso("qh-1"), _iso("qh-2")]
    st = _plan_state(attempts=[_unknown_attempt()])
    calls.clear()
    assert _activate_next_item("u1", "c1", st, now=NOW) == "qh-2"
    assert calls == []


# ── A141: evidence on the apex ───────────────────────────────────────────────


def test_a_multi_concept_observation_is_a_partial_one_either_way():
    from learning.evidence import Evidence, evidence_weight

    for correct in (True, False):
        base = Evidence(node_id="n", channel="free_response", correct=correct)
        multi = Evidence(node_id="n", channel="free_response", correct=correct, multi_concept=True)
        assert base.weight == 1.0
        assert multi.weight == params.WEIGHT_MULTI_CONCEPT == evidence_weight(multi)
    # it multiplies the other factors
    low = Evidence(node_id="n", channel="free_response", correct=False, confidence=0.1, multi_concept=True)
    assert low.weight == params.WEIGHT_LOW_CONFIDENCE * params.WEIGHT_MULTI_CONCEPT
    # a correct answer after H4..H6 is still no upward evidence
    worked = Evidence(node_id="n", channel="free_response", correct=True, max_rung=4, multi_concept=True)
    assert worked.weight == 0.0


def test_the_flag_is_dumped_only_when_set_so_every_other_dict_is_as_before():
    from learning.evidence import Evidence
    from learning.evidence_transaction import fingerprint

    plain = Evidence(node_id="n", channel="free_response", correct=True)
    assert "multi_concept" not in plain.model_dump()
    assert "multi_concept" not in plain.model_dump(mode="json")
    multi = Evidence(node_id="n", channel="free_response", correct=True, multi_concept=True)
    dumped = multi.model_dump()
    assert dumped["multi_concept"] is True
    # a sealed checkpoint's dict round-trips the flag, and so the weight
    assert Evidence.model_validate(dumped).weight == params.WEIGHT_MULTI_CONCEPT
    # an older checkpoint without the key reads as before
    assert Evidence.model_validate(plain.model_dump()).multi_concept is False
    assert fingerprint("u", "c", [plain], None) != fingerprint("u", "c", [multi], None)


def test_grade_answer_records_a_multi_concept_answer_on_the_apex_at_the_partial_weight(monkeypatch):
    import asyncio

    from agents.deps import SaplingDeps
    from agents.tools import check as check_tool
    from agents.tools.check import CheckAnswer, grade_answer

    monkeypatch.setattr(check_tool, "apply_misconception_rule", _no_rule)
    item = _combo("qh-combo")
    deps = SaplingDeps(user_id="u1", course_id="c1", supabase=None, request_id="r", learning_loop=True)
    out = asyncio.run(
        grade_answer(
            item,
            CheckAnswer(question_hash="qh-combo", idk=True),
            deps=deps,
            node_id="n-apex",
            multi_concept=True,
        )
    )
    (row,) = deps.pending_evidence
    assert row["node_id"] == "n-apex" and row["multi_concept"] is True
    assert row["weight"] == params.WEIGHT_MULTI_CONCEPT and out.correct is False
    deps = SaplingDeps(user_id="u1", course_id="c1", supabase=None, request_id="r", learning_loop=True)
    asyncio.run(grade_answer(ITEM, CheckAnswer(question_hash="qh-1", idk=True), deps=deps, node_id="n"))
    (row,) = deps.pending_evidence
    assert "multi_concept" not in row and row["weight"] == 1.0


async def _no_rule(deps, *, item, grade, evidence, confront):
    return "none"


def test_a_combinations_node_is_its_apex(monkeypatch):
    from routes.learn_loop import _node_for_item

    rows = [
        {"id": "n-pre", "concept_name": "Gradient  Descent"},
        {"id": "n-apex", "concept_name": "Learning Rate"},
    ]
    table = MagicMock()
    table.return_value.select.return_value = rows
    monkeypatch.setattr("routes.learn_loop.table", table)
    assert _node_for_item("u1", _combo("q")) == "n-apex"
    assert _node_for_item("u1", _item("q", concept="gradient descent")) == "n-pre"
    assert SEP not in _item("q", concept="gradient descent").concept_key


def test_posing_a_combination_logs_served_and_a_single_item_logs_nothing(monkeypatch):
    from services import varied_practice

    logged = MagicMock()
    monkeypatch.setattr(varied_practice, "log_event", logged)
    varied_practice.note_posed("u1", "s1", _item("q"))
    logged.assert_not_called()
    varied_practice.note_posed("u1", "s1", _combo("qc", "teachback", comps=(APEX, PRE, PRE2)))
    (call,) = logged.call_args_list
    assert call.args == ("learn.multi_concept_served",)
    assert call.kwargs["category"] == "usage" and call.kwargs["user_id"] == "u1"
    assert call.kwargs["payload"] == {
        "course_id": "c1",
        "question_hash": "qc",
        "components": 3,
        "format": "teachback",
        "session_id": "s1",
    }
    from services.events_service import EVENT_TAXONOMY

    assert "learn.multi_concept_served" in EVENT_TAXONOMY


def test_the_component_states_are_the_students_decayed_beliefs(monkeypatch):
    from learning.learner_state import LearnerState
    from services import varied_practice

    table = MagicMock()
    table.return_value.select.return_value = [
        {"id": "n-apex", "concept_name": "Learning Rate"},
        {"id": "n-pre", "concept_name": "Gradient Descent"},
        {"id": "n-other", "concept_name": "Other"},
    ]
    monkeypatch.setattr("db.connection.table", table)
    reads = []

    def read_states(user_id, node_ids, now=None):
        reads.append(sorted(node_ids))
        return {"n-apex": LearnerState(user_id=user_id, node_id="n-apex", p_known=0.96, n_strong_unassisted=2)}

    monkeypatch.setattr(varied_practice, "read_states", read_states)
    out = varied_practice._component_states("u1", "c1", {APEX, PRE})
    assert reads == [["n-apex", "n-pre"]]
    assert out == {APEX: varied_practice.ComponentState(0.96, 2)}  # n-pre has no state row


def test_the_multi_concept_read_keeps_only_unheld_combinations(monkeypatch):
    from services.check_item_service import multi_concept_items

    table = MagicMock()
    table.return_value.select.return_value = []
    monkeypatch.setattr("services.check_item_service.table", table)
    assert multi_concept_items("c1", APEX) == []
    kwargs = table.return_value.select.call_args.kwargs
    assert kwargs["filters"] == {"course_id": "eq.c1", "apex_key": f"eq.{APEX}"}
