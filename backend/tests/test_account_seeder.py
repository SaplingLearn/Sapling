"""services/account_seed/seeder.py — the admin "seed account" engine.

Hermetic: a small in-memory PostgREST stand-in records every write in order,
the wipe service is faked (its own suite covers it), and the pack is a fixture built here (the
real packs are authored separately and validated by test_account_seed_packs).
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta

import pytest

from services.account_seed import seeder
from services.account_seed.schema import MajorPack
from services.encryption import decrypt_if_present, decrypt_json, decrypt_numeric

USER = "user_seed_target"
TERM_START = date(2026, 8, 24)
TODAY = TERM_START + timedelta(days=40)

# ── fixture pack ─────────────────────────────────────────────────────────────

_EXTRACTED = ("This lecture covers the core ideas of the unit in some depth. " * 8).strip()


def _course(n: int) -> dict:
    names = [f"Idea {chr(65 + i)}{n}" for i in range(8)]
    # every tier of learning.bkt.tier_for (0.10 / 0.30 / 0.95) at least once
    masteries = [0.96, 0.8, 0.6, 0.5, 0.3, 0.2, 0.05, 0.0]
    return {
        "code": f"CAS XX 10{n}",
        "name": f"Course Number {n}",
        "department": "Testing",
        "nickname": f"C{n}",
        "color": "#3366cc",
        "concepts": [
            {"name": nm, "mastery": m, "description": f"Description of {nm}."}
            for nm, m in zip(names, masteries)
        ],
        "edges": [
            {"source": names[i], "target": names[i + 1], "relationship": "builds_on",
             "strength": 0.6}
            for i in range(5)
        ],
        "mastery_events": [
            {"concept": names[0], "delta": 0.3, "reason": "quiz review"},
            {"concept": names[2], "delta": 0.1, "reason": "homework"},
        ],
        "categories": [
            {"name": "Homework", "weight": 0.4},
            {"name": "Exams", "weight": 0.6, "drop_lowest": 0},
        ],
        "assignments": [
            # due offsets relative to TERM_START; TODAY = +40
            {"title": "HW 1", "category": "Homework", "type": "homework",
             "due_offset_days": 10, "points_possible": 100, "points_earned": 91},
            {"title": "HW 2", "category": "Homework", "type": "homework",
             "due_offset_days": 25, "points_possible": 100, "points_earned": 84},
            {"title": "HW 3", "category": "Homework", "type": "homework",
             "due_offset_days": 39, "points_possible": 50, "points_earned": 45},
            # earned given but due in the future -> must stay ungraded
            {"title": "HW 4", "category": "Homework", "type": "homework",
             "due_offset_days": 55, "points_possible": 100, "points_earned": 99},
            {"title": "Midterm", "category": "Exams", "type": "exam",
             "due_offset_days": 50, "points_possible": 100, "is_midterm": True},
            {"title": "Final", "category": "Exams", "type": "exam",
             "due_offset_days": 110, "points_possible": 100},
        ],
        "notes": [
            {"title": f"Week {k} notes", "body": "Plaintext note body. " * 6,
             "tags": ["week"], "concepts": [names[0], names[1]]}
            for k in (1, 2)
        ],
        "documents": [
            {"file_name": f"c{n}-syllabus.pdf", "category": "syllabus",
             "summary": "A syllabus summary that is long enough to pass validation.",
             "concept_notes": [{"name": names[0], "description": "First idea."}],
             "extracted_text": _EXTRACTED},
            {"file_name": f"c{n}-lecture1.pdf", "category": "lecture_notes",
             "summary": "Lecture notes summary that is long enough to pass validation.",
             "concept_notes": [{"name": names[1], "description": "Second idea."}],
             "extracted_text": _EXTRACTED},
        ],
        "flashcards": [{"front": f"Front {k}", "back": f"Back {k}"} for k in range(6)],
        "study_guide": {
            "overview": "What the midterm covers.",
            "topics": [
                {"name": "Topic one", "importance": "Core.", "concepts": [names[0]]},
                {"name": "Topic two", "importance": "Builds.", "concepts": [names[1]]},
            ],
        },
        "quizzes": [
            {"concept": names[0], "difficulty": "easy", "days_ago": 5,
             "questions": [
                 {"question": f"Question {k}?", "options": ["w", "x", "y", "z"],
                  "correct_answer": "y", "explanation": "Because."}
                 for k in range(4)
             ],
             "correct": [0, 1, 3]},
            {"concept": names[4], "difficulty": "medium", "days_ago": 2,
             "questions": [
                 {"question": f"Other {k}?", "options": ["a", "b", "c", "d"],
                  "correct_answer": "a", "explanation": "Because."}
                 for k in range(3)
             ],
             "correct": [2]},
        ],
        "session": {
            "name": "Review session",
            "topic": names[4],
            "mode": "socratic",
            "summary_bullets": ["Covered one", "Covered two"],
            "messages": [
                {"role": "user", "content": "Tutor message from the student."},
                {"role": "assistant", "content": "Tutor reply."},
                {"role": "user", "content": "Follow-up."},
                {"role": "assistant", "content": "Answer."},
            ],
        },
    }


PACK = MajorPack.model_validate({
    "key": "testmajor",
    "label": "Test Major",
    "year": "Junior",
    "courses": [_course(n) for n in range(1, 5)],
    "total_xp": 1250,
    "streak_days": 6,
})


# ── in-memory PostgREST stand-in ─────────────────────────────────────────────


def _match(stored, expr: str) -> bool:
    if expr == "not.is.null":
        return stored is not None
    if expr == "is.null":
        return stored is None
    return str(stored) == expr.removeprefix("eq.")


class FakeDB:
    def __init__(self):
        self.rows: dict[str, list[dict]] = defaultdict(list)
        self.log: list[tuple[str, str]] = []  # (table, op) in call order

    def table(self, name):
        db = self

        class Handle:
            def _read(self, filters):
                return [r for r in db.rows[name]
                        if all(_match(r.get(k), v) for k, v in (filters or {}).items())]

            def select(self, columns="*", filters=None, order=None, limit=None, **_):
                rows = self._read(filters)
                return deepcopy(rows[:limit] if limit else rows)

            def insert(self, data):
                batch = data if isinstance(data, list) else [data]
                if isinstance(data, list):
                    keys = {frozenset(r) for r in batch}
                    assert len(keys) == 1, f"{name}: batch rows must share one key set"
                db.rows[name].extend(deepcopy(batch))
                db.log.append((name, "insert"))
                return deepcopy(batch)

            def update(self, data, filters, **_):
                hit = self._read(filters)
                for r in hit:
                    r.update(deepcopy(data))
                db.log.append((name, "update"))
                return deepcopy(hit)

            def upsert(self, data, on_conflict="id", **_):
                keys = on_conflict.split(",")
                hit = self._read({k: f"eq.{data[k]}" for k in keys})
                db.log.append((name, "upsert"))
                if hit:
                    for r in hit:
                        r.update(deepcopy(data))
                    return deepcopy(hit)
                row = {"id": f"{name}-auto-{len(db.rows[name])}", **deepcopy(data)}
                db.rows[name].append(row)
                return [deepcopy(row)]

        return Handle()


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    fake.rows["users"].append({"id": USER, "onboarding_completed": False, "deleted_at": None})
    fake.rows["user_profiles"].append({"user_id": USER, "name": "enc-name", "majors": []})
    # Three of the four codes are in the catalog; the fourth exercises the fallback.
    for n in (1, 2, 3):
        fake.rows["courses"].append({
            "id": f"course-{n}", "school_id": "school-bu",
            "course_code": f"CAS XX 10{n}", "course_name": f"Catalog Name {n}",
        })
    wiped_calls: list[str] = []

    def wipe_account_data(user_id):
        wiped_calls.append(user_id)
        fake.log.append(("*", "wipe"))
        return {"notes": 3, "documents": 1}

    monkeypatch.setattr(seeder, "wipe_account_data", wipe_account_data)
    monkeypatch.setattr(seeder, "table", fake.table)
    # The real account_exists (deleted_at-aware), pointed at this fake.
    from services import account_bundle

    monkeypatch.setattr(account_bundle, "table", fake.table)
    monkeypatch.setattr(seeder, "packs", lambda: {PACK.key: PACK})
    monkeypatch.setattr(seeder, "current_term", lambda today=None: {
        "id": "fall-2026", "start_date": TERM_START.isoformat(), "end_date": "2027-01-03",
    })
    monkeypatch.setattr(
        seeder, "resolve_offering",
        lambda course_id, term_id=None, **kw: f"off-{course_id}-{term_id}",
    )
    monkeypatch.setattr(seeder, "level_for_xp", lambda xp: 7)
    fake.wiped_calls = wiped_calls
    return fake


def _seed(db):
    return seeder.seed_account(USER, PACK.key, today=TODAY)


# ── validation happens before anything is written ────────────────────────────


def test_unknown_major_is_a_value_error_and_writes_nothing(db):
    with pytest.raises(ValueError):
        seeder.seed_account(USER, "astrology", today=TODAY)
    assert db.wiped_calls == []
    assert db.log == []


def test_unknown_user_is_a_lookup_error_and_wipes_nothing(db):
    with pytest.raises(seeder.UnknownAccount):
        seeder.seed_account("user_nobody", PACK.key, today=TODAY)
    assert db.wiped_calls == []
    assert db.log == []


def test_soft_deleted_user_is_unknown_and_wipes_nothing(db):
    db.rows["users"][0]["deleted_at"] = "2026-11-01T00:00:00+00:00"
    with pytest.raises(seeder.UnknownAccount):
        _seed(db)
    assert db.wiped_calls == []
    assert db.log == []


def test_no_terms_refuses_before_the_wipe(db, monkeypatch):
    monkeypatch.setattr(seeder, "current_term", lambda today=None: None)
    with pytest.raises(seeder.NoCurrentTerm):
        _seed(db)
    assert db.wiped_calls == []
    assert db.log == []


# ── ordering + result ────────────────────────────────────────────────────────


def test_wipe_runs_before_any_account_data_is_written(db):
    _seed(db)
    assert db.wiped_calls == [USER]
    wipe_at = db.log.index(("*", "wipe"))
    account_tables = set(seeder.INSERT_ORDER) | {"users", "user_profiles"}
    first_write = min(i for i, (t, _) in enumerate(db.log) if t in account_tables)
    assert wipe_at < first_write


def test_returns_major_wiped_and_created_counts(db):
    out = _seed(db)
    assert out["major"] == PACK.key
    assert out["wiped"] == {"notes": 3, "documents": 1}
    created = out["created"]
    assert created["enrollments"] == 4
    assert created["graph_nodes"] == 32
    assert created["assignments"] == 24
    assert created["documents"] == 8
    assert created["quiz_attempts"] == 8
    assert created["quiz_responses"] == 4 * (4 + 3)
    assert created["study_guides"] == 4
    assert created["sessions"] == 4 and created["messages"] == 16
    assert created["courses"] == 1  # only the code missing from the catalog
    for name, n in created.items():
        assert len(db.rows[name]) >= n


def test_inserts_are_batched_one_call_per_table(db):
    _seed(db)
    inserts = [t for t, op in db.log if op == "insert"]
    assert len(inserts) == len(set(inserts))


def test_reseeding_never_reuses_ids(db):
    _seed(db)
    first = {r["id"] for r in db.rows["graph_nodes"]}
    db.rows["graph_nodes"].clear()
    _seed(db)
    second = {r["id"] for r in db.rows["graph_nodes"]}
    assert first.isdisjoint(second)


# ── catalog resolution ───────────────────────────────────────────────────────


def test_missing_catalog_course_is_created_under_an_existing_school(db):
    _seed(db)
    made = [c for c in db.rows["courses"] if c["course_code"] == "CAS XX 104"]
    assert len(made) == 1 and made[0]["school_id"] == "school-bu"
    assert db.rows["schools"] == []
    offerings = {r["offering_id"] for r in db.rows["enrollments"]}
    assert offerings == {
        "off-course-1-fall-2026", "off-course-2-fall-2026", "off-course-3-fall-2026",
        f"off-{made[0]['id']}-fall-2026",
    }


def test_empty_catalog_falls_back_to_the_sample_school(db):
    db.rows["courses"].clear()
    _seed(db)
    assert [s["slug"] for s in db.rows["schools"]] == [seeder.SAMPLE_SCHOOL_SLUG]
    school_id = db.rows["schools"][0]["id"]
    assert len(db.rows["courses"]) == 4
    assert {c["school_id"] for c in db.rows["courses"]} == {school_id}


def test_graph_nodes_key_on_the_abstract_course(db):
    _seed(db)
    course_ids = {r["course_id"] for r in db.rows["graph_nodes"]}
    assert {"course-1", "course-2", "course-3"} <= course_ids


# ── gradebook ────────────────────────────────────────────────────────────────


def test_only_past_due_assignments_are_graded(db):
    _seed(db)
    by_title = defaultdict(list)
    for a in db.rows["assignments"]:
        by_title[a["title"]].append(a)
    for title, expect in [("HW 1", 91), ("HW 2", 84), ("HW 3", 45)]:
        for a in by_title[title]:
            assert date.fromisoformat(a["due_date"]) < TODAY
            assert decrypt_numeric(a["points_earned"]) == expect
    for title in ("HW 4", "Midterm", "Final"):
        for a in by_title[title]:
            assert a["points_earned"] is None
    hw4 = by_title["HW 4"][0]
    assert date.fromisoformat(hw4["due_date"]) == TERM_START + timedelta(days=55)
    assert decrypt_numeric(hw4["points_possible"]) == 100


def test_assignments_reference_their_enrollment_and_category(db):
    _seed(db)
    enrollments = {r["id"] for r in db.rows["enrollments"]}
    categories = {r["id"]: r for r in db.rows["gradebook_categories"]}
    for a in db.rows["assignments"]:
        assert a["enrollment_id"] in enrollments
        assert categories[a["category_id"]]["enrollment_id"] == a["enrollment_id"]


# ── encryption ───────────────────────────────────────────────────────────────


def _assert_encrypted(stored, plain):
    assert stored != plain
    assert decrypt_if_present(stored) == plain


def test_locked_text_columns_are_encrypted(db):
    _seed(db)
    note = db.rows["notes"][0]
    _assert_encrypted(note["title"], "Week 1 notes")
    _assert_encrypted(note["body"], "Plaintext note body. " * 6)
    doc = db.rows["documents"][0]
    _assert_encrypted(doc["summary"], PACK.courses[0].documents[0].summary)
    _assert_encrypted(doc["extracted_text"], _EXTRACTED)
    assert decrypt_json(doc["concept_notes"]) == [
        {"name": "Idea A1", "description": "First idea."}
    ]
    card = db.rows["flashcards"][0]
    _assert_encrypted(card["front"], "Front 0")
    _assert_encrypted(card["back"], "Back 0")
    msg = db.rows["messages"][0]
    _assert_encrypted(msg["content"], "Tutor message from the student.")
    asg = db.rows["assignments"][0]
    assert asg["points_possible"] not in ("100", 100)


def test_locked_json_columns_are_encrypted(db):
    _seed(db)
    guide = db.rows["study_guides"][0]
    content = decrypt_json(guide["content"])
    assert content["exam"] == "Midterm"
    assert content["overview"] == "What the midterm covers."
    assert [t["name"] for t in content["topics"]] == ["Topic one", "Topic two"]
    session = db.rows["sessions"][0]
    summary = decrypt_json(session["summary_json"])
    assert summary["bullets"] == ["Covered one", "Covered two"]
    assert "time_spent_minutes" in summary
    attempt = db.rows["quiz_attempts"][0]
    assert isinstance(attempt["questions_json"], str)
    assert isinstance(decrypt_json(attempt["questions_json"]), list)


# ── documents ────────────────────────────────────────────────────────────────


def test_documents_are_pending_and_private(db):
    _seed(db)
    for doc in db.rows["documents"]:
        assert doc["index_status"] == "pending"
        assert doc["shareability"] == "personal_notes"
        assert doc["shareability_confidence"] == 1.0
        assert doc["user_id"] == USER


def test_enrollment_points_at_its_syllabus_document(db):
    _seed(db)
    docs = {d["id"]: d for d in db.rows["documents"]}
    for e in db.rows["enrollments"]:
        assert docs[e["syllabus_doc_id"]]["category"] == "syllabus"
        assert docs[e["syllabus_doc_id"]]["offering_id"] == e["offering_id"]


def test_study_guide_targets_the_midterm(db):
    _seed(db)
    midterms = {a["id"]: a for a in db.rows["assignments"] if a["title"] == "Midterm"}
    for g in db.rows["study_guides"]:
        assert g["exam_id"] in midterms
        assert g["generated_at"][:10] <= TODAY.isoformat()


# ── graph ────────────────────────────────────────────────────────────────────


def test_graph_nodes_carry_tier_and_study_history(db):
    from learning.bkt import tier_for

    _seed(db)
    for n in db.rows["graph_nodes"]:
        assert n["mastery_tier"] == tier_for(n["mastery_score"])
        if n["mastery_score"] > 0:
            assert n["times_studied"] >= 1 and n["last_studied_at"]
        else:
            assert n["times_studied"] == 0 and n["last_studied_at"] is None
    tiers = {n["mastery_tier"] for n in db.rows["graph_nodes"]}
    assert tiers == {"mastered", "learning", "struggling", "unexplored"}
    node_ids = {n["id"] for n in db.rows["graph_nodes"]}
    for e in db.rows["graph_edges"]:
        assert e["source_node_id"] in node_ids and e["target_node_id"] in node_ids
    for link in db.rows["note_concepts"]:
        assert link["concept_node_id"] in node_ids


# ── quizzes ──────────────────────────────────────────────────────────────────


def test_quiz_attempts_store_the_real_wire_shape(db):
    from routes.quiz import _is_wire_question, _strip_answer_key

    _seed(db)
    first = db.rows["quiz_attempts"][0]
    questions = decrypt_json(first["questions_json"])
    assert all(_is_wire_question(q) for q in questions)
    assert _strip_answer_key(questions)  # the review projection accepts it
    for q in questions:
        assert [o["label"] for o in q["options"]] == ["A", "B", "C", "D"]
        assert sum(o["correct"] for o in q["options"]) == 1
        assert q["question_hash"]
    assert first["score"] == 3 and first["total"] == 4
    assert first["completed_at"][:10] == (TODAY - timedelta(days=5)).isoformat()
    answers = decrypt_json(first["answers_json"])
    graded = [
        a["selected_label"] == next(o["label"] for o in q["options"] if o["correct"])
        for a, q in zip(answers, questions)
    ]
    assert graded == [True, True, False, True]
    responses = [r for r in db.rows["quiz_responses"] if r["attempt_id"] == first["id"]]
    assert [r["is_correct"] for r in sorted(responses, key=lambda r: r["question_index"])] \
        == [True, True, False, True]


# ── account level ────────────────────────────────────────────────────────────


def test_xp_ledger_sums_to_pack_total_with_namespaced_keys(db):
    _seed(db)
    events = db.rows["xp_events"]
    assert sum(e["amount"] for e in events) == PACK.total_xp
    keys = [e["idempotency_key"] for e in events]
    assert len(keys) == len(set(keys))
    assert all(k.startswith(f"seed:{USER}:") for k in keys)
    assert {e["rule_key"] for e in events} <= {
        "quiz_completed", "session_completed", "document_uploaded", "note_created",
        "daily_goal_met",
    }
    assert all(e["created_at"][:10] <= TODAY.isoformat() for e in events)


def test_user_counters_and_profile(db):
    _seed(db)
    user = db.rows["users"][0]
    assert user["onboarding_completed"] is True
    assert user["total_xp"] == PACK.total_xp
    assert user["level"] == 7
    assert user["streak_count"] == PACK.streak_days
    assert user["longest_streak"] >= PACK.streak_days
    assert user["last_active_date"] == TODAY.isoformat()
    profile = db.rows["user_profiles"][0]
    assert profile["majors"] == ["Test Major"]
    assert profile["year"] == "Junior"
    assert profile["name"] == "enc-name"  # upsert merged, didn't clobber


def test_xp_budget_smaller_than_activity_still_sums_exactly(db, monkeypatch):
    small = PACK.model_copy(update={"total_xp": 100, "streak_days": 3})
    monkeypatch.setattr(seeder, "packs", lambda: {small.key: small})
    _seed(db)
    assert sum(e["amount"] for e in db.rows["xp_events"]) == 100
