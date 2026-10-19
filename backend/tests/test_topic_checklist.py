"""Exercise the real checklist service against persistent in-memory table state."""
import copy
import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from agents.topic_checklist import TopicOutline, topic_checklist_agent
from services import topic_checklist_service as svc
from services.encryption import decrypt_json, encrypt_if_present

NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)


def outline():
    return TopicOutline.model_validate({"topics": [
        {"name": "Functions", "description": "Inputs, outputs and function composition.",
         "importance": 0.7, "source_ids": ["course-description"]},
        {"name": "Recursion", "description": "Base cases and recursive calls.", "parent": "Functions",
         "prerequisites": ["Functions"], "importance": 0.9,
         "source_ids": ["document:doc"], "assessment_ids": ["exam"]},
    ]})


class MemoryTable:
    def __init__(self, db, name):
        self.db, self.name = db, name

    def matches(self, row, filters):
        for key, expression in (filters or {}).items():
            if key == "and":
                if row.get("due_date", "") > expression.split("lte.")[1].rstrip(")"):
                    return False
                continue
            op, value = expression.split(".", 1)
            actual = row.get(key)
            if op == "eq" and actual != value:
                return False
            if op == "neq" and actual == value:
                return False
            if op == "is" and value == "null" and actual is not None:
                return False
            if op == "in" and actual not in value.strip("()").split(","):
                return False
            if op == "gte" and (actual is None or actual < value):
                return False
        return True

    def select(self, columns="*", filters=None, order=None, limit=None, offset=None):
        rows = [copy.deepcopy(row) for row in self.db.setdefault(self.name, []) if self.matches(row, filters)]
        for field in reversed((order or "").split(",")):
            if field:
                rows.sort(key=lambda r: r.get(field.split(".")[0], "") or "", reverse=field.endswith(".desc"))
        rows = rows[offset or 0:]
        return rows if limit is None else rows[:limit]

    def select_with_count(self, columns="*", filters=None, order=None, limit=None, offset=None):
        return self.select(columns, filters, order, limit, offset), len(self.select(columns, filters))

    def upsert(self, row, on_conflict):
        rows = self.db.setdefault(self.name, [])
        keys = on_conflict.split(",")
        existing = next((r for r in rows if all(r[k] == row[k] for k in keys)), None)
        if existing is None:
            rows.append(copy.deepcopy(row))
        else:
            existing.update(copy.deepcopy(row))
        return [row]

    def delete(self, filters):
        self.db[self.name] = [r for r in self.db.get(self.name, []) if not self.matches(r, filters)]
        return []


@pytest.fixture
def state(monkeypatch):
    db = {
        "courses": [{"id": "course", "course_code": "CAS CS 111", "course_name": "Intro CS",
                     "description": "Functions and recursion."}],
        "course_offerings": [
            {"id": "off", "course_id": "course", "term_id": "fall", "created_at": "2026-08-01"},
            {"id": "old-off", "course_id": "course", "term_id": "spring", "created_at": "2026-01-01"},
        ],
        "terms": [{"id": "fall", "label": "Fall 2026", "sort_key": 20263}, {"id": "spring", "label": "Spring 2026", "sort_key": 20261}],
        "enrollments": [{"id": "enr", "user_id": "u", "offering_id": "off"},
                        {"id": "old-enr", "user_id": "u", "offering_id": "old-off"}],
        "documents": [{"id": "doc", "user_id": "u", "offering_id": "off", "file_name": "Midterm guide.pdf",
                       "extracted_text": encrypt_if_present("The midterm tests recursion and base cases."), "created_at": "2026-10-01"}],
        "assignments": [{"id": "exam", "enrollment_id": "enr", "title": "Recursion Midterm",
                         "assignment_type": "exam", "due_date": "2026-10-15", "notes": encrypt_if_present("Recursion")},
                        {"id": "late", "enrollment_id": "enr", "title": "Final", "assignment_type": "exam", "due_date": "2026-12-15"}],
        "graph_nodes": [{"id": "n", "user_id": "u", "course_id": "course", "concept_name": "Recursion",
                         "mastery_score": 0.3, "mastery_tier": "struggling", "times_studied": 1,
                         "last_studied_at": "2026-10-11T12:00:00Z"}],
    }
    monkeypatch.setattr(svc, "table", lambda name: MemoryTable(db, name))
    monkeypatch.setattr(svc, "current_term", lambda: {"id": "fall"})
    monkeypatch.setattr(svc, "term_id_for_label", lambda label: {"Fall 2026": "fall", "Spring 2026": "spring"}.get(label))

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(svc, "datetime", FrozenDatetime)
    calls = []

    async def generate(payload, user_id):
        assert user_id == "u"
        calls.append(payload)
        return outline()

    monkeypatch.setattr(svc, "_generate", generate)
    return db, calls


def test_get_never_calls_model_and_refresh_is_encrypted_idempotent(state):
    db, calls = state
    assert svc.get_checklist("u", "course")["needs_refresh"]
    assert calls == []
    result = svc.refresh_checklist("u", "course")
    assert not result["needs_refresh"]
    stored = copy.deepcopy(db["topic_checklists"])
    assert "Recursion" not in stored[0]["content"]
    assert decrypt_json(stored[0]["content"]) == outline().model_dump()
    assert svc.refresh_checklist("u", "course")["topics"] == result["topics"]
    assert len(calls) == 1 and db["topic_checklists"] == stored


def test_live_priorities_and_manual_checkmark_do_not_raise_mastery(state):
    db, _ = state
    result = svc.refresh_checklist("u", "course")
    recursion = result["topics"][0]
    assert recursion["name"] == "Recursion" and recursion["priority"] == "high"
    assert recursion["status"] == "needs_review" and recursion["review_reasons"] == ["Weak mastery"]
    assert recursion["prerequisite_gaps"] == ["Functions"]
    before = copy.deepcopy(db["graph_nodes"])
    checked = svc.set_reviewed("u", "course", recursion["id"], True)
    assert checked["topics"][0]["checked"] is True
    assert checked["topics"][0]["status"] == "needs_review"
    assert db["graph_nodes"] == before
    assert svc.set_reviewed("u", "course", recursion["id"], False)["topics"][0]["checked"] is False


def test_seeded_mastery_without_study_history_needs_review_only_after_checking(state):
    db, _ = state
    db["graph_nodes"][0].update(mastery_score=0.25, times_studied=0, last_studied_at=None)
    original = copy.deepcopy(db["graph_nodes"])
    initial = svc.refresh_checklist("u", "course")["topics"][0]
    assert initial["name"] == "Recursion" and initial["status"] == "not_started"
    assert initial["checked"] is False and initial["mastery_score"] == 0.25

    reviewed = svc.set_reviewed("u", "course", initial["id"], True)["topics"][0]
    assert reviewed["checked"] is True and reviewed["status"] == "needs_review"
    assert reviewed["review_reasons"] == ["Weak mastery"]
    assert svc.get_checklist("u", "course")["topics"][0]["checked"] is True
    unchecked = svc.set_reviewed("u", "course", initial["id"], False)["topics"][0]
    assert unchecked["checked"] is False and unchecked["status"] == "not_started"
    assert db["graph_nodes"] == original


def test_seven_day_review_boundary_and_unstudied_topics(state):
    db, _ = state
    db["graph_nodes"][0].update(mastery_score=0.9, last_studied_at="2026-10-05T12:00:00Z")
    result = svc.refresh_checklist("u", "course")
    by_name = {t["name"]: t for t in result["topics"]}
    assert by_name["Functions"]["status"] == "not_started"
    assert by_name["Recursion"]["status"] == "needs_review"
    assert by_name["Recursion"]["review_reasons"] == ["Review overdue"]
    checked = svc.set_reviewed("u", "course", svc.topic_key("Recursion"), True)
    assert next(t for t in checked["topics"] if t["name"] == "Recursion")["status"] == "mastered"


def test_mastery_updates_do_not_regenerate_but_new_materials_do(state):
    db, calls = state
    svc.refresh_checklist("u", "course")
    svc.set_reviewed("u", "course", svc.topic_key("Functions"), True)
    db["graph_nodes"][0]["mastery_score"] = 0.9
    assert not svc.get_checklist("u", "course")["needs_refresh"]
    db["documents"][0]["extracted_text"] = encrypt_if_present("A revised midterm covers recursion.")
    assert svc.get_checklist("u", "course")["needs_refresh"]
    result = svc.refresh_checklist("u", "course")
    assert len(calls) == 2
    assert next(t for t in result["topics"] if t["name"] == "Functions")["checked"]


def test_sources_and_assessments_are_owner_offering_scoped(state):
    db, calls = state
    db["documents"].extend([
        {"id": "other", "user_id": "other", "offering_id": "off", "file_name": "Private", "extracted_text": encrypt_if_present("SECRET"), "created_at": "2026-10-11"},
        {"id": "old", "user_id": "u", "offering_id": "old-off", "file_name": "Archived", "extracted_text": encrypt_if_present("OLD"), "created_at": "2026-01-11"},
    ])
    svc.refresh_checklist("u", "course", "Fall 2026")
    payload = calls[0]
    assert {s["id"] for s in payload["sources"]} == {"course-description", "document:doc", "assessment:exam", "concept:n"}
    assert [a["id"] for a in payload["assessments"]] == ["exam"]
    assert "SECRET" not in str(payload) and "OLD" not in str(payload)
    scope = svc.resolve_scope("u", "course", "Spring 2026")
    assert scope["enrollment_id"] == "old-enr"
    old_sources = svc.build_snapshot("u", scope, NOW.date())["payload"]["sources"]
    assert {s["id"] for s in old_sources if s["id"].startswith("document:")} == {"document:old"}


@pytest.mark.parametrize("user,course,semester", [("other", "course", None), ("u", "unknown", None), ("u", "course", "Unknown")])
def test_unowned_or_unknown_scope_fails_before_writes(state, user, course, semester):
    db, calls = state
    with pytest.raises(HTTPException) as err:
        svc.refresh_checklist(user, course, semester)
    assert err.value.status_code == 404 and calls == []
    assert not db.get("topic_checklists")


def test_explicit_unenrolled_semester_never_falls_back(state):
    db, _ = state
    db["enrollments"] = [db["enrollments"][0]]
    with pytest.raises(HTTPException, match="404"):
        svc.get_checklist("u", "course", "Spring 2026")


def test_generation_failure_preserves_existing_data_and_checks(state, monkeypatch):
    db, _ = state
    svc.refresh_checklist("u", "course")
    svc.set_reviewed("u", "course", svc.topic_key("Functions"), True)
    stored = copy.deepcopy(db["topic_checklists"])
    db["courses"][0]["description"] += " Loops."

    async def broken(payload, user_id):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(svc, "_generate", broken)
    with pytest.raises(HTTPException) as err:
        svc.refresh_checklist("u", "course")
    assert err.value.status_code == 503
    assert db["topic_checklists"] == stored
    assert db["topic_checklist_progress"]


def test_no_evidence_produces_empty_state_without_guessing(state):
    db, calls = state
    db["courses"][0]["description"] = None
    db["documents"] = db["graph_nodes"] = db["assignments"] = []
    result = svc.refresh_checklist("u", "course")
    assert result["topics"] == [] and not result["needs_refresh"]
    assert "No course evidence" in result["warnings"][0]
    assert calls == []


def test_wrong_evidence_is_rejected_before_persistence(state, monkeypatch):
    db, _ = state

    async def invalid(payload, user_id):
        value = outline()
        value.topics[0].source_ids = ["document:another-student"]
        return value

    monkeypatch.setattr(svc, "_generate", invalid)
    with pytest.raises(HTTPException) as err:
        svc.refresh_checklist("u", "course")
    assert err.value.status_code == 503 and not db.get("topic_checklists")


def test_unknown_topic_cannot_write_progress(state):
    db, _ = state
    svc.refresh_checklist("u", "course")
    with pytest.raises(HTTPException) as err:
        svc.set_reviewed("u", "course", "unknown", True)
    assert err.value.status_code == 404 and not db.get("topic_checklist_progress")


def test_prompt_budget_is_explicit_and_catalog_is_decrypted(state):
    db, _ = state
    db["course_chunks"] = [{"id": "cat", "course_id": "CAS CS 111", "category": "catalog",
                            "chunk_text": encrypt_if_present("Prerequisites: functions. " * 1000)}]
    scope = svc.resolve_scope("u", "course", None)
    snapshot = svc.build_snapshot("u", scope, NOW.date())
    assert snapshot["truncated"]
    assert any(s["id"] == "catalog:cat" and s["text"].startswith("Prerequisites:") for s in snapshot["payload"]["sources"])
    assert sum(len(s["text"]) for s in snapshot["payload"]["sources"]) <= svc.MAX_SOURCE_CHARS
    assert sum(len(json.dumps(s)) for s in snapshot["payload"]["sources"]) <= svc.MAX_SOURCE_CHARS


@pytest.mark.parametrize("change", ["duplicate", "blank", "blank-description", "missing-parent", "cycle", "prerequisite-cycle", "bad-prerequisite"])
def test_outline_validates_topic_organization(change):
    value = outline().model_dump()
    if change == "duplicate":
        value["topics"][1]["name"] = " functions "
    elif change == "blank":
        value["topics"][0]["name"] = " "
    elif change == "blank-description":
        value["topics"][0]["description"] = " "
    elif change == "missing-parent":
        value["topics"][1]["parent"] = "Missing"
    elif change == "cycle":
        value["topics"][0]["parent"] = "Recursion"
    elif change == "prerequisite-cycle":
        value["topics"][0]["prerequisites"] = ["Recursion"]
    else:
        value["topics"][1]["prerequisites"] = ["Missing"]
    with pytest.raises(ValidationError):
        TopicOutline.model_validate(value)


def test_real_agent_retries_unknown_source_then_accepts_valid_outline():
    calls = []

    def handler(messages, info):
        value = outline().model_dump()
        if not calls:
            value["topics"][0]["source_ids"] = ["wrong"]
        calls.append(value)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, value)])

    payload = {"sources": [{"id": "course-description"}, {"id": "document:doc"}], "assessments": [{"id": "exam"}]}
    with topic_checklist_agent.override(model=FunctionModel(handler)):
        result = topic_checklist_agent.run_sync("Generate checklist", deps=payload)
    assert result.output == outline() and len(calls) == 2


def test_current_term_fallback_uses_term_order_not_creation_time(state, monkeypatch):
    db, _ = state
    db["course_offerings"][1]["created_at"] = "2026-12-01"
    monkeypatch.setattr(svc, "current_term", lambda: {"id": "future-unenrolled"})
    assert svc.resolve_scope("u", "course", None)["enrollment_id"] == "enr"


def test_review_dates_accept_legacy_utc_and_topic_keys_normalize_names(state):
    db, _ = state
    db["graph_nodes"][0]["last_studied_at"] = "2026-10-01T12:00:00"
    result = svc.refresh_checklist("u", "course")
    assert "Review overdue" in result["topics"][0]["review_reasons"]
    assert svc.topic_key("  RECURSION  ") == svc.topic_key("Recursion")


def test_assessment_window_changes_invalidate_the_cached_outline(state):
    db, _ = state
    scope = svc.resolve_scope("u", "course", None)
    before = svc.build_snapshot("u", scope, NOW.date())
    after = svc.build_snapshot("u", scope, NOW.date().replace(day=16))
    assert before["hash"] != after["hash"]
    assert after["payload"]["assessments"] == []


def test_generation_rate_limit_and_cached_reads(state):
    db, calls = state
    for index in range(6):
        db["courses"][0]["description"] += f" Topic {index}."
        svc.refresh_checklist("u", "course")
    assert len(calls) == 6
    assert svc.refresh_checklist("u", "course")["topics"]
    db["courses"][0]["description"] += " New topic."
    with pytest.raises(HTTPException) as err:
        svc.refresh_checklist("u", "course")
    assert err.value.status_code == 429 and "Retry-After" in err.value.headers
    assert svc.get_checklist("u", "course")["topics"]


def test_deleted_documents_disappear_from_sources(state):
    db, _ = state
    db["documents"][0]["deleted_at"] = "2026-10-11"
    scope = svc.resolve_scope("u", "course", None)
    assert all(s["id"] != "document:doc" for s in svc.build_snapshot("u", scope, NOW.date())["payload"]["sources"])


def test_prerequisite_relationships_are_scoped_to_owned_course_nodes(state):
    db, _ = state
    db["graph_nodes"].append({**db["graph_nodes"][0], "id": "fn", "concept_name": "Functions"})
    db["graph_edges"] = [
        {"id": "edge", "user_id": "u", "source_node_id": "fn", "target_node_id": "n", "relationship_type": "prerequisite"},
        {"id": "outside", "user_id": "u", "source_node_id": "fn", "target_node_id": "other-course-node", "relationship_type": "prerequisite"},
        {"id": "private", "user_id": "other", "source_node_id": "fn", "target_node_id": "n", "relationship_type": "prerequisite"},
    ]
    snapshot = svc.build_snapshot("u", svc.resolve_scope("u", "course", None), NOW.date())
    relationships = [s for s in snapshot["payload"]["sources"] if s["id"].startswith("relationship:")]
    assert relationships == [{"id": "relationship:edge", "label": "Tracked course relationship", "text": "Functions is a prerequisite for Recursion."}]


def test_unicode_and_metadata_cannot_bypass_source_budget(state):
    db, _ = state
    db["documents"][0]["extracted_text"] = encrypt_if_present("数学" * 40000)
    db["graph_nodes"] = [{**db["graph_nodes"][0], "id": f"node-{i}", "concept_name": f"x{i}"} for i in range(1200)]
    snapshot = svc.build_snapshot("u", svc.resolve_scope("u", "course", None), NOW.date())
    assert snapshot["truncated"] and len(snapshot["nodes"]) == 1200
    assert sum(len(json.dumps(s)) for s in snapshot["payload"]["sources"]) <= svc.MAX_SOURCE_CHARS
