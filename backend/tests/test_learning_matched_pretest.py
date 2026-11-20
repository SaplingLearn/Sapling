"""Spec §13 A130: the matched pretest probe start, behind the
`probe_matched_pretest` flag (off by default).

A concept's FIRST graded evidence is its anchor and, when the probe graded it,
its pretest (A112); the delayed post-test then poses the protected reserve
that best matches that pretest item (A126, `item_match`). Left to its own
first-item rule the probe asks a new student a teachback item at difficulty 1
while the reserves sit at difficulty 2, so most pairs are unmatched. With the
flag on, the first item on a concept with no graded evidence yet is the
concept's pretest form (`checks.pretest_form`): a non-reserve item parallel to
the reserves — the same format and difficulty, else the same difficulty —
ranked by A129's quality order.

Pure: `pretest_form` and the probe's `pretest_forms`. Route: the flag (off is
byte-identical), the anchors read, the practice reserve, the fallbacks. And
the report the spec row quotes: what `item_match` looks like on the E2E seed
with the flag off and on."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.tools.check import CHANNEL_FOR_FORMAT
from learning import params
from learning.checks import (
    CheckItem,
    RubricItem,
    WrongReason,
    choose_posttest_item,
    posttest_reserve_hashes,
    pretest_form,
    pretest_match,
)
from tests.test_learning_probe_planner import LOOP, NEXT, client, probe  # noqa: F401  (fixture)
from tests.split_patches import patch_loop, setattr_loop
import learning.probe

FMT = {"f": "free", "t": "teachback", "m": "mc_reason"}


def _item(qh, fmt="free", difficulty=2, *, verified=False, lint=None, final_answer="the answer"):
    return CheckItem(
        id=f"id-{qh}",
        course_id="c1",
        concept_key="k1",
        format=fmt,
        difficulty=difficulty,
        prompt=f"Question {qh}?",
        reference_answer="A reference.",
        rubric=[RubricItem(id="r1", text="states it")],
        common_wrong=[WrongReason(key="w", text="a wrong idea")],
        source_chunk_ids=["ch"],
        question_hash=qh,
        final_answer=final_answer,
        canonical_verified=verified,
        lint_flags=lint,
    )


def _grid(*without, **extra):
    """The drafter's full bank — one item per (format, difficulty), hashes
    'f1' … 'm3' — minus `without`, plus `extra`."""
    items = {f"{f}{d}": _item(f"{f}{d}", FMT[f], d) for f in "ftm" for d in (1, 2, 3)}
    for qh in without:
        items.pop(qh)
    items.update(extra)
    return list(items.values())


def _hash(item):
    return item.question_hash if item is not None else None


# ── the pretest form (pure) ──────────────────────────────────────────────────


def test_the_matches_a_form_may_have_are_the_same_cell_then_the_same_difficulty():
    assert params.PRETEST_FORM_MATCHES == ("exact", "difficulty")
    assert set(params.PRETEST_FORM_MATCHES) <= set(params.POSTTEST_ITEM_MATCHES)


def test_a_full_bank_has_no_exact_form_so_the_form_matches_both_reserves_difficulty():
    """One item per cell, and the reserves take theirs (f2, m2): the one item
    left at the reserves' difficulty is the teachback one."""
    grid = _grid()
    assert posttest_reserve_hashes(grid) == ("f2", "m2")
    form = pretest_form(grid)
    assert _hash(form) == "t2"
    assert {pretest_match(r, form) for r in (grid[1], grid[7])} == {"difficulty"}


def test_a_duplicate_in_a_reserve_cell_is_an_exact_form():
    """A second mc_reason item at difficulty 2: m2 stays the reserve (the
    parallel form A126 protects), m2b is exact to it and difficulty-matched to
    f2 — better than t2, difficulty-matched to both."""
    grid = _grid(m2b=_item("m2b", "mc_reason", 2))
    assert posttest_reserve_hashes(grid) == ("f2", "m2")
    assert _hash(pretest_form(grid)) == "m2b"


def test_a_cell_both_reserves_share_needs_a_third_item_for_an_exact_form():
    """Two free items at difficulty 2 are both reserves (A126: the same cell
    when the pool holds two there); a third is exact to both."""
    two = _grid(f2b=_item("f2b", "free", 2))
    assert posttest_reserve_hashes(two) == ("f2", "f2b")
    assert _hash(pretest_form(two)) in {"t2", "m2"}  # difficulty-matched only
    three = _grid(f2b=_item("f2b", "free", 2), f2c=_item("f2c", "free", 2))
    assert _hash(pretest_form(three)) == "f2c"
    assert pretest_match(two[1], pretest_form(three)) == "exact"


def test_quality_then_the_strong_channel_order_break_equal_matches():
    # A129: a confirmed key first, then the lint tier
    grid = _grid(t2b=_item("t2b", "teachback", 2, verified=True, lint=["negative_stem"]))
    assert _hash(pretest_form(grid)) == "t2b"
    flagged = _grid("t2", t2=_item("t2", "teachback", 2, lint=["correct_longest"]), t2b=_item("t2b", "teachback", 2, lint=[]))
    assert _hash(pretest_form(flagged)) == "t2b"
    # a bank too small for a second reserve: f2 alone; m2 and t2 both match its
    # difficulty — the strong channel (mc_reason) first (POSTTEST_RESERVE_FORMATS)
    small = [_item(qh, FMT[qh[0]], int(qh[1])) for qh in ("f2", "t2", "m2", "f1", "t1")]
    assert posttest_reserve_hashes(small) == ("f2",)
    assert _hash(pretest_form(small)) == "m2"


def test_a_form_is_never_a_reserve_excluded_unservable_or_held():
    grid = _grid()
    assert pretest_form(grid, excluded={"t2"}) is None  # format-only or no match left
    no_answer = _grid("t2", t2=_item("t2", "teachback", 2, final_answer=None))
    assert pretest_form(no_answer) is None  # A34: never servable
    held = _grid("t2", t2=_item("t2", "teachback", 2, lint=["key_disputed"]))
    assert pretest_form(held) is None  # A124: a held key is never served
    assert pretest_form([]) is None  # no bank, no reserve
    for qh in posttest_reserve_hashes(grid):
        assert _hash(pretest_form(grid)) != qh


def test_a_format_only_match_is_no_parallel_form():
    """The six-item seed shape with nothing left at difficulty 2 but the
    reserve: free items at 1 and 3 only share its format — no form."""
    bank = [_item(qh, FMT[qh[0]], int(qh[1])) for qh in ("f1", "f2", "f3", "t1", "t3")]
    assert posttest_reserve_hashes(bank) == ("f2",)
    assert pretest_form(bank) is None


# ── the probe's pretest_forms (pure) ─────────────────────────────────────────


def _bound(item, node="n1"):
    from services.loop.planning import _BoundItem

    return _BoundItem(item, node)


def _next(states, items, **kw):
    from learning import probe as probe_policy

    return probe_policy.next_probe_item(states, items, kw.pop("asked", []), channel_for_format=CHANNEL_FOR_FORMAT, **kw)


def _observation(node, qh, *, graded=True):
    return {
        "node_id": node, "question_hash": qh, "difficulty": 1, "channel": "teachback_llm",
        "correct": True, "idk": False, "p_after": 0.4, "independent": True,
        **({} if graded else {"unavailable": True, "graded": False}),
    }


def test_the_form_replaces_the_first_item_heuristic():
    bank = [_bound(i) for i in _grid() if i.question_hash not in ("f2", "m2")]
    heuristic = _next({"n1": params.BKT_L0}, bank)
    assert heuristic.question_hash == "t1"  # a new student: teachback at difficulty 1
    steered = _next({"n1": params.BKT_L0}, bank, pretest_forms={"n1": "t2"})
    assert steered.question_hash == "t2"


def test_strand_fairness_and_the_caps_stand():
    a = [_bound(_item(f"a-{qh}", FMT[qh[0]], int(qh[1])), "n1") for qh in ("t1", "t2")]
    b = [_bound(_item(f"b-{qh}", FMT[qh[0]], int(qh[1])), "n2") for qh in ("t1", "t2")]
    # n1 has one (ungraded) observation, n2 none: the least-observed strand goes first
    picked = _next(
        {"n1": params.BKT_L0, "n2": params.BKT_L0},
        a + b,
        pretest_forms={"n1": "a-t2"},
        history=[_observation("n1", "gone", graded=False)],
    )
    assert picked.node_id == "n2"


def test_a_strand_with_a_graded_answer_is_never_steered():
    bank = [_bound(_item(qh, FMT[qh[0]], int(qh[1]))) for qh in ("t1", "t2", "t3", "f1")]
    history = [_observation("n1", "gone")]
    graded = _next({"n1": params.BKT_L0}, bank, pretest_forms={"n1": "t2"}, history=history)
    unsteered = _next({"n1": params.BKT_L0}, bank, history=history)
    assert graded is unsteered and graded.question_hash != "t2"
    # an ungraded answer (the grader was unavailable) wrote no evidence: still steered
    ungraded = _next(
        {"n1": params.BKT_L0},
        bank,
        pretest_forms={"n1": "t2"},
        history=[_observation("n1", "gone", graded=False)],
    )
    assert ungraded.question_hash == "t2"


def test_a_form_that_is_no_candidate_falls_back_to_the_heuristic():
    bank = [_bound(_item(qh, FMT[qh[0]], int(qh[1]))) for qh in ("t1", "t2")]
    asked = _next({"n1": params.BKT_L0}, bank, pretest_forms={"n1": "t2"}, asked=["t2"])
    assert asked.question_hash == "t1"
    absent = _next({"n1": params.BKT_L0}, bank, pretest_forms={"n1": "elsewhere"})
    assert absent.question_hash == "t1"


def test_graded_strands():
    from learning.probe import graded_strands

    history = [_observation("n1", "a"), _observation("n2", "b", graded=False), {"junk": True}]
    assert graded_strands(history) == frozenset({"n1"})


# ── the route ────────────────────────────────────────────────────────────────


def test_the_flag_is_server_only_off_first_and_off_unconfigured(monkeypatch):
    """Off until an admin turns it on (no migration seeds a row): the
    measurement protocol changes only at a trial boundary."""
    from services import feature_flags as ff
    from services.loop.planning import PROBE_MATCHED_PRETEST_FLAG

    monkeypatch.delenv("SAPLING_FLAG_PROBE_MATCHED_PRETEST", raising=False)
    fd = ff.REGISTRY[PROBE_MATCHED_PRETEST_FLAG]
    assert fd.variants == ("off", "on") and not fd.client_visible
    assert ff.flag_on(PROBE_MATCHED_PRETEST_FLAG, "u1") is False


def _flag(on: bool):
    """routes.learn_loop.flag_on with only the A130 flag answered."""

    def flag_on(key, user_id):
        assert key == "probe_matched_pretest", key
        return on

    return flag_on


def _bank(node="A"):
    """The full grid bound to `node` (the route's binding)."""
    from tests.test_learning_probe_planner import _ci

    return [_ci(f"{node}-{qh}", node, FMT[qh[0]], int(qh[1]), qh) for f in "ftm" for d in (1, 2, 3) for qh in [f"{f}{d}"]]


@pytest.fixture
def one_strand(probe):  # noqa: F811
    probe.full = _bank("A")
    probe.states.return_value = {"A": params.BKT_L0}
    probe.edges.return_value = []
    return probe


def test_flag_off_is_byte_identical(one_strand, monkeypatch):
    """Off: no anchors read, no form computed, the probe called exactly as
    before A130 — and the item and the saved document are the heuristic's."""

    anchors = MagicMock(side_effect=AssertionError("the anchors are never read with the flag off"))
    form = MagicMock(side_effect=AssertionError("no pretest form with the flag off"))
    setattr_loop(monkeypatch, "posttest_anchors", anchors)
    setattr_loop(monkeypatch, "pretest_form", form)
    setattr_loop(monkeypatch, "flag_on", _flag(False))
    with patch.object(learning.probe, "next_probe_item", wraps=learning.probe.next_probe_item) as nxt:
        body = client.post(f"{LOOP}/probe/next", json=NEXT).json()
    assert "pretest_forms" not in nxt.call_args.kwargs
    assert body["question_hash"] == "t1"  # the band heuristic's first item for a new student
    doc = one_strand.store["doc"]["probe"]
    assert doc["practice_reserves"] == {"A": max({"f1", "f3", "t1", "t2", "t3", "m1", "m3"})}


def test_flag_on_asks_the_pretest_form_first(one_strand, monkeypatch):

    anchors = MagicMock(return_value=([], False))
    setattr_loop(monkeypatch, "posttest_anchors", anchors)
    setattr_loop(monkeypatch, "flag_on", _flag(True))
    body = client.post(f"{LOOP}/probe/next", json=NEXT).json()
    assert body["question_hash"] == "t2"  # parallel (same difficulty) to both reserves
    anchors.assert_called_once_with(user_id="u1")
    pr = one_strand.store["doc"]["probe"]
    assert pr["practice_reserves"]["A"] != "t2"  # teaching keeps another fresh item
    # answered and graded: the strand's next item is the heuristic's again, and
    # with every skill graded the anchors are not read at all
    pr["history"].append({**pr["current"], "correct": True, "idk": False, "p_after": 0.5})
    pr["current"] = None
    anchors.reset_mock()
    with patch.object(learning.probe, "next_probe_item", wraps=learning.probe.next_probe_item) as nxt:
        client.post(f"{LOOP}/probe/next", json=NEXT)
    anchors.assert_not_called()
    assert "pretest_forms" not in nxt.call_args.kwargs


def test_an_anchored_concept_is_not_steered(one_strand, monkeypatch):
    """Evidence from before this probe (an earlier session, a quiz) already
    anchors the concept: its pretest is fixed, so the heuristic stands."""

    setattr_loop(monkeypatch, "posttest_anchors", MagicMock(return_value=([{"node_id": "A"}], False)))
    setattr_loop(monkeypatch, "flag_on", _flag(True))
    assert client.post(f"{LOOP}/probe/next", json=NEXT).json()["question_hash"] == "t1"


def test_an_unread_anchor_steers_nothing(one_strand, monkeypatch, caplog):

    setattr_loop(monkeypatch, "posttest_anchors", MagicMock(side_effect=RuntimeError("db down")))
    setattr_loop(monkeypatch, "flag_on", _flag(True))
    with caplog.at_level("WARNING"):
        assert client.post(f"{LOOP}/probe/next", json=NEXT).json()["question_hash"] == "t1"
    assert any("no matched pretest" in r.getMessage() for r in caplog.records)


def test_teaching_keeps_the_form_when_it_is_the_only_fresh_item(one_strand, monkeypatch):
    """The practice reserve predates the flag: with nothing but the form fresh,
    teaching keeps it and the probe falls back to what is left."""

    setattr_loop(monkeypatch, "posttest_anchors", MagicMock(return_value=([], False)))
    setattr_loop(monkeypatch, "flag_on", _flag(True))
    others = {"f1", "f3", "t1", "t3", "m1", "m3"}
    one_strand.seen.return_value = others  # seen elsewhere: the probe's second pass only
    body = client.post(f"{LOOP}/probe/next", json=NEXT).json()
    assert one_strand.store["doc"]["probe"]["practice_reserves"] == {"A": "t2"}
    assert body["question_hash"] in others


# ── the E2E seed: item_match with the flag off and on ────────────────────────


def _seed_bank():
    """The rich seed's loop concepts (db/seed_local_rich.py: three concepts,
    free and teachback at every difficulty), through the real seed code and
    the real decrypt boundary, bound to the loop user's nodes."""
    from db import seed_helpers
    from db import seed_local_rich as seed
    from services.loop.planning import _BoundItem
    from services.check_item_service import _row_to_item
    from services.graph_service import _normalize_concept

    rows: dict[str, list[dict]] = {}

    class _T:
        def __init__(self, name):
            self.name = name

        def select(self, *_a, **_k):
            return []

        def upsert(self, row, on_conflict=None):
            rows.setdefault(self.name, []).append(row)

        insert = upsert

    with patch.object(seed_helpers, "table", _T), patch.object(seed, "table", _T), patch.object(
        seed, "_admin_role_id", lambda: None
    ):
        seed_helpers.reset_counts()
        seed.seed_learning_loop()
    node_for = {
        _normalize_concept(name): seed.loop_node_id(seed.USER_LOOP, slug) for slug, name, _ in seed.LOOP_NODES
    }
    return [_BoundItem(_row_to_item(r), node_for[r["concept_key"]]) for r in rows["check_items"]]


def _first_items(probe_ns, on: bool) -> dict:  # noqa: F811
    """A new student's first probe item on every seeded concept (each strand
    in the probe at once, every answer correct)."""

    first: dict[str, object] = {}
    with patch_loop("flag_on", _flag(on)), patch_loop("posttest_anchors", MagicMock(return_value=([], False))):
        for _ in range(params.PROBE_SESSION_CAP):
            body = client.post(f"{LOOP}/probe/next", json=NEXT).json()
            if body["done"]:
                break
            pr = probe_ns.store["doc"]["probe"]
            first.setdefault(body["node_id"], body["question_hash"])
            pr["history"].append({**pr["current"], "correct": True, "idk": False, "p_after": 0.5})
            pr["current"] = None
    return first


@pytest.mark.parametrize("on", [False, True])
def test_item_match_on_a_full_bank(one_strand, on):
    """The drafter's full bank (one item per format × difficulty) protects two
    reserves, f2 and m2 — one per window. Off, a new student's pretest is
    teachback at difficulty 1 and both windows' pairs are `none`; on, it is
    teachback at difficulty 2 and both are `difficulty`."""
    first = _first_items(one_strand, on)
    items = [b.item for b in one_strand.full]
    pretest = next(i for i in items if i.question_hash == first["A"])
    week = choose_posttest_item(items, {pretest.question_hash}, window_index=0, pretest=pretest)
    month = choose_posttest_item(
        items, {pretest.question_hash, week.item.question_hash}, window_index=1, pretest=pretest
    )
    assert (week.source, month.source) == ("reserve", "reserve")
    assert (pretest.question_hash, week.match, month.match) == (
        ("t2", "difficulty", "difficulty") if on else ("t1", "none", "none")
    )


@pytest.mark.parametrize("on", [False, True])
def test_item_match_on_the_e2e_seed(probe, on):  # noqa: F811
    """What a new seeded student's pretest/post-test pairs look like.

    The seed gives each concept six items (free and teachback at every
    difficulty) — too few for a second reserve, so each concept protects one,
    free at difficulty 2, and the 28-day window poses a fallback whose match
    depends on what the student practised. Off, the probe's first item on
    every concept is its band pick for a new student, teachback at difficulty
    1, so every 7-day pair is `none`. On, it is teachback at difficulty 2 and
    every 7-day pair is `difficulty` — the best the seed allows: it has no
    second free item at difficulty 2, so no `exact` form exists."""
    bank = _seed_bank()
    nodes = sorted({b.node_id for b in bank})
    assert len(nodes) == 3 and len(bank) == 18
    probe.full = bank
    probe.states.return_value = {n: params.BKT_L0 for n in nodes}
    probe.edges.return_value = []  # every concept in the probe at once
    first = _first_items(probe, on)
    assert set(first) == set(nodes)
    matches = {}
    for node, qh in first.items():
        items = [b.item for b in bank if b.node_id == node]
        pretest = next(i for i in items if i.question_hash == qh)
        week = choose_posttest_item(items, {qh}, window_index=0, pretest=pretest)
        month = choose_posttest_item(items, {qh, week.item.question_hash}, window_index=1, pretest=pretest)
        assert week.source == "reserve" and (week.item.format, week.item.difficulty) == ("free", 2)
        assert month is not None and month.source == "fallback"  # one reserve per seeded concept
        matches[node] = (pretest.format, pretest.difficulty, week.match)
    assert set(matches.values()) == {("teachback", 2, "difficulty") if on else ("teachback", 1, "none")}
