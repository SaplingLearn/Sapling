"""Assessment scope, encrypted persistence, schedule constraints and live mastery."""
import copy
from datetime import date
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from agents.topic_checklist import TopicOutline
from agents.assessment_guide import AssessmentGuide
from services import study_plan_service as svc
from services.encryption import decrypt_json, encrypt_if_present
from learning.params import BKT_PROFICIENT


class Store:
    def __init__(self, db, name):
        self.db, self.name = db, name

    def select(self, columns="*", filters=None, order=None, limit=None, offset=None):
        def matches(row):
            for key, expr in (filters or {}).items():
                op, value = expr.split(".", 1)
                actual = row.get(key)
                if op == "eq" and str(actual) != value:
                    return False
                if op == "neq" and str(actual) == value:
                    return False
                if op == "in" and actual not in value.strip("()").split(","):
                    return False
                if op == "is" and actual is not None:
                    return False
            return True
        rows = [copy.deepcopy(r) for r in self.db.setdefault(self.name, []) if matches(r)]
        return rows[offset or 0:][:limit] if limit else rows[offset or 0:]

    def insert(self, row):
        self.db.setdefault(self.name, []).append(copy.deepcopy(row))
        return [copy.deepcopy(row)]

    def select_with_count(self, columns="*", filters=None, order=None, limit=None, offset=None):
        return self.select(columns, filters, order, limit, offset), len(self.select(columns, filters))

    def update(self, changes, filters):
        matches = {r["id"] for r in self.select(filters=filters)}
        for row in self.db[self.name]:
            if row["id"] in matches:
                row.update(copy.deepcopy(changes))
        return self.select(filters={"id": filters["id"]}) if matches else []

    def delete(self, filters):
        matches = self.select(filters=filters)
        self.db[self.name] = [r for r in self.db[self.name] if r not in matches]
        return matches


@pytest.fixture
def state(monkeypatch):
    db = {
        "documents": [{"id": "doc", "user_id": "u", "offering_id": "off", "file_name": "Review.pdf",
                       "extracted_text": encrypt_if_present("Functions and recursion"), "deleted_at": None}],
        "assignments": [{"id": "exam", "enrollment_id": "enr", "title": "Midterm", "notes": encrypt_if_present("Functions and recursion")}],
        "graph_nodes": [{"id": "node", "user_id": "u", "course_id": "course", "concept_name": "Recursion",
                         "mastery_score": .3, "times_studied": 1, "mastery_tier": "struggling"}],
    }
    monkeypatch.setattr(svc, "table", lambda name: Store(db, name))
    monkeypatch.setattr(svc, "_today", lambda tz: date(2026, 10, 21))
    monkeypatch.setattr(svc.checklist, "resolve_scope", lambda user, course, term: {
        "course": {"id": course, "course_code": "CS 111", "course_name": "Intro CS"},
        "offering_id": "off", "enrollment_id": "enr" if term != "old" else "old-enr", "semester": term or "Fall 2026",
    })
    calls = []

    def generate(payload, *args):
        calls.append(payload)
        return AssessmentGuide.model_validate({"overview": "Prepare by connecting functions to recursive calls.", "topics": [
            {"name": "Functions", "description": "Inputs and outputs", "importance": .8, "source_ids": ["document:doc"], "study_points": ["Explain function inputs and outputs."]},
            {"name": "Recursion", "description": "Base cases", "importance": .9, "source_ids": ["document:doc"],
             "parent": "Functions", "prerequisites": ["Functions"], "study_points": ["Identify a base case."]},
        ]})

    monkeypatch.setattr(svc, "generate_topics", generate)
    return db, calls


def request(**kwargs):
    return svc.PlanCreate(title="Midterm", assessment_date="2026-10-30", start_date="2026-10-21",
                          document_ids=["doc"], assignment_ids=["exam"], **kwargs)


def test_creation_uses_only_selected_owned_evidence_and_encrypts(state):
    db, calls = state
    plan = svc.create_plan("u", "course", request())
    assert plan["version"] == 1 and len(plan["topics"]) == 2
    assert plan["guide_overview"] == "Prepare by connecting functions to recursive calls."
    assert plan["topics"][0]["study_points"] == ["Explain function inputs and outputs."]
    assert {s["id"] for s in calls[0]["sources"]} == {"document:doc", "assignment:exam"}
    assert "Functions and recursion" in str(calls[0])
    assert "Midterm" not in db["assessment_study_plans"][0]["content"]
    assert decrypt_json(db["assessment_study_plans"][0]["content"])["title"] == "Midterm"
    with pytest.raises(HTTPException) as error:
        svc.create_plan("other", "course", request())
    assert error.value.status_code == 404


def test_manual_assessment_date_accepts_undated_documents_and_assignments(state):
    db, calls = state
    db["assignments"][0]["due_date"] = None
    db["documents"][0]["concept_notes"] = [{"concept": "Recursion", "notes": "Base cases"}]
    available = svc.list_sources("u", "course")
    assert available["documents"][0]["id"] == "doc"
    assert available["assignments"][0]["due_date"] is None
    plan = svc.create_plan("u", "course", request())
    assert plan["assessment_date"] == "2026-10-30"
    assert plan["assignment_ids"] == ["exam"] and plan["document_ids"] == ["doc"]
    assert "Base cases" in str(calls[0])
    # A dated assignment isn't required at all: documents plus a manually
    # entered assessment date also create an independent assessment plan.
    data = request().model_copy(update={"assignment_ids": []})
    standalone = svc.create_plan("u", "course", data)
    assert standalone["assessment_date"] == "2026-10-30" and standalone["assignment_ids"] == []


def test_mastery_is_live_and_sessions_do_not_manufacture_mastery(state):
    db, calls = state
    plan = svc.create_plan("u", "course", request())
    original = db["graph_nodes"][0].copy()
    updated = svc.update_plan("u", "course", UUID(plan["id"]), svc.PlanUpdate(version=1,
        session={"id": plan["sessions"][0]["id"], "completed": True}))
    assert db["graph_nodes"][0] == original
    assert updated["mastered_count"] == 0
    db["graph_nodes"][0]["mastery_score"] = BKT_PROFICIENT
    read = svc.list_plans("u", "course")["plans"][0]
    assert read["mastered_count"] == 1
    assert next(t for t in read["topics"] if t["name"] == "Recursion")["checked"]
    assert len(calls) == 1  # Reads never regenerate topics.
    assert svc.list_plans("u", "course", "old")["plans"] == []


def test_schedule_respects_dates_days_capacity_and_prerequisites(state):
    plan = svc.create_plan("u", "course", request(study_days=[0, 2, 4], minutes_per_day=25))
    totals = {}
    for session in plan["sessions"]:
        day = date.fromisoformat(session["scheduled_date"])
        assert date(2026, 10, 21) <= day < date(2026, 10, 30)
        assert day.weekday() in [0, 2, 4]
        totals[day] = totals.get(day, 0) + session["minutes"]
    assert all(total <= 25 for total in totals.values())
    first = {t["name"]: next(s["scheduled_date"] for s in plan["sessions"] if s["topic_id"] == t["id"]) for t in plan["topics"]}
    assert first["Functions"] <= first["Recursion"]


def test_over_capacity_and_no_available_days_are_explicit(state):
    plan = svc.create_plan("u", "course", request(study_days=[1], minutes_per_day=15))
    assert len(plan["sessions"]) == 1 and "could not fit" in " ".join(plan["warnings"])
    content = {**plan, "study_days": [1], "assessment_date": "2026-10-22"}
    sessions, warnings = svc.build_schedule(content, [], date(2026, 10, 21))
    assert not sessions and warnings


def test_replan_preserves_completed_sessions_without_repeating_initial_study(state):
    plan = svc.create_plan("u", "course", request())
    session = plan["sessions"][0]
    plan = svc.update_plan("u", "course", UUID(plan["id"]), svc.PlanUpdate(version=1,
        session={"id": session["id"], "completed": True}))
    plan = svc.update_plan("u", "course", UUID(plan["id"]), svc.PlanUpdate(version=2, regenerate=True))
    assert next(s for s in plan["sessions"] if s["id"] == session["id"])["completed"]
    assert len([s for s in plan["sessions"] if s["topic_id"] == session["topic_id"] and s["kind"] == "study"]) == 1


def test_updates_reject_cross_semester_stale_versions_and_invalid_rescheduling(state):
    plan = svc.create_plan("u", "course", request(study_days=[0, 2, 4]))
    with pytest.raises(HTTPException) as error:
        svc.update_plan("u", "course", UUID(plan["id"]), svc.PlanUpdate(version=9, regenerate=True))
    assert error.value.status_code == 409
    for target in ("2026-10-20", "2026-10-30", "2026-10-22"):
        with pytest.raises(HTTPException) as error:
            svc.update_plan("u", "course", UUID(plan["id"]), svc.PlanUpdate(version=1,
                session={"id": plan["sessions"][0]["id"], "scheduled_date": target}))
        assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        svc.update_plan("u", "course", UUID(plan["id"]), svc.PlanUpdate(version=1, regenerate=True), "old")
    assert error.value.status_code == 404


def test_topic_edits_validate_evidence_references_and_cycles(state):
    plan = svc.create_plan("u", "course", request())
    topics = decrypt_json(state[0]["assessment_study_plans"][0]["content"])["topics"]
    bad = copy.deepcopy(topics)
    bad[0]["source_ids"] = ["document:other-user"]
    with pytest.raises(HTTPException):
        svc.update_plan("u", "course", UUID(plan["id"]), svc.PlanUpdate(version=1, topics=bad))
    bad = copy.deepcopy(topics)
    bad[0]["prerequisite_ids"] = [bad[1]["id"]]
    with pytest.raises(HTTPException):
        svc.update_plan("u", "course", UUID(plan["id"]), svc.PlanUpdate(version=1, topics=bad))
    topics[0]["name"] = "Function composition"
    updated = svc.update_plan("u", "course", UUID(plan["id"]), svc.PlanUpdate(version=1, topics=topics))
    assert updated["topics"][0]["name"] == "Function composition" and updated["version"] == 2


def test_atomic_conflict_and_model_failure_do_not_overwrite(state, monkeypatch):
    plan = svc.create_plan("u", "course", request())
    saved = copy.deepcopy(state[0]["assessment_study_plans"])
    monkeypatch.setattr(Store, "update", lambda *args, **kwargs: [])
    with pytest.raises(HTTPException) as error:
        svc.update_plan("u", "course", UUID(plan["id"]), svc.PlanUpdate(version=1, title="Changed"))
    assert error.value.status_code == 409 and state[0]["assessment_study_plans"] == saved

    def fail(payload, *args):
        raise RuntimeError("Model unavailable")
    monkeypatch.setattr(svc, "generate_topics", fail)
    with pytest.raises(HTTPException) as error:
        svc.create_plan("u", "course", request())
    assert error.value.status_code == 503 and state[0]["assessment_study_plans"] == saved


def test_timing_edits_rebuild_schedule_but_cannot_change_coverage(state):
    plan = svc.create_plan("u", "course", request())
    settings = request(minutes_per_day=15, study_days=[0, 2, 4]).model_dump(mode="json")
    settings["assessment_date"] = "2026-11-02"
    changed = svc.update_plan("u", "course", UUID(plan["id"]), svc.PlanUpdate(version=1, settings=settings))
    assert changed["assessment_date"] == "2026-11-02"
    assert all(s["minutes"] == 15 for s in changed["sessions"])
    settings["coverage"] = "A different exam"
    with pytest.raises(HTTPException) as error:
        svc.update_plan("u", "course", UUID(plan["id"]), svc.PlanUpdate(version=2, settings=settings))
    assert error.value.status_code == 422


def test_sources_and_deletion_are_enrollment_scoped(state):
    db, _ = state
    db["documents"].append({"id": "private", "user_id": "other", "offering_id": "off", "deleted_at": None})
    sources = svc.list_sources("u", "course")
    assert [d["id"] for d in sources["documents"]] == ["doc"]
    assert svc.list_sources("u", "course", "old")["assignments"] == []
    plan = svc.create_plan("u", "course", request())
    with pytest.raises(HTTPException) as error:
        svc.delete_plan("u", "course", UUID(plan["id"]), "old")
    assert error.value.status_code == 404
    assert svc.delete_plan("u", "course", UUID(plan["id"])) == {"deleted": True}
    assert svc.list_plans("u", "course")["plans"] == []


def test_rescheduling_checks_capacity_and_persists_valid_moves(state):
    plan = svc.create_plan("u", "course", request(minutes_per_day=25))
    first, second = plan["sessions"][:2]
    with pytest.raises(HTTPException) as error:
        svc.update_plan("u", "course", UUID(plan["id"]), svc.PlanUpdate(version=1,
            session={"id": second["id"], "scheduled_date": first["scheduled_date"]}))
    assert error.value.status_code == 422
    dates = {s["scheduled_date"] for s in plan["sessions"]}
    target = next(date(2026, 10, day).isoformat() for day in range(21, 30) if date(2026, 10, day).isoformat() not in dates)
    changed = svc.update_plan("u", "course", UUID(plan["id"]), svc.PlanUpdate(version=1,
        session={"id": first["id"], "scheduled_date": target}))
    assert next(s for s in changed["sessions"] if s["id"] == first["id"])["scheduled_date"] == target


def test_rate_limit_and_invalid_generated_evidence_never_persist(state, monkeypatch):
    monkeypatch.setattr(svc, "check_rate_limit", lambda *args, **kwargs: 30)
    with pytest.raises(HTTPException) as error:
        svc.create_plan("u", "course", request())
    assert error.value.status_code == 429 and error.value.headers["Retry-After"] == "30"
    assert not state[0].get("assessment_study_plans")
    monkeypatch.setattr(svc, "check_rate_limit", lambda *args, **kwargs: None)

    def invalid(payload, *args):
        return TopicOutline.model_validate({"topics": [{"name": "Private topic", "description": "Unsupported",
            "importance": .8, "source_ids": ["document:other-user"]}]})
    monkeypatch.setattr(svc, "generate_topics", invalid)
    with pytest.raises(HTTPException) as error:
        svc.create_plan("u", "course", request())
    assert error.value.status_code == 503 and not state[0].get("assessment_study_plans")


def test_create_preserves_the_shared_budget_error_for_the_api_handler(state, monkeypatch):
    from types import SimpleNamespace

    def capped(*args):
        raise svc.ai_budget.AIBudgetExceeded(SimpleNamespace(level="hard"))
    monkeypatch.setattr(svc, "generate_topics", capped)
    with pytest.raises(svc.ai_budget.AIBudgetExceeded):
        svc.create_plan("u", "course", request())
    assert not state[0].get("assessment_study_plans")


@pytest.mark.parametrize("changes", [
    {"study_days": []}, {"study_days": [7]}, {"study_days": [True]}, {"minutes_per_day": 0},
    {"assessment_date": "2026-10-21"}, {"timezone": "bad/timezone"},
    {"document_ids": ["doc),user_id.eq.other"]},
])
def test_invalid_inputs(changes):
    data = request().model_dump()
    with pytest.raises(ValidationError):
        svc.PlanCreate.model_validate({**data, **changes})


def test_automatic_time_spreads_daily_focus_and_recomputes_after_date_edit(state):
    plan = svc.create_plan("u", "course", request())
    assert plan["automatic_time"] is True
    assert plan["minutes_per_day"] == 25
    study = [s for s in plan["sessions"] if s["kind"] == "study"]
    assert len({s["scheduled_date"] for s in study}) == len(study)
    settings = request().model_dump(mode="json")
    settings["assessment_date"] = "2026-10-22"
    changed = svc.update_plan("u", "course", UUID(plan["id"]), svc.PlanUpdate(version=1, settings=settings))
    assert changed["automatic_time"] is True
    assert changed["minutes_per_day"] > plan["minutes_per_day"]
