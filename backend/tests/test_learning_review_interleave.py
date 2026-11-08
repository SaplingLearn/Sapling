"""Spec §13 A114: confusable concepts are interleaved in the daily review queue.

The pure half (`learning/interleave.py`) is property-tested over seeded random
queues: the same multiset in and out, no adjacent repeats while avoidable,
unrelated items in DASH order, partners side by side, determinism, and replay
consistency (the per-request rebuild serves the same order). The review half
(`learning/review.py`) is tested with every table mocked: the reads, the
anchor, the same set and stats, and the route serving a sibling next."""

from __future__ import annotations

import copy
import functools
import itertools
import logging
import random
from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from learning import params
from learning.interleave import confusable_partners, serve_order

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
PAST = (NOW - timedelta(days=3)).isoformat()
USER = "user_interleave"
COURSE = "course-1"
OTHER = "course-2"


def _sym(*pairs) -> dict:
    """A symmetric partner map from (a, b) pairs."""
    out: dict = {}
    for a, b in pairs:
        out.setdefault(a, set()).add(b)
        out.setdefault(b, set()).add(a)
    return out


def _keys(keys, order) -> list:
    return [keys[i] for i in order]


# ── serve_order: worked examples ──────────────────────────────────────────────


def test_a_confusable_pair_is_pulled_side_by_side():
    keys = ["a", "x", "y", "b"]
    assert _keys(keys, serve_order(keys, _sym(("a", "b")))) == ["a", "b", "x", "y"]


def test_two_pairs_each_end_up_adjacent_and_the_rest_keeps_dash_order():
    keys = ["a", "x", "c", "b", "y", "d"]
    out = _keys(keys, serve_order(keys, _sym(("a", "b"), ("c", "d"))))
    assert out == ["a", "b", "x", "c", "d", "y"]


def test_a_sibling_family_is_served_as_one_run_in_dash_order():
    keys = ["p", "x", "q", "y", "r"]
    family = _sym(("p", "q"), ("p", "r"), ("q", "r"))
    assert _keys(keys, serve_order(keys, family)) == ["p", "q", "r", "x", "y"]


def test_no_partners_is_the_identity():
    keys = ["a", "b", "c", "d"]
    assert serve_order(keys, {}) == [0, 1, 2, 3]
    assert serve_order(keys, _sym(("z", "w"))) == [0, 1, 2, 3]  # partners not in the queue


def test_an_unrelated_head_keeps_its_place():
    keys = ["x", "a", "y", "b"]
    out = _keys(keys, serve_order(keys, _sym(("a", "b"))))
    assert out == ["x", "a", "b", "y"]


def test_the_previous_item_anchors_the_first_pick():
    keys = ["x", "y", "b"]
    out = _keys(keys, serve_order(keys, _sym(("a", "b")), previous="a"))
    assert out == ["b", "x", "y"]


def test_with_no_previous_the_dash_head_is_served_first():
    keys = ["x", "a", "b"]
    assert serve_order(keys, _sym(("a", "b")))[0] == 0


def test_the_concept_just_graded_is_never_served_again_first():
    keys = ["a", "x", "y"]
    assert _keys(keys, serve_order(keys, {}, previous="a")) == ["x", "a", "y"]
    # ... unless nothing else is left: the set never changes
    assert serve_order(["a"], {}, previous="a") == [0]


def test_repeated_keys_are_separated_when_they_can_be():
    keys = ["b", "a", "a", "a", "c"]  # a greedy walk would end "…a, a"
    out = _keys(keys, serve_order(keys, {}))
    assert out == ["a", "b", "a", "c", "a"]
    assert Counter(out) == Counter(keys)


def test_an_asymmetric_map_is_read_from_the_item_just_placed():
    keys = ["a", "x", "b"]
    assert _keys(keys, serve_order(keys, {"a": {"b"}})) == ["a", "b", "x"]
    assert _keys(keys, serve_order(keys, {"b": {"a"}})) == ["a", "x", "b"]


def test_empty_queue():
    assert serve_order([], {}) == []
    assert serve_order([], _sym(("a", "b")), previous="a") == []


# ── serve_order: properties over seeded random queues ─────────────────────────


def _random_case(rng: random.Random, *, unique: bool):
    n = rng.randint(0, 9)
    if unique:
        keys = [f"k{i}" for i in rng.sample(range(20), n)]
    else:
        keys = [f"k{rng.randint(0, 3)}" for _ in range(n)]
    universe = sorted(set(keys) | {f"k{i}" for i in range(20, 23)})
    pairs = [(a, b) for a, b in itertools.combinations(universe, 2) if rng.random() < 0.15]
    previous = rng.choice([None, *universe])
    return keys, _sym(*pairs), previous


CASES = [_random_case(random.Random(seed), unique=seed % 2 == 0) for seed in range(400)]
UNIQUE_CASES = [_random_case(random.Random(10_000 + s), unique=True) for s in range(300)]


def _no_repeat(seq, previous) -> bool:
    return all(a != b for a, b in zip([previous, *seq], seq))


def _feasible(keys, previous) -> bool:
    """Exhaustive search: does ANY arrangement of `keys` avoid a repeat (the
    first one included, against `previous`)? Independent of serve_order's rule."""
    distinct = sorted(set(keys))

    @functools.cache
    def arrange(counts: tuple, last) -> bool:
        if not any(counts):
            return True
        return any(
            n and k != last and arrange(counts[:i] + (n - 1,) + counts[i + 1 :], k)
            for i, (k, n) in enumerate(zip(distinct, counts))
        )

    return arrange(tuple(Counter(keys)[k] for k in distinct), previous)


def test_the_same_multiset_comes_out():
    for keys, partners, previous in CASES:
        order = serve_order(keys, partners, previous=previous)
        assert sorted(order) == list(range(len(keys))), (keys, previous, order)
        assert Counter(_keys(keys, order)) == Counter(keys)


def test_no_adjacent_repeat_while_one_can_be_avoided():
    checked = 0
    for keys, partners, previous in CASES:
        out = _keys(keys, serve_order(keys, partners, previous=previous))
        if _feasible(keys, previous):
            checked += 1
            assert _no_repeat(out, previous), (keys, previous, out)
    assert checked > len(CASES) // 2  # the oracle is not vacuous


def test_unrelated_items_keep_their_dash_order():
    for keys, partners, previous in UNIQUE_CASES:
        present = set(keys)
        near_previous = partners.get(previous, set())
        unrelated = [
            i
            for i, k in enumerate(keys)
            if not (partners.get(k, set()) & present) and k not in near_previous and k != previous
        ]
        order = serve_order(keys, partners, previous=previous)
        assert [i for i in order if i in unrelated] == unrelated, (keys, partners, previous)


def test_a_waiting_partner_always_comes_next_earliest_in_dash_order():
    pulled = 0
    for keys, partners, previous in UNIQUE_CASES:
        order = serve_order(keys, partners, previous=previous)
        for step, placed in enumerate(order):
            before = previous if step == 0 else keys[order[step - 1]]
            near = partners.get(before, set())
            waiting = sorted(i for i in order[step:] if keys[i] in near)
            if before is not None and waiting:
                pulled += 1
                assert placed == waiting[0], (keys, partners, previous, order)
    assert pulled > len(UNIQUE_CASES) // 2  # partners do occur in the generated queues


def test_replaying_one_serve_at_a_time_gives_the_same_order():
    """The route rebuilds the queue per request with the last graded item as
    `previous`; the order it serves is the order computed up front."""
    for keys, partners, previous in CASES:
        static = serve_order(keys, partners, previous=previous)
        remaining, last, served = list(range(len(keys))), previous, []
        while remaining:
            sub = [keys[i] for i in remaining]
            head = remaining[serve_order(sub, partners, previous=last)[0]]
            served.append(head)
            remaining.remove(head)
            last = keys[head]
        assert served == static, (keys, partners, previous)


def test_the_order_is_deterministic():
    for keys, partners, previous in CASES:
        first = serve_order(keys, partners, previous=previous)
        again = serve_order(list(keys), copy.deepcopy(partners), previous=previous)
        reordered = {k: frozenset(sorted(v, reverse=True)) for k, v in reversed(partners.items())}
        assert first == again == serve_order(keys, reordered, previous=previous)


# ── confusable_partners ───────────────────────────────────────────────────────


def test_siblings_are_partners():
    courses = {"a": COURSE, "b": COURSE, "c": COURSE}
    got = confusable_partners(courses, {"a": {"p"}, "b": {"p"}, "c": {"q"}}, {})
    assert got == {"a": frozenset({"b"}), "b": frozenset({"a"})}


def test_a_shared_open_wrong_key_makes_partners():
    courses = {"a": COURSE, "b": COURSE, "c": COURSE}
    got = confusable_partners(courses, {}, {"a": {"k1", "k2"}, "c": {"k2"}, "b": {"k3"}})
    assert got == {"a": frozenset({"c"}), "c": frozenset({"a"})}


def test_both_signals_union_and_the_relation_is_symmetric_and_irreflexive():
    courses = {n: COURSE for n in "abcd"}
    got = confusable_partners(courses, {"a": {"p"}, "b": {"p"}}, {"b": {"k"}, "c": {"k"}})
    assert got == {"a": {"b"}, "b": {"a", "c"}, "c": {"b"}}
    assert all(node not in others for node, others in got.items())
    assert all(node in got[other] for node, others in got.items() for other in others)


def test_another_courses_node_is_never_a_partner():
    courses = {"a": COURSE, "b": OTHER, "c": None, "d": None}
    parents = {n: {"p"} for n in courses}
    assert confusable_partners(courses, parents, {}) == {"c": {"d"}, "d": {"c"}}


def test_a_parent_and_its_child_are_not_partners_and_outsiders_are_ignored():
    courses = {"p": COURSE, "a": COURSE}
    got = confusable_partners(courses, {"a": {"p"}, "zz": {"p"}}, {"zz": {"k"}, "a": {"k"}})
    assert got == {}


# ── review.py: the queue ──────────────────────────────────────────────────────


def _tables(data: dict):
    handles: dict = {}

    def factory(name):
        if name not in handles:
            m = MagicMock(name=name)
            m.select.return_value = list(data.get(name, []))
            handles[name] = m
        return handles[name]

    return factory, handles


def _due(node_id):
    return {
        "node_id": node_id,
        "p_known": 0.9,
        "streak_unassisted": 0,
        "fsrs_d": 5.0,
        "fsrs_s": 1.0,
        "fsrs_last_review_at": PAST,
        "fsrs_due_at": PAST,
    }


def _card(card_id):
    return {
        "id": card_id,
        "topic": "T",
        "offering_id": None,
        "fsrs_d": 5.0,
        "fsrs_s": 1.0,
        "due_at": PAST,
        "reps": 0,
        "lapses": 0,
        "last_rating": None,
        "last_reviewed_at": PAST,
    }


def _check_item(key, course=COURSE):
    """A servable `free` item at the profic difficulty (p_known 0.9)."""
    return SimpleNamespace(
        id=f"ci-{key}",
        course_id=course,
        concept_key=key,
        format=params.REVIEW_FORMAT_BY_BAND["profic"],
        difficulty=params.REVIEW_DIFFICULTY_BY_BAND["profic"],
        question_hash=f"qh-{key}",
        created_at=None,
        final_answer="42",
        prompt=f"Explain {key}",
        options=None,
    )


def _edge(parent, child):
    return {"source_node_id": parent, "target_node_id": child}


@pytest.fixture
def queue_env(monkeypatch):
    """Due concepts (node id = concept key, lower case) and cards, served in the
    DASH order `rank` names; graph_edges / misconceptions come from the test."""
    from learning import review

    monkeypatch.setattr(review, "seen_hashes", lambda user_id: set())
    monkeypatch.setattr(review, "revealed_hashes", lambda user_id: set())
    monkeypatch.setattr(review, "reported_hashes", lambda user_id: set())  # spec §13 A113
    monkeypatch.setattr(review, "posttest_reserves", lambda items: frozenset())
    monkeypatch.setattr(review, "decayed_p", lambda p, elapsed, s: p)
    monkeypatch.setattr(review, "user_offering_ids_for_course", lambda u, c: ["off-1"])
    monkeypatch.setattr(
        review, "list_items", lambda course_id, key, **kw: [_check_item(key, course_id)]
    )
    wrong_reads: list = []

    def build(rank, *, courses=None, edges=(), wrong=(), edge_error=None):
        courses = courses or {}
        concepts = [k for k in rank if not k.startswith("f")]
        cards = [k for k in rank if k.startswith("f")]
        factory, handles = _tables(
            {
                "flashcards": [_card(c) for c in cards],
                "learner_state": [_due(n) for n in concepts],
                "graph_nodes": [
                    {"id": n, "course_id": courses.get(n, COURSE), "concept_name": n.upper()}
                    for n in concepts
                ],
                "graph_edges": [_edge(p, c) for p, c in edges],
            }
        )
        monkeypatch.setattr(review, "table", factory)
        if edge_error is not None:
            factory("graph_edges").select.side_effect = edge_error

        def open_for(user_id, node_ids):
            wrong_reads.append(sorted(node_ids))
            return [{"node_id": n, "wrong_key": k, "count": 1} for n, k in wrong]

        monkeypatch.setattr(review, "open_for", open_for)
        position = {k: i for i, k in enumerate(rank)}
        monkeypatch.setattr(
            review,
            "_order",
            lambda entries, now: sorted(
                entries,
                key=lambda e: position[e.node["id"] if isinstance(e, review._Concept) else e.id],
            ),
        )
        return handles, wrong_reads

    return build


def _served(queue) -> list[str]:
    return [i.node_id if i.kind == "check" else i.id for i in queue]


def test_prerequisite_siblings_are_served_side_by_side(queue_env):
    from learning import review

    handles, _ = queue_env(["a", "x", "b"], edges=[("p", "a"), ("p", "b"), ("q", "x")])
    queue, stats = review.due_queue_with_stats(USER, COURSE, NOW)
    assert _served(queue) == ["a", "b", "x"]
    # one graph_edges read: prerequisite edges INTO the queued concepts
    (call,) = handles["graph_edges"].select.call_args_list
    filters = call.kwargs["filters"]
    assert filters["relationship_type"] == "eq.prerequisite"
    assert filters["user_id"] == f"eq.{USER}"
    assert filters["target_node_id"] == 'in.("a","b","x")'  # EDGE_PREREQ_SOURCE_IS_PREREQ
    assert stats["in_budget"] == 3


def test_concepts_sharing_an_open_wrong_key_are_served_side_by_side(queue_env):
    from learning import review

    _, wrong_reads = queue_env(
        ["a", "x", "b"], wrong=[("a", "confuses_a_with_b"), ("b", "confuses_a_with_b")]
    )
    assert _served(review.due_queue(USER, COURSE, NOW)) == ["a", "b", "x"]
    assert wrong_reads == [["a", "b", "x"]]


def test_interleaving_never_changes_the_set_the_budget_or_the_stats(queue_env):
    from learning import review

    rank = ["a", "f1", "x", "f2", "c", "b", "y", "d", "f3"]
    queue_env(rank, edges=[("p", "a"), ("p", "b")], wrong=[("c", "k"), ("d", "k")])
    plain, plain_stats = review.due_queue_with_stats(USER, COURSE, NOW, interleave=False)
    mixed, mixed_stats = review.due_queue_with_stats(USER, COURSE, NOW)
    assert _served(plain) == rank  # DASH order, budget cut
    assert _served(mixed) == ["a", "b", "f1", "x", "f2", "c", "d", "y", "f3"]
    assert Counter(_served(mixed)) == Counter(_served(plain))
    assert sum(i.cost_s for i in mixed) == sum(i.cost_s for i in plain)
    assert mixed_stats == plain_stats


def test_the_budget_cut_happens_before_the_reorder(queue_env):
    """A partner past the budget is never pulled in."""
    from learning import review

    queue_env(["a", "x", "b"], edges=[("p", "a"), ("p", "b")])
    budget = params.REVIEW_DAILY_BUDGET_MIN * 60
    spent = budget - 2 * params.REVIEW_SECONDS_PER_CHECK
    queue, stats = review.due_queue_with_stats(
        USER, COURSE, NOW, loop_state={"review": {"spent_s": spent}}
    )
    assert _served(queue) == ["a", "x"] and stats["due"]["check"] == 3


def test_flashcards_and_unrelated_concepts_keep_their_dash_order(queue_env):
    from learning import review

    rank = ["f1", "x", "a", "f2", "y", "b", "f3"]
    queue_env(rank, edges=[("p", "a"), ("p", "b")])
    out = _served(review.due_queue(USER, COURSE, NOW))
    assert out == ["f1", "x", "a", "b", "f2", "y", "f3"]
    unrelated = [k for k in rank if k not in ("a", "b")]
    assert [k for k in out if k in unrelated] == unrelated


def test_another_courses_sibling_is_not_pulled_in_a_course_less_queue(queue_env):
    from learning import review

    queue_env(["a", "x", "b"], courses={"b": OTHER}, edges=[("p", "a"), ("p", "b")])
    assert _served(review.due_queue(USER, None, NOW)) == ["a", "x", "b"]


def test_the_last_graded_concept_anchors_the_next_build(queue_env):
    """After `a` is graded (and no longer due), its sibling is served next,
    ahead of the DASH head — the pair stays side by side across the rebuild."""
    from learning import review

    handles, wrong_reads = queue_env(["x", "y", "b"], edges=[("p", "a"), ("p", "b")])
    state = {"review": {"last_graded": {"key": "a", "course_id": COURSE}}}
    assert _served(review.due_queue(USER, COURSE, NOW, loop_state=state)) == ["b", "x", "y"]
    (call,) = handles["graph_edges"].select.call_args_list
    assert call.kwargs["filters"]["target_node_id"] == 'in.("a","b","x","y")'
    assert wrong_reads == [["a", "b", "x", "y"]]


def test_a_course_less_anchor_pairs_only_within_its_course(queue_env):
    from learning import review

    queue_env(["x", "b"], courses={"b": OTHER}, edges=[("p", "a"), ("p", "b")])
    state = {"review": {"last_graded": {"key": "a", "course_id": COURSE}}}
    assert _served(review.due_queue(USER, None, NOW, loop_state=state)) == ["x", "b"]


def test_the_concept_just_graded_is_not_served_first_again(queue_env):
    from learning import review

    queue_env(["a", "x"])
    state = {"review": {"last_graded": {"key": "a", "course_id": COURSE}}}
    assert _served(review.due_queue(USER, COURSE, NOW, loop_state=state)) == ["x", "a"]


def test_a_flashcard_anchor_reads_nothing_and_keeps_dash_order(queue_env):
    from learning import review

    handles, wrong_reads = queue_env(["f1", "x", "f2"])
    state = {"review": {"last_graded": {"key": "fc:f9", "course_id": COURSE}}}
    assert _served(review.due_queue(USER, COURSE, NOW, loop_state=state)) == ["f1", "x", "f2"]
    assert "graph_edges" not in handles and wrong_reads == []


def test_a_resolved_misconception_no_longer_pairs_concepts(queue_env, monkeypatch):
    """Spec §13 A127: the interleave reads PKG-10's open_for, which a resolved
    row leaves — once the student closes the shared key on one concept, the two
    concepts are no longer confusable and DASH order returns."""
    from learning import misconceptions, review
    from tests.test_learning_confidence_resolve import UNASSISTED, FakeMisconceptions

    queue_env(["a", "x", "b"])
    seen = NOW.isoformat()
    fake = FakeMisconceptions(
        [
            {"id": f"m-{n}", "user_id": USER, "node_id": n, "check_item_id": f"ci-{n}",
             "wrong_key": "confuses_a_with_b", "count": 1, "last_seen_at": seen,
             "resolved_at": None}
            for n in ("a", "b")
        ]
    )
    monkeypatch.setattr(misconceptions, "table", lambda name: fake)
    monkeypatch.setattr(misconceptions, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(review, "open_for", misconceptions.open_for)  # the real reader
    monkeypatch.setattr(misconceptions, "_utcnow", lambda: NOW)
    assert _served(review.due_queue(USER, COURSE, NOW)) == ["a", "b", "x"]
    closed = misconceptions.resolve_after_grade(
        USER, "a", keys=["confuses_a_with_b"], item_id="ci-a2", attempt=UNASSISTED,
        surface="review",
    )
    assert closed == ["confuses_a_with_b"]
    assert _served(review.due_queue(USER, COURSE, NOW)) == ["a", "x", "b"]


def test_no_interleave_reads_when_no_two_concepts_could_pair(queue_env):
    from learning import review

    handles, wrong_reads = queue_env(["f1", "a", "f2"])
    assert _served(review.due_queue(USER, COURSE, NOW)) == ["f1", "a", "f2"]
    assert "graph_edges" not in handles and wrong_reads == []


def test_a_failed_edge_read_keeps_dash_order(queue_env, caplog):
    from learning import review

    queue_env(["a", "x", "b"], edge_error=RuntimeError("down"))
    with caplog.at_level(logging.WARNING, logger="sapling.learning.review"):
        assert _served(review.due_queue(USER, COURSE, NOW)) == ["a", "x", "b"]
    assert "prerequisite edges unread (RuntimeError)" in caplog.text


def test_the_summary_makes_no_interleave_read(queue_env):
    from learning import review

    handles, wrong_reads = queue_env(["a", "x", "b"], edges=[("p", "a"), ("p", "b")])
    out = review.summary(USER, COURSE, NOW, loop_state={}, retention=0.9)
    assert out["in_budget"] == 3
    assert "graph_edges" not in handles and wrong_reads == []


# ── review.py: the anchor is written by the grade record ──────────────────────


def _review_item(kind, **kw):
    from learning.review import ReviewItem

    base = dict(
        kind=kind,
        id=kw.pop("id"),
        course_id=COURSE,
        r=0.5,
        stability=params.FSRS_S0_GOOD,
        cost_s=params.REVIEW_SECONDS_PER_CHECK,
        sr_stage="acquire",
        sr_target=params.SR_INITIAL_CRITERION,
    )
    base.update(kw)
    return ReviewItem(**base)


def test_a_grade_records_the_anchor_and_a_lost_claim_does_not():
    from learning import review

    doc: dict = {}
    check = _review_item("check", id="ci-a", node_id="a")
    review._apply_grade(doc, check, correct=True, session_id="s", retention=0.9)
    assert doc["review"]["last_graded"] == {"key": "a", "course_id": COURSE}
    card = _review_item("flashcard", id="f1", course_id=None)
    review._apply_grade(doc, card, correct=False, session_id="s", retention=0.9)
    assert doc["review"]["last_graded"] == {"key": "fc:f1", "course_id": None}
    # a record whose claim no longer holds writes nothing — the anchor included
    held = {"open": {"a": {"item_id": "ci-a", "claim": "other"}}}
    assert (
        review._apply_grade(held, check, correct=True, session_id="s", retention=0.9, claim="mine")
        is None
    )
    assert "review" not in held


def test_the_anchor_survives_the_session_view():
    from learning import review

    stored = {"review": {"spent_s": 45, "last_graded": {"key": "a", "course_id": COURSE}}}
    view = review._session_view(stored)
    assert review._last_graded(view) == {"key": "a", "course_id": COURSE}
    for malformed in ("a", {"key": ["a"]}, {"key": ""}, {"course_id": COURSE}, None):
        assert review._last_graded({"review": {"last_graded": malformed}}) == {}, malformed
    assert review._last_graded({}) == {} and review._last_graded(None) == {}


# ── the route: /review/next serves the sibling of the concept just graded ─────


def test_review_next_serves_the_sibling_of_the_concept_just_graded(queue_env, monkeypatch):
    from fastapi.testclient import TestClient

    from learning import review
    from learning.loop_state_store import LoadedLoopState
    from learning.policy import LoopState
    from main import app

    queue_env(["x", "y", "b"], edges=[("p", "a"), ("p", "b")])
    state = {
        "sr": {},
        "review": {
            "spent_s": 45,
            "served_hashes": ["qh-a"],
            "last_graded": {"key": "a", "course_id": COURSE},
        },
    }
    sid = review.review_session_id(USER, COURSE, NOW)
    saved = LoopState(extra=copy.deepcopy(state))

    def store(session_id, mutate):
        replaced = mutate(saved)
        return LoadedLoopState(replaced or saved, 1)

    monkeypatch.setattr(review, "update_loop_state", store)
    # the REAL loader reads the stored document (spec §13 A115: never a hand-built view)
    monkeypatch.setattr(
        review,
        "_read_session",
        lambda s, u: [{"id": s, "user_id": u, "loop_state": saved.to_json()}],
    )
    monkeypatch.setattr(review, "review_retention", lambda u, c: params.FSRS_RETENTION_DEFAULT)
    monkeypatch.setattr(review, "log_event", lambda *a, **kw: None)
    monkeypatch.setattr("routes.learn_loop._review_now", lambda: NOW)
    monkeypatch.setattr("routes.learn_loop._pause_novice", lambda user_id: False)
    monkeypatch.setattr("routes.learn_loop.user_offering_ids_for_course", lambda u, c: ["off-1"])
    monkeypatch.setattr(
        "routes.learn_loop.get_check_item", lambda item_id: _check_item(item_id.removeprefix("ci-"))
    )
    with (
        patch("routes.learn_loop.require_self", return_value=None),
        patch("routes.learn_loop.learning_loop_for_request", return_value=True),
    ):
        r = TestClient(app).get(f"/api/learn/loop/review/next?user_id={USER}&course_id={COURSE}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["item"]["node_id"] == "b" and body["in_budget"] == 3
    assert body["session_id"] == sid  # the real loader derived today's session
    assert saved.extra["open"]["b"]["item_id"] == "ci-b"


# ── A114 × A113 (× A115): a reported item is never an interleave partner ──────


def _pool_with_a_second_item(monkeypatch, key: str) -> None:
    """`key`'s pool holds its own item — the selector's first choice (the lowest
    id at the same format and difficulty) — and a second one, `ci-{key}2`."""
    from learning import review

    def list_items(course_id, concept_key, **kw):
        items = [_check_item(concept_key, course_id)]
        if concept_key == key:
            items.append(_check_item(f"{key}2", course_id))
        return items

    monkeypatch.setattr(review, "list_items", list_items)


def test_a_reported_item_never_comes_back_as_an_interleave_partner(queue_env, monkeypatch):
    """The sibling of the concept just graded comes next (A114), and an item the
    student reported is never served again (A113). The interleave only orders
    what the selector chose, so the partner comes next with ANOTHER item —
    whether the reported one was its first choice or the item the session has
    open for it — and with nothing else left the partner is unservable: never
    pulled forward, and the DASH order holds."""
    from learning import review

    queue_env(["x", "y", "b"], edges=[("p", "a"), ("p", "b")])
    _pool_with_a_second_item(monkeypatch, "b")
    anchored = {"review": {"last_graded": {"key": "a", "course_id": COURSE}}}
    opened = {**anchored, "open": {"b": {"item_id": "ci-b", "served_at": NOW.timestamp() - 60}}}

    def queue(state):
        items, stats = review.due_queue_with_stats(
            USER, COURSE, NOW, loop_state=copy.deepcopy(state)
        )
        return [(i.node_id, i.id) for i in items], stats

    # unreported (the control): the partner is pulled forward with its first choice
    assert queue(anchored)[0] == [("b", "ci-b"), ("x", "ci-x"), ("y", "ci-y")]
    assert queue(opened)[0] == [("b", "ci-b"), ("x", "ci-x"), ("y", "ci-y")]
    monkeypatch.setattr(review, "reported_hashes", lambda user_id: {"qh-b"})
    assert queue(anchored)[0] == [("b", "ci-b2"), ("x", "ci-x"), ("y", "ci-y")]
    assert queue(opened)[0] == [("b", "ci-b2"), ("x", "ci-x"), ("y", "ci-y")]
    # nothing else left for the partner: unservable, the rest keeps its DASH order
    monkeypatch.setattr(
        review, "list_items", lambda course_id, key, **kw: [_check_item(key, course_id)]
    )
    order, stats = queue(opened)
    assert order == [("x", "ci-x"), ("y", "ci-y")]
    assert stats["unservable"] == 1 and stats["in_budget"] == 2


def test_review_next_never_re_serves_a_reported_open_item_as_the_partner(
    queue_env, monkeypatch
):
    """Through the route and the REAL loader: the session graded `a`, then served
    its sibling `b` (open, unanswered). Since A115 the view carries "open", so a
    refresh re-serves that item — the partner, first (A114) — with no write.
    Once the student reports it on another surface (the loop's check card, which
    leaves the review entry in place), `b` still comes next, with its other item,
    opened in place of the reported one (A113)."""
    from fastapi.testclient import TestClient

    from learning import review
    from learning.loop_state_store import LoadedLoopState
    from learning.policy import LoopState
    from main import app

    queue_env(["x", "y", "b"], edges=[("p", "a"), ("p", "b")])
    _pool_with_a_second_item(monkeypatch, "b")
    reported: set[str] = set()
    monkeypatch.setattr(review, "reported_hashes", lambda user_id: set(reported))
    saved = LoopState(
        extra={
            "sr": {},
            "review": {
                "spent_s": 45,
                "served_hashes": ["qh-a", "qh-b"],
                "last_graded": {"key": "a", "course_id": COURSE},
            },
            "open": {"b": {"item_id": "ci-b", "served_at": NOW.timestamp() - 60}},
        }
    )
    writes: list[str] = []

    def store(session_id, mutate):
        writes.append(session_id)
        replaced = mutate(saved)
        return LoadedLoopState(replaced or saved, 1)

    monkeypatch.setattr(review, "update_loop_state", store)
    monkeypatch.setattr(
        review,
        "_read_session",
        lambda s, u: [{"id": s, "user_id": u, "loop_state": saved.to_json()}],
    )
    monkeypatch.setattr(review, "review_retention", lambda u, c: params.FSRS_RETENTION_DEFAULT)
    monkeypatch.setattr(review, "log_event", lambda *a, **kw: None)
    monkeypatch.setattr("routes.learn_loop._review_now", lambda: NOW)
    monkeypatch.setattr("routes.learn_loop._pause_novice", lambda user_id: False)
    monkeypatch.setattr("routes.learn_loop.user_offering_ids_for_course", lambda u, c: ["off-1"])
    monkeypatch.setattr(
        "routes.learn_loop.get_check_item", lambda item_id: _check_item(item_id.removeprefix("ci-"))
    )

    def served() -> dict:
        with (
            patch("routes.learn_loop.require_self", return_value=None),
            patch("routes.learn_loop.learning_loop_for_request", return_value=True),
        ):
            r = TestClient(app).get(f"/api/learn/loop/review/next?user_id={USER}&course_id={COURSE}")
        assert r.status_code == 200, r.text
        return r.json()["item"]

    first = served()
    assert (first["node_id"], first["id"]) == ("b", "ci-b") and writes == []  # re-served
    reported.add("qh-b")
    moved = served()
    assert (moved["node_id"], moved["id"]) == ("b", "ci-b2")
    assert saved.extra["open"]["b"]["item_id"] == "ci-b2" and len(writes) == 1
