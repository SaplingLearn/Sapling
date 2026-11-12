"""The planned outline (services/study_guides/plan.py).

`weights` and `plan_sections` are pure and tested directly. `aplan` is tested
with its three reads replaced where the module looks them up.
"""
import asyncio
from itertools import product

import pytest

from models.study_guide import GuideRequest
from services.study_guides import plan
from services.study_guides.errors import GuideNotFound

TIERS = ("struggling", "learning", "unexplored", "mastered")


# ── Weights ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("count", range(1, 9))
def test_weights_sum_to_100_for_every_tier_mix(count):
    for mix in product(TIERS, repeat=count):
        for use_history in (True, False):
            shares = plan.weights(list(mix), use_history=use_history)
            assert len(shares) == count
            assert sum(shares) == 100, (mix, use_history, shares)
            assert min(shares) >= 1, (mix, use_history, shares)


def test_weights_follow_the_room_each_tier_gets():
    # 5 : 3 : 3 : 1 of 12, rounded by largest remainder.
    assert plan.weights(["struggling", "learning", "unexplored", "mastered"], use_history=True) == [
        42, 25, 25, 8,
    ]
    assert plan.weights(["mastered", "struggling"], use_history=True) == [17, 83]
    assert plan.weights(["learning"], use_history=True) == [100]


def test_a_weaker_tier_never_gets_less_room():
    for mix in product(TIERS, repeat=5):
        shares = dict(zip(mix, plan.weights(list(mix), use_history=True)))
        ranked = [shares[t] for t in ("struggling", "learning", "mastered") if t in shares]
        assert ranked == sorted(ranked, reverse=True), mix


def test_weights_are_equal_without_history_and_the_remainder_goes_first():
    assert plan.weights(["struggling", "mastered", "learning"], use_history=False) == [34, 33, 33]
    assert plan.weights(["mastered"] * 8, use_history=False) == [13, 13, 13, 13, 12, 12, 12, 12]


def test_no_sections_have_no_weights():
    assert plan.weights([], use_history=True) == []


def test_a_long_lopsided_outline_still_gives_every_section_a_point():
    shares = plan.weights(["mastered"] * 50 + ["struggling"] * 20, use_history=True)
    assert sum(shares) == 100 and min(shares) == 1


# ── Sections ──────────────────────────────────────────────────────────────────

CONCEPTS = ["Variables", "Loops", "Functions", "Recursion", "Pointers", "Structs"]
SCORES = {
    "Variables": 0.9, "Loops": 0.5, "Functions": 0.3, "Recursion": 0.15, "Pointers": 0.8,
}


def test_each_concept_is_a_section_with_its_tier_and_share():
    sections = plan.plan_sections(
        ["Variables", "Loops", "Recursion"], SCORES, depth="standard", use_history=True,
    )
    assert [s.model_dump() for s in sections] == [
        {"title": "Variables", "tier": "mastered", "weight": 11},
        {"title": "Loops", "tier": "learning", "weight": 33},
        {"title": "Recursion", "tier": "struggling", "weight": 56},
    ]


def test_repeated_concepts_are_one_section_under_the_first_spelling():
    sections = plan.plan_sections(
        ["Loops", "  loops ", "LOOPS", "Functions", "", "   "], {}, depth="deep", use_history=True,
    )
    assert [s.title for s in sections] == ["Loops", "Functions"]


def test_with_history_the_weakest_concepts_are_kept_in_their_original_order():
    # cram keeps 3 of 6: Structs (not in the tree, counts as 0), Recursion
    # (0.15) and Functions (0.3), in the order the materials gave them.
    sections = plan.plan_sections(CONCEPTS, SCORES, depth="cram", use_history=True)
    assert [(s.title, s.tier) for s in sections] == [
        ("Functions", "struggling"), ("Recursion", "struggling"), ("Structs", "unexplored"),
    ]
    assert sum(s.weight for s in sections) == 100


def test_without_history_the_first_concepts_are_kept_and_all_are_unexplored():
    sections = plan.plan_sections(CONCEPTS, SCORES, depth="cram", use_history=False)
    assert [s.model_dump() for s in sections] == [
        {"title": "Variables", "tier": "unexplored", "weight": 34},
        {"title": "Loops", "tier": "unexplored", "weight": 33},
        {"title": "Functions", "tier": "unexplored", "weight": 33},
    ]


@pytest.mark.parametrize("depth, count", [("cram", 3), ("standard", 5), ("deep", 8)])
def test_a_depth_caps_the_number_of_sections(depth, count):
    concepts = [f"Concept {n}" for n in range(12)]
    for use_history in (True, False):
        sections = plan.plan_sections(concepts, {}, depth=depth, use_history=use_history)
        assert [s.title for s in sections] == concepts[:count]  # ties keep the earliest
        assert sum(s.weight for s in sections) == 100


def test_fewer_concepts_than_the_depth_allows_are_all_kept():
    sections = plan.plan_sections(["Loops", "Pointers"], SCORES, depth="deep", use_history=True)
    assert [(s.title, s.tier, s.weight) for s in sections] == [
        ("Loops", "learning", 75), ("Pointers", "mastered", 25),
    ]


def test_scores_match_concepts_whatever_the_case_and_spacing():
    sections = plan.plan_sections(
        ["supply  and demand"], {"Supply and Demand": 0.9}, depth="cram", use_history=True,
    )
    assert (sections[0].title, sections[0].tier) == ("supply  and demand", "mastered")


def test_no_concepts_plan_no_sections():
    assert plan.plan_sections([], SCORES, depth="standard", use_history=True) == []


# ── aplan ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def reads(monkeypatch):
    calls = {"offering": [], "concepts": [], "mastery": []}

    async def aresolve_offering(user_id, course_id, semester):
        calls["offering"].append((user_id, course_id, semester))
        if course_id != "course-cs":
            raise GuideNotFound("Class not found.")
        return "off-cs"

    async def aload_concepts(user_id, offering_id, material_ids):
        calls["concepts"].append((user_id, offering_id, list(material_ids)))
        return CONCEPTS if material_ids else []

    async def amastery(user_id, course_id):
        calls["mastery"].append((user_id, course_id))
        return SCORES

    monkeypatch.setattr(plan, "aresolve_offering", aresolve_offering)
    monkeypatch.setattr(plan, "aload_concepts", aload_concepts)
    monkeypatch.setattr(plan, "amastery", amastery)
    return calls


def _request(**choices):
    return GuideRequest(course_id="course-cs", material_ids=["d1", "d2"], **choices)


def test_the_plan_is_made_from_the_chosen_materials_and_the_students_mastery(reads):
    out = asyncio.run(plan.aplan("user_me", _request(semester="Fall 2026", depth="cram")))
    assert [s.title for s in out.sections] == ["Functions", "Recursion", "Structs"]
    assert out.minutes == 3 * plan.MINUTES_PER_SECTION["cram"] == 6
    assert reads == {
        "offering": [("user_me", "course-cs", "Fall 2026")],
        "concepts": [("user_me", "off-cs", ["d1", "d2"])],
        "mastery": [("user_me", "course-cs")],  # the graph keys on the course, not the offering
    }


@pytest.mark.parametrize("depth, sections, minutes", [
    ("cram", 3, 6), ("standard", 5, 15), ("deep", 6, 30),
])
def test_minutes_follow_the_number_of_sections_and_the_depth(reads, depth, sections, minutes):
    out = asyncio.run(plan.aplan("user_me", _request(depth=depth)))
    assert (len(out.sections), out.minutes) == (sections, minutes)


def test_with_history_off_mastery_is_not_read(reads):
    out = asyncio.run(plan.aplan("user_me", _request(use_history=False, depth="cram")))
    assert reads["mastery"] == []
    assert [(s.title, s.tier) for s in out.sections] == [
        ("Variables", "unexplored"), ("Loops", "unexplored"), ("Functions", "unexplored"),
    ]


def test_an_empty_selection_is_an_empty_plan(reads):
    request = GuideRequest(course_id="course-cs", material_ids=[])
    out = asyncio.run(plan.aplan("user_me", request))
    assert out.model_dump() == {"sections": [], "minutes": 0}
    assert reads["mastery"] == []


def test_a_class_the_student_is_not_in_has_no_plan(reads):
    request = GuideRequest(course_id="course-other", material_ids=["d1"])
    with pytest.raises(GuideNotFound):
        asyncio.run(plan.aplan("user_me", request))
    assert reads["concepts"] == [] and reads["mastery"] == []
