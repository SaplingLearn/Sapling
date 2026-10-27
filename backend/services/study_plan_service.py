"""Private assessment plans: bounded evidence extraction and deterministic scheduling.

Completion of a study session records activity, never mastery. Topic completion
is derived on every read from the same course graph used by the knowledge map.
"""
from __future__ import annotations

import logging
import math
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

import config
from agents._providers import model_mode, model_name_for
from agents._run import run_agent_sync
from agents.topic_checklist import normalized_name
from agents.assessment_guide import assessment_guide_agent
from learning.bkt import in_mastered_tier, is_weak
from db.connection import page_all, table
from services.encryption import decrypt_if_present, decrypt_json, encrypt_json
from services.request_limits import check_rate_limit
from services import topic_checklist_service as checklist
from services import ai_budget, checklist_budget

logger = logging.getLogger(__name__)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PlanCreate(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    assessment_type: Literal["quiz", "exam"] = "exam"
    assessment_date: date
    start_date: date
    timezone: str = Field(default="UTC", max_length=64)
    coverage: str = Field(default="", max_length=4000)
    document_ids: list[str] = Field(default_factory=list, max_length=20)
    assignment_ids: list[str] = Field(default_factory=list, max_length=20)
    study_days: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    minutes_per_day: int | None = Field(default=None, ge=15, le=480, strict=True)

    @field_validator("document_ids", "assignment_ids")
    @classmethod
    def safe_ids(cls, values):
        if any(not v or len(v) > 128 or not all(c.isalnum() or c in "_-" for c in v) for v in values):
            raise ValueError("Invalid source identifier.")
        return list(dict.fromkeys(values))

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose a valid timezone.") from None
        return value

    @field_validator("study_days", mode="before")
    @classmethod
    def valid_days(cls, values):
        if not isinstance(values, list) or any(type(v) is not int or v not in range(7) for v in values):
            raise ValueError("Study days use Monday=0 through Sunday=6.")
        return sorted(set(values))

    @model_validator(mode="after")
    def valid_window(self):
        if not 1 <= (self.assessment_date - self.start_date).days <= 366:
            raise ValueError("Start studying 1–366 days before the assessment.")
        if not (self.coverage or self.document_ids or self.assignment_ids):
            raise ValueError("Describe assessment coverage or select course materials.")
        return self


class PlanTopic(StrictModel):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    parent_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    prerequisite_ids: list[str] = Field(default_factory=list, max_length=10)
    source_ids: list[str] = Field(default_factory=list, max_length=30)
    importance: float = Field(default=0.5, ge=0, le=1)
    study_points: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(default_factory=list, max_length=5)


class SessionEdit(StrictModel):
    id: UUID
    scheduled_date: date | None = None
    completed: StrictBool | None = None

    @model_validator(mode="after")
    def has_change(self):
        if self.scheduled_date is None and self.completed is None:
            raise ValueError("Provide a date or completion state.")
        return self


class PlanUpdate(StrictModel):
    version: int = Field(ge=1, strict=True)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    topics: list[PlanTopic] | None = Field(default=None, min_length=1, max_length=60)
    session: SessionEdit | None = None
    regenerate: StrictBool = False
    settings: PlanCreate | None = None

    @model_validator(mode="after")
    def valid_update(self):
        if self.title is None and self.topics is None and self.session is None and self.settings is None and not self.regenerate:
            raise ValueError("Provide a change.")
        if self.session and (self.topics is not None or self.regenerate or self.settings is not None):
            raise ValueError("Edit sessions separately from rebuilding the schedule.")
        return self


def _today(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date()


def _nodes(user_id: str, course_id: str) -> list[dict]:
    return list(page_all(table("graph_nodes"),
        "id,concept_name,mastery_score,times_studied,last_studied_at", filters={
            "user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}",
            "mastery_tier": "neq.subject_root",
        }, order="id"))


def _progress(topics: list[dict], nodes: list[dict]) -> list[dict]:
    by_name = {normalized_name(n["concept_name"]): n for n in nodes}
    result = []
    for topic in topics:
        node = by_name.get(normalized_name(topic["name"]))
        score = float(node["mastery_score"]) if node and node.get("mastery_score") is not None else None
        studied = bool(node and node.get("times_studied", 0))
        status = ("mastered" if score is not None and in_mastered_tier(score) else
                  "needs_review" if studied and score is not None and is_weak(score) else
                  "in_progress" if studied else "not_started")
        result.append({**topic, "mastery_score": score, "status": status,
                       "checked": status == "mastered", "node_id": node["id"] if node else None})
    return result


def _validate_topics(topics: list[dict], source_ids: set[str]) -> None:
    by_id = {t["id"]: t for t in topics}
    if len(by_id) != len(topics) or len({normalized_name(t["name"]) for t in topics}) != len(topics):
        raise HTTPException(422, "Topics must have unique IDs and names.")
    for topic in topics:
        if not set(topic["source_ids"]) <= source_ids:
            raise HTTPException(422, "Topic evidence must belong to this plan.")
        refs = topic["prerequisite_ids"] + ([topic["parent_id"]] if topic["parent_id"] else [])
        if any(ref not in by_id or ref == topic["id"] for ref in refs):
            raise HTTPException(422, "Topic references must name other topics in the plan.")
    # Check parent and prerequisite DAGs independently; parents can legitimately
    # also be prerequisites for their subtopics.
    for field in ("parent_id", "prerequisite_ids"):
        complete = set()

        def visit(key, path):
            if key in path:
                raise HTTPException(422, "Topic relationships cannot contain cycles.")
            if key in complete:
                return
            value = by_id[key][field]
            for ref in ([value] if value else []) if field == "parent_id" else value:
                visit(ref, path | {key})
            complete.add(key)

        for key in by_id:
            visit(key, set())


def recommended_daily_minutes(content: dict, nodes: list[dict], today: date) -> int:
    """Estimate from topic workload and remaining days; never claim learning speed."""
    start = max(date.fromisoformat(content["start_date"]), today)
    end = date.fromisoformat(content["assessment_date"])
    days = sum((start + timedelta(days=i)).weekday() in content["study_days"]
               for i in range(max(0, (end - start).days)))
    completed = {(s["topic_id"], s["kind"]) for s in content.get("sessions", []) if s["completed"]}
    units = 0
    for topic in _progress(content["topics"], nodes):
        kinds = ["review"] if topic["checked"] else ["study", "review"]
        units += sum((topic["id"], kind) not in completed for kind in kinds)
    # 25-minute focus sessions, capped at two hours rather than inventing
    # unlimited availability. Coverage warnings expose unrealistic deadlines.
    return min(120, max(25, 25 * ((units + max(days, 1) - 1) // max(days, 1))))


def build_schedule(content: dict, nodes: list[dict], today: date) -> tuple[list[dict], list[str]]:
    """Respect availability/capacity; explicitly report any unscheduled work.

    Twenty-five minutes is a planning estimate, not a model's claim about the
    student's learning speed. Retain completed sessions during explicit replans.
    """
    start = max(date.fromisoformat(content["start_date"]), today)
    end = date.fromisoformat(content["assessment_date"])
    days = [start + timedelta(days=i) for i in range(max(0, (end - start).days))
            if (start + timedelta(days=i)).weekday() in content["study_days"]]
    sessions = [s for s in content.get("sessions", []) if s["completed"]]
    used = {d.isoformat(): sum(s["minutes"] for s in sessions if s["scheduled_date"] == d.isoformat()) for d in days}
    by_id = {t["id"]: t for t in _progress(content["topics"], nodes)}
    ordered, visited = [], set()

    def visit(topic):
        if topic["id"] in visited:
            return
        visited.add(topic["id"])
        for key in topic["prerequisite_ids"]:
            visit(by_id[key])
        ordered.append(topic)

    for topic in sorted(by_id.values(), key=lambda t: (t["checked"], t["status"] != "needs_review", -t["importance"], t["name"])):
        visit(topic)
    warnings = []
    duration = min(25, content["minutes_per_day"])
    first_days = {}
    completed = {(s["topic_id"], s["kind"]): date.fromisoformat(s["scheduled_date"]) for s in sessions}

    def place(topic, kind, candidates):
        if content.get("automatic_time"):
            candidates = sorted(candidates, key=lambda d: used[d.isoformat()])
        for day in candidates:
            key = day.isoformat()
            if used[key] + duration <= content["minutes_per_day"]:
                used[key] += duration
                sessions.append({"id": str(uuid4()), "topic_id": topic["id"], "kind": kind,
                                 "scheduled_date": key, "minutes": duration, "completed": False})
                return day
        return None

    # First coverage precedes optional repeat review. Mastered concepts need a
    # short review rather than another initial session.
    unscheduled = 0
    for topic in ordered:
        kind = "review" if topic["checked"] else "study"
        prerequisite_days = [first_days[p] for p in topic["prerequisite_ids"] if first_days.get(p)]
        earliest = max(prerequisite_days, default=start)
        first_days[topic["id"]] = completed.get((topic["id"], kind)) or place(topic, kind, [d for d in days if d >= earliest])
        if first_days[topic["id"]] is None:
            unscheduled += 1
    if unscheduled:
        warnings.append(f"{unscheduled} topics could not fit before the assessment. Increase availability or reduce coverage.")
    for topic in ordered:
        first = first_days[topic["id"]]
        if not topic["checked"] and first and (topic["id"], "review") not in completed:
            place(topic, "review", [d for d in reversed(days) if d >= first + timedelta(days=2)])
    sessions.sort(key=lambda s: (s["scheduled_date"], s["kind"] == "review"))
    return sessions, warnings


def _source_rows(user_id: str, scope: dict, data: PlanCreate) -> tuple[list[dict], list[dict]]:
    docs = table("documents").select("id,file_name,summary,extracted_text,concept_notes", filters={
        "user_id": f"eq.{user_id}", "offering_id": f"eq.{scope['offering_id']}",
        "deleted_at": "is.null", "id": f"in.({','.join(data.document_ids)})",
    }) if data.document_ids else []
    assignments = table("assignments").select("id,title,notes,due_date,assignment_type", filters={
        "enrollment_id": f"eq.{scope['enrollment_id']}", "id": f"in.({','.join(data.assignment_ids)})",
    }) if data.assignment_ids else []
    if {r["id"] for r in docs} != set(data.document_ids) or {r["id"] for r in assignments} != set(data.assignment_ids):
        raise HTTPException(404, "A selected source is unavailable in this course and semester.")
    return docs, assignments


def _evidence(data: PlanCreate, docs: list[dict], assignments: list[dict], scope: dict) -> tuple[dict, list[str]]:
    sources, warnings = [], []
    budget = 60000

    def add(key, label, text):
        nonlocal budget
        if not text.strip():
            return
        source = {"id": key, "label": label[:256], "text": text[:10000]}
        while source["text"] and len(json.dumps(source)) > budget:
            source["text"] = source["text"][:len(source["text"]) // 2]
        if source["text"]:
            sources.append(source)
            budget -= len(json.dumps(source))
        if source["text"] != text:
            warnings.append("Some selected material was shortened. Confirm the proposed topics cover your assessment.")

    add("assessment-coverage", "Your assessment coverage", data.coverage)
    for doc in docs:
        parts = []
        for key in ("summary", "concept_notes", "extracted_text"):
            value = doc.get(key)
            if isinstance(value, str):
                value = decrypt_if_present(value)
            if value:
                parts.append(value if isinstance(value, str) else json.dumps(value))
        add(f"document:{doc['id']}", doc["file_name"], "\n".join(parts))
    for assignment in assignments:
        add(f"assignment:{assignment['id']}", assignment["title"],
            assignment["title"] + "\n" + (decrypt_if_present(assignment.get("notes")) or ""))
    if not sources:
        raise HTTPException(422, "The selected materials contain no readable content. Describe assessment coverage.")
    return {"course": {"code": scope["course"]["course_code"], "name": scope["course"]["course_name"]},
            "sources": sources, "assessments": []}, list(dict.fromkeys(warnings))


def present(row: dict, nodes: list[dict]) -> dict:
    content = decrypt_json(row["content"])
    topics = _progress(content["topics"], nodes)
    return {**content, "topics": topics, "id": row["id"], "version": row["version"],
            "mastered_count": sum(t["checked"] for t in topics),
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def list_plans(user_id: str, course_id: str, semester: str | None = None) -> dict:
    scope = checklist.resolve_scope(user_id, course_id, semester)
    rows = list(page_all(table("assessment_study_plans"), "*", filters={
        "enrollment_id": f"eq.{scope['enrollment_id']}",
    }, order="created_at.desc,id"))
    nodes = _nodes(user_id, course_id) if rows else []
    return {"semester": scope["semester"], "plans": [present(row, nodes) for row in rows]}


def list_sources(user_id: str, course_id: str, semester: str | None = None) -> dict:
    scope = checklist.resolve_scope(user_id, course_id, semester)
    return {"documents": list(page_all(table("documents"), "id,file_name", filters={
        "user_id": f"eq.{user_id}", "offering_id": f"eq.{scope['offering_id']}", "deleted_at": "is.null",
    }, order="created_at.desc,id")), "assignments": list(page_all(table("assignments"),
        "id,title,due_date,assignment_type", filters={"enrollment_id": f"eq.{scope['enrollment_id']}"}, order="due_date,id"))}


def generate_topics(payload: dict, user_id: str, enrollment_id: str):
    """Use PR #728's durable spending controls without publishing a course outline.

    An assessment outline has narrower coverage than the course checklist. Settle
    the model receipt normally, but save its topics only in the assessment plan.
    """
    if model_mode() == "real":
        if not config.ANTHROPIC_API_KEY:
            raise HTTPException(503, "Study guide generation requires an Anthropic API key on the backend. You can run the local no-key smoke test while that key is unavailable." if config.IS_LOCAL else "Study guide generation is temporarily unavailable. Please try again later.")
        if model_name_for("assessment_guide") != "claude-haiku-5-5":
            raise HTTPException(503, "The configured study guide model needs an approved usage policy.")
    # The existing .07644 hold exceeds Haiku's .017288 maximum for this envelope.
    from services.llm_pricing import cost_usd
    maximum_cost = cost_usd("claude-haiku-5-5", 50000, 3 * 8192)
    if not isinstance(maximum_cost, (int, float)) or not math.isfinite(maximum_cost) or not 0 < maximum_cost <= float(checklist_budget.HOLD_USD):
        raise HTTPException(503, "Study guide usage policy needs an update.")
    digest = hashlib.sha256(json.dumps({"purpose": "assessment-plan", "operation": str(uuid4()),
                                       "payload": payload}, sort_keys=True).encode()).hexdigest()
    with checklist._generation_slot(user_id):
        try:
            reservation = checklist_budget.admit(user_id, enrollment_id, digest)
        except HTTPException as error:
            if error.status_code == 409:
                raise HTTPException(409, "An earlier study guide request is still in progress or awaiting confirmation. Wait two minutes before trying again. Your assessment details have been kept.", headers=error.headers) from None
            raise
        if reservation is None:
            raise HTTPException(409, "Please retry creating this assessment plan.")
        try:
            try:
                decision = ai_budget.check(user_id, "generation")
            except ai_budget.AIBudgetUnavailable:
                raise HTTPException(503, "AI usage is temporarily unavailable. Please try again.") from None
            if decision.level == "hard":
                raise ai_budget.AIBudgetExceeded(decision)
        except BaseException:
            checklist_budget.reconcile(reservation, no_dispatch=True)
            raise
        generation = run_agent_sync(checklist._generate(payload, user_id, reservation, agent=assessment_guide_agent, approved_model="claude-haiku-5-5"))
        checklist._finish_generation(generation, payload, publish=False)
        return generation.outline


def create_plan(user_id: str, course_id: str, data: PlanCreate, semester: str | None = None) -> dict:
    scope = checklist.resolve_scope(user_id, course_id, semester)
    today = _today(data.timezone)
    if data.start_date < today:
        raise HTTPException(422, "The study start date cannot be in the past.")
    retry = check_rate_limit(f"study-plan:{user_id}", limit=6, window_sec=60)
    if retry is not None:
        raise HTTPException(429, "Please wait before generating another plan.", headers={"Retry-After": str(retry)})
    docs, assignments = _source_rows(user_id, scope, data)
    payload, warnings = _evidence(data, docs, assignments, scope)
    nodes = _nodes(user_id, course_id)
    try:
        outline = generate_topics({**payload, "existing_topic_names": [n["concept_name"] for n in nodes][:200]},
                                  user_id, scope["enrollment_id"])
        checklist.validate_evidence(outline, payload)
    except (HTTPException, ai_budget.AIBudgetExceeded):
        raise
    except Exception:
        logger.exception("Study plan extraction failed")
        raise HTTPException(503, "Could not generate topics. Please try again.") from None
    if not outline.topics:
        raise HTTPException(422, "No academic topics were found. Add more specific coverage or materials.")
    topics = [{"id": checklist.topic_key(t.name), "name": t.name, "description": t.description,
               "parent_id": checklist.topic_key(t.parent) if t.parent else None,
               "prerequisite_ids": [checklist.topic_key(p) for p in t.prerequisites],
               "source_ids": t.source_ids, "importance": t.importance,
               "study_points": getattr(t, "study_points", [])} for t in outline.topics]
    content = {**data.model_dump(mode="json"), "topics": topics,
               "guide_overview": getattr(outline, "overview", ""),
               "sources": [{"id": s["id"], "label": s["label"]} for s in payload["sources"]],
               "source_warnings": warnings, "automatic_time": data.minutes_per_day is None}
    if content["automatic_time"]:
        content["minutes_per_day"] = recommended_daily_minutes(content, nodes, today)
    content["sessions"], scheduling_warnings = build_schedule(content, nodes, today)
    content["warnings"] = warnings + scheduling_warnings
    now = datetime.now(timezone.utc).isoformat()
    row = {"id": str(uuid4()), "enrollment_id": scope["enrollment_id"], "version": 1,
           "content": encrypt_json(content), "created_at": now, "updated_at": now}
    table("assessment_study_plans").insert(row)
    return present(row, nodes)


def update_plan(user_id: str, course_id: str, plan_id: UUID, data: PlanUpdate, semester: str | None = None) -> dict:
    scope = checklist.resolve_scope(user_id, course_id, semester)
    filters = {"id": f"eq.{plan_id}", "enrollment_id": f"eq.{scope['enrollment_id']}"}
    rows = table("assessment_study_plans").select("*", filters=filters, limit=1)
    if not rows:
        raise HTTPException(404, "Study plan not found.")
    row = rows[0]
    if row["version"] != data.version:
        raise HTTPException(409, "This plan changed. Reload before editing it.")
    content = decrypt_json(row["content"])
    nodes = _nodes(user_id, course_id)
    if data.settings is not None:
        settings = data.settings.model_dump(mode="json")
        # Timing edits cannot silently claim coverage of new evidence.
        if any(settings[k] != content[k] for k in ("coverage", "document_ids", "assignment_ids")):
            raise HTTPException(422, "Create a new assessment plan to change source coverage.")
        if data.settings.assessment_date <= _today(data.settings.timezone):
            raise HTTPException(422, "Choose an assessment date after today.")
        content.update(settings)
        content["automatic_time"] = data.settings.minutes_per_day is None
    if data.title is not None:
        content["title"] = data.title
    if data.topics is not None:
        topics = [t.model_dump() for t in data.topics]
        _validate_topics(topics, {s["id"] for s in content["sources"]})
        content["topics"] = topics
        valid = {t["id"] for t in topics}
        content["sessions"] = [s for s in content["sessions"] if s["topic_id"] in valid]
    if data.session:
        session = next((s for s in content["sessions"] if s["id"] == str(data.session.id)), None)
        if session is None:
            raise HTTPException(404, "Study session not found.")
        if data.session.scheduled_date is not None:
            target = data.session.scheduled_date
            if not max(_today(content["timezone"]), date.fromisoformat(content["start_date"])) <= target < date.fromisoformat(content["assessment_date"]):
                raise HTTPException(422, "Schedule sessions between today/start date and the day before the assessment.")
            if target.weekday() not in content["study_days"]:
                raise HTTPException(422, "Choose one of your available study days.")
            used = sum(s["minutes"] for s in content["sessions"] if s["id"] != session["id"] and s["scheduled_date"] == target.isoformat())
            if used + session["minutes"] > content["minutes_per_day"]:
                raise HTTPException(422, "That day exceeds your study time budget.")
            session["scheduled_date"] = target.isoformat()
        if data.session.completed is not None:
            session["completed"] = data.session.completed
    if data.regenerate or data.topics is not None or data.settings is not None:
        if content.get("automatic_time"):
            content["minutes_per_day"] = recommended_daily_minutes(content, nodes, _today(content["timezone"]))
        content["sessions"], warnings = build_schedule(content, nodes, _today(content["timezone"]))
        content["warnings"] = content["source_warnings"] + warnings
    content["sessions"].sort(key=lambda s: (s["scheduled_date"], s["kind"] == "review"))
    changes = {"content": encrypt_json(content), "version": row["version"] + 1,
               "updated_at": datetime.now(timezone.utc).isoformat()}
    saved = table("assessment_study_plans").update(changes, filters={**filters, "version": f"eq.{data.version}"})
    if not saved:
        raise HTTPException(409, "This plan changed. Reload before editing it.")
    return present(saved[0], nodes)


def delete_plan(user_id: str, course_id: str, plan_id: UUID, semester: str | None = None) -> dict:
    scope = checklist.resolve_scope(user_id, course_id, semester)
    rows = table("assessment_study_plans").delete({"id": f"eq.{plan_id}", "enrollment_id": f"eq.{scope['enrollment_id']}"})
    if not rows:
        raise HTTPException(404, "Study plan not found.")
    return {"deleted": True}
