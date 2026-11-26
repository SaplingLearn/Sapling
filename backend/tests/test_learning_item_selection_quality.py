"""Spec §13 A129: every picker that serves a student a check item prefers,
among the items its own rule treats as equal, a confirmed key, then a clean
lint, then never linted, then flagged — the post-test's quality order
(`checks.serve_quality`) — and never lets that preference override the rule's
own keys: the difficulty target, the strand, the channel (format), novelty and
the reserve exclusions. A flagged item still serves when it is the only option.

One test group per picker: `checks.select_item` (in-session activation and
review), the review selector, the probe (`probe.next_probe_item`, through the
route's `_BoundItem`), the isomorph re-ask after `unknown`, and the H4
sibling. The post-test keeps its own order (A126), which serve_quality never
contradicts."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agents.tools.check import CHANNEL_FOR_FORMAT
from learning import params
from learning.checks import (
    CheckItem,
    RubricItem,
    WrongReason,
    _quality_rank,
    lint_rank,
    posttest_reserve_hashes,
    select_item,
    serve_quality,
)
from tests.split_patches import patch_loop
import services.loop.cursor

T = "2026-11-01T00:00:00+00:00"


def _item(
    qh,
    fmt="free",
    difficulty=2,
    *,
    verified=False,
    lint=None,
    created=T,
    stepwise=False,
    concept="k1",
) -> CheckItem:
    return CheckItem(
        id=f"id-{qh}",
        course_id="c1",
        concept_key=concept,
        format=fmt,
        difficulty=difficulty,
        prompt=f"Question {qh}?",
        reference_answer=f"1. Start from {qh}.\n2. Conclude for {qh}.",
        rubric=[RubricItem(id="r1", text="states it")],
        common_wrong=[WrongReason(key="w", text="a wrong idea")],
        source_chunk_ids=["ch"],
        question_hash=qh,
        final_answer=f"{qh} result",
        canonical_verified=verified,
        lint_flags=lint,
        created_at=created,
        stepwise=stepwise,
    )


# ── the order itself ─────────────────────────────────────────────────────────


def test_serve_quality_is_a_confirmed_key_then_clean_never_linted_flagged():
    ranked = [
        _item("a", verified=True, lint=[]),
        _item("b", verified=True, lint=None),
        _item("c", verified=True, lint=["correct_longest"]),
        _item("d", verified=True, lint=["unsourced"]),
        _item("e", verified=False, lint=[]),
        _item("f", verified=False, lint=None),
        _item("g", verified=False, lint=["negative_stem"]),
        _item("h", verified=False, lint=["unsourced"]),
    ]
    assert sorted(ranked, key=serve_quality) == ranked
    # A128 refines the flagged tier: an item with its sources before an unsourced one
    assert serve_quality(ranked[2]) < serve_quality(ranked[3])
    assert lint_rank(ranked[2]) == lint_rank(ranked[3]) == 2


def test_serve_quality_never_contradicts_the_post_tests_order():
    """The post-test's _quality_rank (A126) is (verify, lint, hash); A129's
    order is its first two keys, refined only where those tie."""
    pool = [
        _item(qh, verified=v, lint=lint)
        for qh, (v, lint) in enumerate(
            [(True, []), (True, None), (True, ["unsourced"]), (False, []), (False, ["x"]), (False, None)]
        )
        for qh in [f"q{qh}"]
    ]
    for a in pool:
        for b in pool:
            if serve_quality(a)[:2] < serve_quality(b)[:2]:
                assert _quality_rank(a) < _quality_rank(b)


# ── select_item: in-session activation and review ────────────────────────────


def test_select_item_prefers_a_confirmed_key_then_the_lint_tier_at_the_chosen_difficulty():
    older_flagged = _item("a", lint=["correct_longest"], created="2026-09-01T00:00:00+00:00")
    clean = _item("b", lint=[])
    never_linted = _item("c", lint=None)
    verified_flagged = _item("d", verified=True, lint=["correct_longest"])
    assert select_item([older_flagged, clean], format="free", difficulty=2) is clean
    assert select_item([older_flagged, never_linted], format="free", difficulty=2) is never_linted
    assert select_item([never_linted, clean], format="free", difficulty=2) is clean
    # a confirmed key outranks the lint tier: a wrong key is no measurement at all
    assert select_item([clean, verified_flagged], format="free", difficulty=2) is verified_flagged


def test_select_item_never_lets_quality_move_the_difficulty_or_the_format():
    flagged_exact = _item("a", difficulty=2, lint=["negative_stem"])
    clean_far = _item("b", difficulty=3, verified=True, lint=[])
    assert select_item([flagged_exact, clean_far], format="free", difficulty=2) is flagged_exact
    # the nearest difficulty keeps "lower first" on a tie, whatever the quality
    flagged_low = _item("c", difficulty=1, lint=["negative_stem"])
    assert select_item([clean_far, flagged_low], format="free", difficulty=2) is flagged_low
    # the format is the channel: never substituted for a cleaner item
    clean_teachback = _item("d", "teachback", 2, verified=True, lint=[])
    assert select_item([flagged_exact, clean_teachback], format="free", difficulty=2) is flagged_exact


def test_a_flagged_item_still_serves_when_it_is_the_only_option():
    flagged = _item("a", lint=["duplicate_options"])
    clean = _item("b", lint=[])
    assert select_item([flagged], format="free", difficulty=2) is flagged
    assert select_item([flagged, clean], format="free", difficulty=2, exclude_hashes={"b"}) is flagged


def test_select_item_keeps_a128s_sourced_item_first_between_two_flagged_ones():
    unsourced = _item("a", lint=["unsourced"], created="2026-09-01T00:00:00+00:00")
    sourced_flagged = _item("b", lint=["negative_stem"])
    assert select_item([unsourced, sourced_flagged], format="free", difficulty=2) is sourced_flagged


def test_equal_quality_keeps_the_oldest_item():
    newer = _item("a", lint=[], created="2026-11-02T00:00:00+00:00")
    older = _item("b", lint=[], created="2026-10-01T00:00:00+00:00")
    assert select_item([newer, older], format="free", difficulty=2) is older


# ── the review selector (rule 1, A23) ────────────────────────────────────────


def _review_pick(monkeypatch, pool, *, seen=(), band="develop"):
    from learning import review

    monkeypatch.setattr(review, "list_items", lambda *_a: pool)
    monkeypatch.setattr(review, "seen_hashes", lambda _u: set(seen))
    monkeypatch.setattr(review, "revealed_hashes", lambda _u: set())
    monkeypatch.setattr(review, "reported_hashes", lambda _u: set())
    selector = review._Selector("u1", served_today=set(), opened={})
    concept = review._Concept(
        node={"id": "n1", "course_id": "c1", "concept_name": "k1"},
        row={"streak_unassisted": 0},
        stability=1.0,
        last_review_at=None,
        band=band,
    )
    picked = selector.item(concept, datetime(2026, 11, 8, tzinfo=timezone.utc))
    return picked.question_hash if picked is not None else None


def _grid_without(*cells, stepwise=False):
    """A full bank (one clean item per format × difficulty, hashes f1 … m3)
    minus `cells`: its post-test reserves are f2 and its parallel form m2."""
    fmt = {"f": "free", "t": "teachback", "m": "mc_reason"}
    return [
        _item(f"{f}{d}", fmt[f], d, lint=[], stepwise=stepwise)
        for f in "ftm"
        for d in (1, 2, 3)
        if f"{f}{d}" not in cells
    ]


def test_review_prefers_the_clean_item_among_its_rules_equals(monkeypatch):
    """A novice review asks mc_reason at difficulty 1: of the items there,
    the clean one, though the flagged one is older (the tie-break before)."""
    older_flagged = _item("mf", "mc_reason", 1, lint=["correct_longest"], created="2026-09-01T00:00:00+00:00")
    bank = _grid_without() + [older_flagged]
    assert posttest_reserve_hashes(bank) == ("f2", "m2")
    assert _review_pick(monkeypatch, bank, band="novice") == "m1"
    verified = _item("mv", "mc_reason", 1, verified=True, lint=["correct_longest"])
    assert _review_pick(monkeypatch, bank + [verified], band="novice") == "mv"


def test_review_novelty_difficulty_and_channel_come_before_quality(monkeypatch):
    # novelty: the strict pass (unseen) serves the flagged item before a clean seen one
    bank = _grid_without() + [_item("mf", "mc_reason", 1, lint=["correct_longest"])]
    assert _review_pick(monkeypatch, bank, seen={"m1"}, band="novice") == "mf"
    # difficulty and channel: the band's format at its difficulty, flagged,
    # before a clean mc_reason item at another difficulty or a clean free one at it
    flagged_cell = _grid_without("m1") + [_item("m1", "mc_reason", 1, lint=["negative_stem"])]
    assert _review_pick(monkeypatch, flagged_cell, band="novice") == "m1"


# ── the probe (probe.next_probe_item through the route's binding) ────────────


def _bound(item, node="n1"):
    from services.loop.planning import _BoundItem

    return _BoundItem(item, node)


def _probe(states, items, **kw):
    from learning import probe

    return probe.next_probe_item(states, items, [], channel_for_format=CHANNEL_FOR_FORMAT, **kw)


def test_the_binding_carries_serve_quality():
    flagged = _bound(_item("a", lint=["unsourced"]))
    assert flagged.quality == serve_quality(flagged.item) and flagged.unsourced is True


def test_the_probe_prefers_quality_among_equal_challenges():
    flagged = _bound(_item("a", "teachback", 1, lint=["negative_stem"]))
    clean = _bound(_item("b", "teachback", 1, lint=[]))
    verified = _bound(_item("c", "teachback", 1, verified=True, lint=["negative_stem"]))
    assert _probe({"n1": params.BKT_L0}, [flagged, clean]) is clean
    assert _probe({"n1": params.BKT_L0}, [flagged, clean, verified]) is verified


def test_the_probe_never_lets_quality_move_the_strand_the_challenge_or_the_channel():
    # the challenge (and through it the channel): at BKT_L0 a teachback item at
    # difficulty 1 is in the probe band, a free one is not — the flagged
    # teachback item is asked before the confirmed, clean free one
    flagged_in_band = _bound(_item("a", "teachback", 1, lint=["negative_stem"]))
    clean_out_of_band = _bound(_item("b", "free", 1, verified=True, lint=[]))
    assert _probe({"n1": params.BKT_L0}, [flagged_in_band, clean_out_of_band]) is flagged_in_band
    # the adaptive difficulty: after an unaided correct answer at difficulty 1
    # the probe challenges the harder side, flagged or not
    history = [
        {
            "node_id": "n1", "question_hash": "h0", "difficulty": 1, "channel": "free_response",
            "correct": True, "idk": False, "p_after": 0.5, "independent": True,
        }
    ]
    hard_flagged = _bound(_item("c", "free", 3, lint=["negative_stem"]))
    easy_clean = _bound(_item("d", "free", 1, verified=True, lint=[]))
    assert _probe({"n1": 0.5}, [hard_flagged, easy_clean], history=history) is hard_flagged
    # the strand: the least-observed strand goes first, whatever its items' quality
    n1_clean = _bound(_item("e", "teachback", 1, verified=True, lint=[]), "n1")
    n2_flagged = _bound(_item("f", "teachback", 1, lint=["negative_stem"]), "n2")
    picked = _probe(
        {"n1": params.BKT_L0, "n2": params.BKT_L0},
        [n1_clean, n2_flagged],
        asked_per_node={"n1": 1},
    )
    assert picked is n2_flagged


def test_the_probe_still_asks_a_flagged_item_when_it_is_all_the_strand_has():
    flagged = _bound(_item("a", "teachback", 1, lint=["correct_longest"]))
    assert _probe({"n1": params.BKT_L0}, [flagged]) is flagged


def test_an_item_without_a_quality_ranks_as_before():
    """A caller that binds no quality (an older one, a test fake) keeps A128's
    rule: `unsourced` alone ranks an item after an equal one with its sources."""
    from types import SimpleNamespace

    a = SimpleNamespace(id="a", node_id="n1", format="free", difficulty=2, question_hash="a", unsourced=True)
    b = SimpleNamespace(id="b", node_id="n1", format="free", difficulty=2, question_hash="b")
    assert _probe({"n1": 0.5}, [a, b]) is b


# ── the isomorph re-ask after `unknown` (A75 (g), A27) ───────────────────────


def _unknown_state(qh="last"):
    return {
        "attempts": [
            {
                "question_hash": qh, "node_id": "node-1", "correct": False, "wrong_key": None,
                "confidence": None, "difficulty": 2, "idk": False, "isomorph_of": None,
            }
        ]
    }


def test_the_isomorph_re_ask_takes_the_best_isomorph():
    from services.loop.practice import _isomorph_after_unknown

    last = _item("last")
    flagged = _item("iso-a", lint=["correct_longest"], created="2026-09-01T00:00:00+00:00")
    clean = _item("iso-b", lint=[])
    verified = _item("iso-c", verified=True, lint=None)
    other_cell = _item("x", difficulty=3, verified=True, lint=[])  # no isomorph: another difficulty
    items = [last, flagged, other_cell, clean]
    assert _isomorph_after_unknown(_unknown_state(), "node-1", items, {"last"}) is clean
    items.append(verified)
    assert _isomorph_after_unknown(_unknown_state(), "node-1", items, {"last"}) is verified
    # a flagged isomorph is still re-asked when it is the only one
    only = [last, flagged, other_cell]
    assert _isomorph_after_unknown(_unknown_state(), "node-1", only, {"last"}) is flagged


# ── the H4 sibling (a worked example on an isomorph, A17) ─────────────────────


@pytest.mark.parametrize("best", ["clean", "verified"])
def test_the_h4_worked_example_is_the_best_isomorph(best):
    from learning.ladder import Rung

    # the isomorphs sit outside both reserve cells (f2, m2), so none is protected
    active = _item("active", "teachback", 1, stepwise=True)
    flagged = _item(
        "sib-a", "teachback", 1, lint=["negative_stem"], stepwise=True, created="2026-09-01T00:00:00+00:00"
    )
    clean = _item("sib-b", "teachback", 1, lint=[], stepwise=True)
    verified = _item("sib-c", "teachback", 1, verified=True, lint=["negative_stem"], stepwise=True)
    bank = _grid_without("t1") + [active, flagged, clean] + ([verified] if best == "verified" else [])
    assert posttest_reserve_hashes(bank) == ("f2", "m2")
    with patch_loop("list_items", return_value=bank):
        payload, leaked = services.loop.cursor._leak_checked_payload(
            user_id="u1", item=active, rung=Rung.H4, reference=active.reference_answer
        )
    assert payload is not None and not leaked
    assert payload.revealed_hash == ("sib-b" if best == "clean" else "sib-c")


def test_the_h4_worked_example_is_never_a_reserve_whatever_its_quality():
    """A23/A126: the reserves stay protected — a clean, confirmed sibling that is
    a reserve is never shown; the flagged isomorph is."""
    from learning.ladder import Rung

    # no mc_reason item at difficulty 2, so the second reserve is the
    # teachback one there (A126's parallel form), confirmed and clean
    bank = [
        i.model_copy(update={"canonical_verified": True}) if i.question_hash == "t2" else i
        for i in _grid_without("m2", stepwise=True)
    ]
    active = _item("t2b", "teachback", 2, stepwise=True)
    flagged = _item("t2c", "teachback", 2, lint=["negative_stem"], stepwise=True)
    bank += [active, flagged]
    assert posttest_reserve_hashes(bank) == ("f2", "t2")
    with patch_loop("list_items", return_value=bank):
        payload, _ = services.loop.cursor._leak_checked_payload(
            user_id="u1", item=active, rung=Rung.H4, reference=active.reference_answer
        )
    assert payload is not None and payload.revealed_hash == "t2c"
