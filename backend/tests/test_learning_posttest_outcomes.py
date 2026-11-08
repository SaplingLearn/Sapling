"""Spec §13 A126: matched delayed-retention outcome items.

The concept's two protected post-test items (`checks.posttest_reserve_hashes`:
the A23 reserve and its parallel form), how a window's item is chosen against
the student's pretest item (`choose_posttest_item`, `pretest_match`), why a
due window is skipped (`posttest_skip_reason`), that every serving path keeps
BOTH reserves out (in-session checks, H4 siblings, review; the probe's own test
is in tests/test_learning_probe_planner.py), and the schema's value lists
against learning/params.py. The route behaviour is in
tests/test_learning_posttest.py, the report in tests/test_learning_learning_gain.py
and tests/test_admin_learning_loop_kpis.py, the SQL in
tests/integration/test_posttest_outcomes_db.py."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from learning import params
from learning.checks import (
    CheckItem,
    RubricItem,
    WrongReason,
    choose_posttest_item,
    posttest_reserve_hash,
    posttest_reserve_hashes,
    posttest_reserves,
    posttest_skip_reason,
    pretest_match,
)

FMT = {"f": "free", "t": "teachback", "m": "mc_reason"}
MIGRATION = next(
    (Path(__file__).resolve().parents[1] / "db" / "migrations").glob("*_learning_posttest_outcomes.sql")
)


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


def _grid(**over):
    """A full bank — one item per (format, difficulty), hashes 'f1' … 'm3'."""
    items = {f"{f}{d}": _item(f"{f}{d}", FMT[f], d) for f in "ftm" for d in (1, 2, 3)}
    items.update(over)
    return list(items.values())


def _by(items, qh):
    return next(i for i in items if i.question_hash == qh)


# ── the reserve pair ─────────────────────────────────────────────────────────


def test_a_full_bank_protects_the_a23_reserve_and_its_parallel_form():
    """The first is A23's free item at the middle difficulty; the second keeps
    its difficulty in the next POSTTEST_RESERVE_FORMATS format (mc_reason: a
    strong channel, selected-response)."""
    assert params.POSTTEST_RESERVE_FORMATS == ("free", "mc_reason", "teachback")
    grid = _grid()
    assert posttest_reserve_hashes(grid) == ("f2", "m2")
    assert posttest_reserve_hash(grid) == "f2"  # A23's reserve is unchanged
    assert posttest_reserves(grid) == frozenset({"f2", "m2"})
    without_mc = [i for i in grid if i.question_hash != "m2"]
    assert posttest_reserve_hashes(without_mc) == ("f2", "t2")  # the next format
    no_free_mid = [i for i in grid if i.question_hash != "f2"]
    # no free/2 item: A23 falls back to the best servable item (f1, the lowest
    # hash); its parallel form keeps that difficulty in the next format
    assert posttest_reserve_hashes(no_free_mid) == ("f1", "m1")


def test_a_duplicate_cell_is_the_exact_parallel_form():
    """Where the pool allows — two items in the reserve's own cell — the second
    reserve shares its format and difficulty."""
    grid = _grid(f2b=_item("f2b", "free", 2))
    assert posttest_reserve_hashes(grid) == ("f2", "f2b")


def test_a_confirmed_key_is_preferred_then_the_lint_tier():
    """A124 then A113: among the items one rule allows, a verified key first,
    a clean lint before an unlinted one before a flagged one, then the hash."""
    grid = _grid(f2=_item("f2", "free", 2, lint=[]), f2v=_item("f2v", "free", 2, verified=True))
    assert posttest_reserve_hashes(grid)[0] == "f2v"
    flagged = _grid(
        f2=_item("f2", "free", 2, lint=["negative_stem"]), f2z=_item("f2z", "free", 2, lint=[])
    )
    assert posttest_reserve_hashes(flagged) == ("f2z", "f2")  # f2 is still the exact parallel
    shape_first = _grid(m2=_item("m2", "mc_reason", 2, lint=["correct_longest"]))
    assert posttest_reserve_hashes(shape_first) == ("f2", "m2")  # the shape decides before the lint


def test_held_and_answerless_items_are_never_reserves():
    held = _item("f2", "free", 2, lint=["key_disputed"])  # A124: held
    grid = _grid(f2=held, m2=_item("m2", "mc_reason", 2, final_answer=None))  # A34
    reserves = posttest_reserve_hashes(grid)
    assert "f2" not in reserves and "m2" not in reserves
    assert reserves == ("f1", "m1")


@pytest.mark.parametrize("size,count", [(1, 1), (6, 1), (7, 2), (9, 2)])
def test_a_small_bank_keeps_its_one_reserve(size, count):
    """The second reserve leaves at least POSTTEST_RESERVE_MIN_LEFT servable
    items (the probe's minimum per skill plus its practice reserve) — the
    six-item seeded loop concepts keep exactly the bank they had."""
    assert params.POSTTEST_RESERVE_MIN_LEFT == params.PROBE_ITEMS_PER_SKILL_MIN + 1
    bank = _grid()[:size]
    assert len(posttest_reserve_hashes(bank)) == count
    assert posttest_reserve_hashes([]) == ()


# ── the window's item ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "fmt,difficulty,expected",
    [("free", 2, "exact"), ("teachback", 2, "difficulty"), ("free", 1, "format"), ("mc_reason", 3, "none")],
)
def test_the_match_levels(fmt, difficulty, expected):
    assert pretest_match(_item("x", "free", 2), _item("p", fmt, difficulty)) == expected
    assert pretest_match(_item("x"), None) == "no_pretest"
    assert expected in params.POSTTEST_ITEM_MATCHES


def test_without_a_pretest_each_window_takes_its_own_reserve():
    grid = _grid()
    first = choose_posttest_item(grid, set(), window_index=0)
    second = choose_posttest_item(grid, set(), window_index=1)
    assert (first.item.question_hash, first.match, first.source) == ("f2", "no_pretest", "reserve")
    assert (second.item.question_hash, second.match, second.source) == ("m2", "no_pretest", "reserve")


def test_the_better_matched_reserve_goes_to_the_first_window():
    """Pretest m1 (mc_reason, difficulty 1): m2 shares its format, f2 nothing —
    the 1-week window (the primary outcome) poses m2; once m2 is answered
    (seen), the 4-week window poses f2."""
    grid = _grid()
    pretest = _by(grid, "m1")
    first = choose_posttest_item(grid, {"m1"}, window_index=0, pretest=pretest)
    assert (first.item.question_hash, first.match) == ("m2", "format")
    second = choose_posttest_item(grid, {"m1", "m2"}, window_index=1, pretest=pretest)
    assert (second.item.question_hash, second.match, second.source) == ("f2", "none", "reserve")


def test_equally_matched_reserves_keep_their_windows():
    grid = _grid()
    pretest = _by(grid, "t2")  # both reserves share its difficulty
    assert choose_posttest_item(grid, {"t2"}, window_index=0, pretest=pretest).item.question_hash == "f2"
    assert choose_posttest_item(grid, {"t2"}, window_index=1, pretest=pretest).item.question_hash == "m2"


def test_the_only_fresh_reserve_is_taken():
    grid = _grid()
    choice = choose_posttest_item(grid, {"f2"}, window_index=0)
    assert (choice.item.question_hash, choice.source) == ("m2", "reserve")


def test_with_no_fresh_reserve_the_fallback_order():
    """Matched to the pretest first, then A23's order: a free item, a
    confirmed key, the lint tier, the nearest middle difficulty, the lower,
    the hash. Never an excluded item."""
    grid = _grid()
    pretest = _by(grid, "m1")
    choice = choose_posttest_item(grid, {"f2", "m2", "m1"}, window_index=0, pretest=pretest)
    assert (choice.item.question_hash, choice.match, choice.source) == ("f1", "difficulty", "fallback")
    no_pretest = choose_posttest_item(grid, {"f2", "m2"}, window_index=0)
    assert no_pretest.item.question_hash == "f1"  # free, nearest the middle, the lower first
    hard = choose_posttest_item(grid, {"f2", "m2", "t3"}, window_index=0, pretest=_by(grid, "t3"))
    assert (hard.item.question_hash, hard.match) == ("f3", "difficulty")  # the match outranks the middle
    verified = _grid(f3=_item("f3", "free", 3, verified=True))
    assert choose_posttest_item(verified, {"f2", "m2"}, window_index=0).item.question_hash == "f3"
    no_free = choose_posttest_item(grid, {"f1", "f2", "f3", "m2"}, window_index=0)
    assert no_free.item.question_hash == "t2"  # no free left: the nearest middle difficulty
    everything = {i.question_hash for i in grid}
    assert choose_posttest_item(grid, everything, window_index=0) is None


def test_a_held_item_is_never_posed():
    held = _item("f2", "free", 2, lint=["key_audit_wrong"])
    choice = choose_posttest_item([held, _item("t1", "teachback", 1)], set(), window_index=0)
    assert choice.item.question_hash == "t1"
    assert choose_posttest_item([held], set(), window_index=0) is None


# ── why a window is skipped ──────────────────────────────────────────────────


def test_the_skip_reasons():
    assert posttest_skip_reason([], exposed=set()) == "no_items"
    assert posttest_skip_reason([_item("q", final_answer=None)], exposed=set()) == "no_items"
    assert posttest_skip_reason([_item("q", lint=["key_disputed"])], exposed=set()) == "no_items"
    bank = [_item("q1"), _item("q2")]
    assert posttest_skip_reason(bank, exposed={"q1", "q2"}) == "exhausted"
    assert posttest_skip_reason(bank, exposed=iter(["q1", "q2"])) == "exhausted"  # any iterable
    assert posttest_skip_reason(bank, exposed={"q1"}) == "reported"  # q2 is only reported
    assert set(params.POSTTEST_SKIP_REASONS) == {"no_items", "exhausted", "reported"}


# ── every serving path keeps both reserves out ───────────────────────────────


def test_in_session_practice_excludes_both_reserves():
    from routes import learn_loop

    grid = _grid()
    with (
        patch("routes.learn_loop._concept_key_for_node", return_value="k1"),
        patch("routes.learn_loop.list_items", return_value=grid),
    ):
        items, exclude = learn_loop._practice_pool("u1", "c1", "node-1", {"seen"})
    assert items == grid and exclude == {"seen", "f2", "m2"}


def test_an_h4_sibling_is_never_a_reserve():
    """The active item m2b shares its cell with the second reserve m2 (a
    duplicate cell): H4 shows an isomorph — never m2."""
    from routes import learn_loop
    from learning.ladder import Rung

    grid = _grid(m2b=_item("m2b", "mc_reason", 2))
    active = _by(grid, "m2b")
    assert posttest_reserve_hashes(grid) == ("f2", "m2")
    with patch("routes.learn_loop.list_items", return_value=grid), patch(
        "routes.learn_loop.ladder.deterministic_content", return_value=None
    ) as content:
        learn_loop._leak_checked_payload(user_id="u1", item=active, rung=Rung.H4, reference="r")
    assert content.call_args.kwargs["exclude_hashes"] == frozenset({"f2", "m2"})


def test_review_never_serves_a_reserve(monkeypatch):
    """Both passes of the review selector exclude both reserves (A23 since
    PKG-12, the second since A126). A develop-band review asks mc_reason at
    difficulty 2 — exactly the second reserve's cell — and every other item is
    seen, so only the fallback pass can serve: it takes the nearest mc_reason
    item, never m2."""
    from datetime import datetime, timezone

    from learning import review

    grid = _grid()
    monkeypatch.setattr(review, "list_items", lambda *_a: grid)
    monkeypatch.setattr(review, "seen_hashes", lambda _u: {i.question_hash for i in grid} - {"f2", "m2"})
    monkeypatch.setattr(review, "revealed_hashes", lambda _u: set())
    monkeypatch.setattr(review, "reported_hashes", lambda _u: set())
    selector = review._Selector("u1", served_today=set(), opened={})
    concept = review._Concept(
        node={"id": "n1", "course_id": "c1", "concept_name": "k1"},
        row={"streak_unassisted": 0},
        stability=1.0,
        last_review_at=None,
        band="develop",
    )
    picked = selector.item(concept, datetime(2026, 11, 8, tzinfo=timezone.utc))
    assert picked is not None and picked.question_hash == "m1"


# ── the anchors read (the posttest_anchors SQL function) ─────────────────────


def test_the_anchors_are_read_page_by_page_by_node_id(monkeypatch):
    from datetime import datetime, timezone

    from learning import posttest_store

    monkeypatch.setattr(posttest_store, "_ANCHORS_PAGE", 2)
    pages = [[{"node_id": "a"}, {"node_id": "b"}], [{"node_id": "c"}, {"node_id": "d"}], [{"node_id": "e"}]]
    calls = []

    def _rpc(name, params_):
        calls.append((name, dict(params_)))
        return pages[len(calls) - 1]

    monkeypatch.setattr(posttest_store, "rpc", _rpc)
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    rows, truncated = posttest_store.posttest_anchors(user_id="u1", anchor_from=t0)
    assert [r["node_id"] for r in rows] == list("abcde") and truncated is False
    assert [c[1]["p_after_node_id"] for c in calls] == [None, "b", "d"]
    assert all(c[0] == "posttest_anchors" and c[1]["p_limit"] == 2 for c in calls)
    assert calls[0][1] == {"p_user_id": "u1", "p_anchor_from": t0.isoformat(), "p_anchor_to": None,
                           "p_after_node_id": None, "p_limit": 2}


def test_a_capped_anchors_read_says_it_was_cut(monkeypatch):
    from learning import posttest_store

    monkeypatch.setattr(posttest_store, "_ANCHORS_PAGE", 2)
    monkeypatch.setattr(posttest_store, "rpc", lambda *_a: [{"node_id": "a"}, {"node_id": "b"}])
    rows, truncated = posttest_store.posttest_anchors(limit=3)
    assert len(rows) == 3 and truncated is True
    monkeypatch.setattr(posttest_store, "rpc", lambda *_a: [{"node_id": "a"}])
    assert posttest_store.posttest_anchors(limit=1) == ([{"node_id": "a"}], False)  # all of it


def test_a_failed_anchors_read_raises():
    from learning import posttest_store

    with patch("learning.posttest_store.rpc", side_effect=RuntimeError("no such function")):
        with pytest.raises(RuntimeError):
            posttest_store.posttest_anchors(user_id="u1")


# ── the request model and the schema's value lists ───────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [(3, 3.0), (2.5, 2.5), (None, None), ("3", None), (True, None), ({"x": 1}, None),
     (float("nan"), None), (10**400, None)],
)
def test_the_answer_body_takes_any_telemetry_and_keeps_only_finite_numbers(value, expected):
    from models import PosttestAnswerBody

    body = PosttestAnswerBody(node_id="n1", question_hash="q1", hidden_count=value, hidden_s=value)
    assert body.hidden_count == expected and body.hidden_s == expected


def _check_list(name: str) -> tuple[str, ...]:
    sql = MIGRATION.read_text()
    found = re.search(rf"{name} IN \(([^)]*)\)", sql)
    assert found, name
    return tuple(v.strip().strip("'") for v in found.group(1).split(","))


def test_the_migration_check_lists_are_the_params():
    assert _check_list("item_match") == params.POSTTEST_ITEM_MATCHES
    assert _check_list("item_source") == params.POSTTEST_ITEM_SOURCES
    assert _check_list("reason") == params.POSTTEST_SKIP_REASONS


def test_the_skip_table_and_the_anchor_function_are_backend_only():
    sql = MIGRATION.read_text()
    assert "ALTER TABLE posttest_skips ENABLE ROW LEVEL SECURITY" in sql
    assert "REVOKE ALL ON TABLE posttest_skips FROM PUBLIC" in sql
    signature = "posttest_anchors(text, timestamptz, timestamptz, text, integer)"
    assert f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC" in sql
    assert f"GRANT EXECUTE ON FUNCTION {signature} TO service_role" in sql
    assert "STABLE" in sql  # a read: no write can hide behind the RPC
    for verb in ("INSERT", "UPDATE", "DELETE"):
        body = sql.split("AS $$", 1)[1].split("$$;", 1)[0]
        assert verb not in body.upper()
