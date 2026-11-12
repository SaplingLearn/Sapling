"""What the student knows (services/study_guides/signals.py).

Hermetic: `graph_nodes` and `quiz_context` are in-memory stand-ins that honour
the filters the module sends, with digests encrypted as the quiz writes them;
the silent-empty seam is recorded.
"""
import asyncio
import logging

import pytest

import config
from services.encryption import encrypt_json
from services.study_guides import signals
from services.tool_signals import Expect

ME, OTHER = "user_me", "user_other"
COURSE, OTHER_COURSE = "course-cs", "course-bio"


def _matches(row: dict, filters: dict) -> bool:
    for column, condition in filters.items():
        value = str(row.get(column))
        if condition.startswith("eq."):
            if value != condition[3:]:
                return False
        elif condition.startswith("neq."):
            if value == condition[4:]:
                return False
        elif condition.startswith("in.("):
            if value not in [v.strip('"') for v in condition[4:-1].split(",")]:
                return False
        else:
            raise AssertionError(f"filter {column}={condition} not modelled")
    return True


class _DB:
    def __init__(self):
        self.rows: dict[str, list[dict]] = {"graph_nodes": [], "quiz_context": []}
        self.reads: list[str] = []
        self.reports: list[dict] = []

    def node(self, node_id, name, score=0.0, *, user_id=ME, course_id=COURSE, tier="learning"):
        self.rows["graph_nodes"].append({
            "id": node_id, "user_id": user_id, "course_id": course_id,
            "concept_name": name, "mastery_score": score, "mastery_tier": tier,
        })

    def digest(self, node_id, *, user_id=ME, **fields):
        self.rows["quiz_context"].append({
            "user_id": user_id, "concept_node_id": node_id, "context_json": encrypt_json(fields),
        })

    def table(self, name):
        db = self

        class _Table:
            async def aselect(self, columns="*", filters=None, order=None, limit=None, **_):
                db.reads.append(name)
                rows = [r for r in db.rows[name] if _matches(r, filters or {})]
                if name == "graph_nodes":
                    rows.sort(key=lambda r: (r["concept_name"], r["id"]))
                return [{c: r.get(c) for c in columns.split(",")} for r in rows]

        return _Table()


@pytest.fixture
def db(monkeypatch):
    fake = _DB()
    monkeypatch.setattr(signals, "table", fake.table)

    async def report(tool, **kwargs):
        fake.reports.append({"tool": tool, **kwargs})
        return False

    monkeypatch.setattr(signals, "report_empty_result_async", report)
    return fake


def run(coro):
    return asyncio.run(coro)


# ── Mastery ───────────────────────────────────────────────────────────────────


def test_mastery_is_the_students_score_per_concept_in_the_course(db):
    db.node("n1", "Recursion", 0.82)
    db.node("n2", "Pointers", 0.2)
    db.node("n3", "Unscored", None)
    db.node("n-root", "CS 111", 0.0, tier="subject_root")
    db.node("n-bio", "Mitosis", 0.9, course_id=OTHER_COURSE)
    db.node("n-theirs", "Recursion", 0.1, user_id=OTHER)
    assert run(signals.amastery(ME, COURSE)) == {"Pointers": 0.2, "Recursion": 0.82, "Unscored": 0.0}


def test_the_mastery_read_reports_through_the_silent_empty_seam(db):
    db.node("n1", "Recursion", 0.82)
    run(signals.amastery(ME, COURSE))
    run(signals.amastery(ME, OTHER_COURSE))
    assert db.reports == [
        {"tool": "study_guide_mastery", "user_id": ME, "count": 1, "expect": Expect.HAS_GRAPH,
         "feature": "study_guide", "scope": {"course_id": f"eq.{COURSE}"}},
        {"tool": "study_guide_mastery", "user_id": ME, "count": 0, "expect": Expect.HAS_GRAPH,
         "feature": "study_guide", "scope": {"course_id": f"eq.{OTHER_COURSE}"}},
    ]


def test_tiers_follow_the_configured_thresholds():
    assert signals.tiers({
        "a": config.MASTERY_MASTERED_MIN,
        "b": config.MASTERY_MASTERED_MIN - 0.01,
        "c": config.MASTERY_LEARNING_MIN - 0.01,
        "d": 0.0,
    }) == {"a": "mastered", "b": "learning", "c": "struggling", "d": "unexplored"}
    assert signals.tiers({}) == {}


def test_concept_names_match_whatever_the_case_and_spacing():
    assert signals.concept_key("  Supply   and\tDemand ") == signals.concept_key("supply and demand")
    assert signals.concept_key("Supply") != signals.concept_key("Demand")


# ── Quiz mistakes ─────────────────────────────────────────────────────────────


def test_mistakes_list_common_mistakes_first_then_weak_areas(db):
    db.node("n1", "Recursion")
    db.digest("n1", common_mistakes=["Forgets the base case"], weak_areas=["Tail calls"],
              notes="never a mistake", questions_seen_summary="nor this")
    assert run(signals.amistakes(ME, COURSE, ["Recursion"])) == [
        signals.QuizMistake(id="m1", concept="Recursion", text="Forgets the base case"),
        signals.QuizMistake(id="m2", concept="Recursion", text="Tail calls"),
    ]


def test_mistakes_follow_the_order_the_concepts_are_given_in(db):
    db.node("n1", "Pointers")
    db.node("n2", "Recursion")
    db.digest("n1", common_mistakes=["Dereferences null"])
    db.digest("n2", common_mistakes=["Forgets the base case"])
    found = run(signals.amistakes(ME, COURSE, ["Recursion", "Pointers"]))
    assert [(m.id, m.concept) for m in found] == [("m1", "Recursion"), ("m2", "Pointers")]


def test_concepts_match_on_case_and_spacing_and_keep_the_trees_name(db):
    db.node("n1", "Supply and Demand")
    db.digest("n1", weak_areas=["Shifts versus movements"])
    (mistake,) = run(signals.amistakes(ME, COURSE, ["  supply  AND demand"]))
    assert mistake.concept == "Supply and Demand"


def test_at_most_three_mistakes_per_concept_and_twelve_in_all(db):
    names = [f"Concept {n}" for n in range(6)]
    for n, name in enumerate(names):
        db.node(f"n{n}", name)
        db.digest(f"n{n}", common_mistakes=[f"{name} mistake {i}" for i in range(4)],
                  weak_areas=[f"{name} weak area"])
    found = run(signals.amistakes(ME, COURSE, names))
    assert [m.id for m in found] == [f"m{n}" for n in range(1, 13)]
    assert [m.concept for m in found] == [name for name in names[:4] for _ in range(3)]
    assert found[2].text == "Concept 0 mistake 2"  # the fourth and the weak area are cut


def test_blank_and_repeated_entries_are_dropped(db):
    db.node("n1", "Recursion")
    db.digest("n1", common_mistakes=["Forgets the base case", "  ", None],
              weak_areas=["forgets the  base case", "Tail calls"])
    assert [m.text for m in run(signals.amistakes(ME, COURSE, ["Recursion"]))] == [
        "Forgets the base case", "Tail calls",
    ]


def test_only_this_students_digests_for_these_concepts_are_read(db):
    db.node("n1", "Recursion")
    db.node("n2", "Pointers")
    db.node("n-bio", "Recursion", course_id=OTHER_COURSE)
    db.digest("n1", common_mistakes=["Mine"])
    db.digest("n1", user_id=OTHER, common_mistakes=["A classmate's"])
    db.digest("n2", common_mistakes=["Not asked for"])
    db.digest("n-bio", common_mistakes=["Another class"])
    assert [m.text for m in run(signals.amistakes(ME, COURSE, ["Recursion"]))] == ["Mine"]


def test_a_digest_that_does_not_decrypt_is_skipped_with_a_warning(db, caplog):
    db.node("n1", "Pointers")
    db.node("n2", "Recursion")
    db.digest("n1", common_mistakes=["Never read"])
    db.digest("n2", common_mistakes=["Forgets the base case"])
    db.rows["quiz_context"][0]["context_json"] = "bm90IGNpcGhlcnRleHQgYXQgYWxsLCBqdXN0IGJhc2U2NCB0ZXh0"
    with caplog.at_level(logging.WARNING, logger=signals.logger.name):
        found = run(signals.amistakes(ME, COURSE, ["Pointers", "Recursion"]))
    assert found == [signals.QuizMistake(id="m1", concept="Recursion", text="Forgets the base case")]
    warnings = [r for r in caplog.records if r.name == signals.logger.name]
    assert len(warnings) == 1 and warnings[0].exc_info is None
    assert db.reports[-1]["count"] == 1


def test_the_mistakes_read_reports_the_digests_that_yielded_text(db):
    db.node("n1", "Pointers")
    db.node("n2", "Recursion")
    db.digest("n1", common_mistakes=[], weak_areas=[], notes="nothing recorded yet")
    assert run(signals.amistakes(ME, COURSE, ["Pointers", "Recursion"])) == []
    assert db.reports == [{
        "tool": "study_guide_mistakes", "user_id": ME, "count": 0,
        "expect": Expect.HAS_ATTEMPTS, "feature": "study_guide",
        "scope": {"concept_node_id": 'in.("n1","n2")'},
    }]


def test_concepts_the_tree_does_not_have_read_no_digests(db):
    db.node("n1", "Recursion")
    db.digest("n1", common_mistakes=["Forgets the base case"])
    assert run(signals.amistakes(ME, COURSE, ["Graph theory"])) == []
    assert run(signals.amistakes(ME, COURSE, [])) == []
    assert "quiz_context" not in db.reads
    assert db.reports == []
