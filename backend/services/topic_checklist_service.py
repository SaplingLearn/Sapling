"""Enrollment-scoped outlines with live, deterministic study/review priorities."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException

from agents import WORKER_LIMITS
from agents._run import run_agent_sync
from agents.topic_checklist import PROMPT_VERSION, TopicOutline, normalized_name, topic_checklist_agent
from agents.usage import record_agent_usage
from db.connection import page_all, table
from services.academics import current_term, term_id_for_label
from services.encryption import decrypt_if_present, decrypt_json, encrypt_json
from services.request_limits import check_rate_limit

logger = logging.getLogger(__name__)
REVIEW_AFTER_DAYS = 7
ASSESSMENT_WINDOW_DAYS = 30
MAX_DOCUMENTS = 30
MAX_ASSESSMENTS = 50
MAX_SOURCE_CHARS = 60000


def topic_key(name: str) -> str:
    return hashlib.sha256(normalized_name(name).encode()).hexdigest()[:32]


def resolve_scope(user_id: str, course_id: str, semester: str | None) -> dict:
    """Resolve only an owned enrollment, never fall back across an explicit term."""
    term_id = term_id_for_label(semester) if semester else None
    if semester and not term_id:
        raise HTTPException(404, "Semester not found.")
    courses = table("courses").select("id,course_code,course_name,description", filters={
        "id": f"eq.{course_id}", "deleted_at": "is.null",
    }, limit=1)
    if not courses:
        raise HTTPException(404, "Course not found.")
    offerings = list(page_all(table("course_offerings"), "id,term_id", filters={
        "course_id": f"eq.{course_id}", **({"term_id": f"eq.{term_id}"} if term_id else {}),
    }, order="created_at.desc,id"))
    owned = list(page_all(table("enrollments"), "id,offering_id", filters={
        "user_id": f"eq.{user_id}",
    }, order="id"))
    by_offering = {r["offering_id"]: r for r in owned}
    candidates = [o for o in offerings if o["id"] in by_offering]
    if not candidates:
        raise HTTPException(404, "You are not enrolled in this course and semester.")
    term_ids = sorted({o["term_id"] for o in candidates})
    terms = list(page_all(table("terms"), "id,label,sort_key", filters={
        "id": f"in.({','.join(term_ids)})",
    }, order="id"))
    by_term = {t["id"]: t for t in terms}
    current = current_term() if not semester else None
    latest = max(candidates, key=lambda o: by_term.get(o["term_id"], {}).get("sort_key", 0))
    chosen = next((o for o in candidates if current and o["term_id"] == current["id"]), latest)
    return {
        "course": courses[0], "enrollment_id": by_offering[chosen["id"]]["id"],
        "offering_id": chosen["id"], "semester": by_term.get(chosen["term_id"], {}).get("label", ""),
    }


def build_snapshot(user_id: str, scope: dict, today: date) -> dict:
    """Bound prompt size; never read another student's uploaded material."""
    course = scope["course"]
    sources = []
    budget = MAX_SOURCE_CHARS
    truncated = False

    def add_source(source_id: str, label: str, text: str | None):
        nonlocal budget, truncated
        text = (text or "").strip()
        if not text:
            return
        # Account for IDs/labels and JSON escaping too: thousands of tiny
        # concept names must not evade the evidence-size ceiling.
        if len(label) > 256:
            truncated = True
            label = label[:256]
        overhead = len(json.dumps({"id": source_id, "label": label, "text": ""}))
        allowed = min(10000, max(0, budget - overhead))
        if len(text) > allowed:
            truncated = True
        if allowed:
            # Ensure escaped Unicode cannot expand beyond the remaining budget.
            while allowed and len(json.dumps(text[:allowed])) - 2 > budget - overhead:
                allowed //= 2
                truncated = True
            if allowed:
                source = {"id": source_id, "label": label, "text": text[:allowed]}
                sources.append(source)
                budget -= len(json.dumps(source))

    add_source("course-description", "BU course description", course.get("description"))
    # Catalog RAG uses BU codes, while graph/course rows use abstract IDs.
    catalogs = table("course_chunks").select("id,chunk_text", filters={
        "course_id": f"eq.{course['course_code']}", "category": "eq.catalog",
    }, order="created_at.desc,id", limit=5)
    for row in catalogs:
        add_source(f"catalog:{row['id']}", "BU catalog", decrypt_if_present(row.get("chunk_text")))

    docs, doc_count = table("documents").select_with_count(
        "id,file_name,summary,extracted_text,concept_notes", filters={
            "user_id": f"eq.{user_id}", "offering_id": f"eq.{scope['offering_id']}",
            "deleted_at": "is.null",
        }, order="created_at.desc,id", limit=MAX_DOCUMENTS,
    )
    for row in docs:
        # Include concept notes even on older uploads without stored full text.
        text = "\n".join(filter(None, [
            decrypt_if_present(row.get("summary")),
            decrypt_if_present(row.get("concept_notes")),
            decrypt_if_present(row.get("extracted_text")),
        ]))
        add_source(f"document:{row['id']}", row["file_name"], text)

    assessments, assessment_count = table("assignments").select_with_count("id,title,due_date,assignment_type,notes", filters={
        "enrollment_id": f"eq.{scope['enrollment_id']}",
        "assignment_type": "in.(exam,quiz)", "due_date": f"gte.{today.isoformat()}",
        "and": f"(due_date.lte.{(today + timedelta(days=ASSESSMENT_WINDOW_DAYS)).isoformat()})",
    }, order="due_date,id", limit=MAX_ASSESSMENTS)
    for row in assessments:
        if len(row["title"]) > 256:
            truncated = True
            row["title"] = row["title"][:256]
        row["notes"] = decrypt_if_present(row.get("notes")) or ""
        add_source(f"assessment:{row['id']}", row["title"], f"{row['title']}\n{row['notes']}")

    # Tracked graph concepts are evidence for material already processed; scores
    # are excluded from the prompt/hash because they change independently.
    nodes = list(page_all(table("graph_nodes"), "id,concept_name,mastery_score,times_studied,last_studied_at", filters={
        "user_id": f"eq.{user_id}", "course_id": f"eq.{course['id']}",
        "mastery_tier": "neq.subject_root",
    }, order="id"))
    for node in nodes:
        add_source(f"concept:{node['id']}", "Tracked course concept", node["concept_name"])
    node_names = {n["id"]: n["concept_name"] for n in nodes}
    relationships = page_all(table("graph_edges"), "id,source_node_id,target_node_id,relationship_type", filters={
        "user_id": f"eq.{user_id}", "relationship_type": "in.(prerequisite,builds_on)",
    }, order="id")
    for edge in relationships:
        source = node_names.get(edge["source_node_id"])
        target = node_names.get(edge["target_node_id"])
        if source and target:
            text = f"{source} is a prerequisite for {target}." if edge["relationship_type"] == "prerequisite" else f"{target} builds on {source}."
            add_source(f"relationship:{edge['id']}", "Tracked course relationship", text)
    payload = {
        "course": {"code": course["course_code"], "name": course["course_name"]},
        "sources": sources,
        "assessments": [{k: r[k] for k in ("id", "title", "due_date", "assignment_type")} for r in assessments],
    }
    digest = hashlib.sha256(json.dumps({"version": PROMPT_VERSION, **payload}, sort_keys=True).encode()).hexdigest()
    return {"payload": payload, "hash": digest, "nodes": nodes,
            "truncated": truncated or doc_count > MAX_DOCUMENTS or assessment_count > MAX_ASSESSMENTS}


def _cache(scope: dict) -> dict | None:
    rows = table("topic_checklists").select("*", filters={
        "enrollment_id": f"eq.{scope['enrollment_id']}",
    }, limit=1)
    return rows[0] if rows else None


def validate_evidence(outline: TopicOutline, payload: dict) -> None:
    sources = {s["id"] for s in payload["sources"]}
    assessments = {a["id"] for a in payload["assessments"]}
    for topic in outline.topics:
        if not set(topic.source_ids) <= sources or not set(topic.assessment_ids) <= assessments:
            raise ValueError("The generated outline references evidence outside this course.")


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp


def present(scope: dict, snapshot: dict, cache: dict | None, now: datetime) -> dict:
    outline = TopicOutline.model_validate(decrypt_json(cache["content"])) if cache and snapshot["payload"]["sources"] else None
    progress = list(page_all(table("topic_checklist_progress"), "topic_key,reviewed_at", filters={
        "enrollment_id": f"eq.{scope['enrollment_id']}",
    }, order="topic_key")) if cache else []
    reviewed = {r["topic_key"]: r["reviewed_at"] for r in progress}
    nodes = {normalized_name(n["concept_name"]): n for n in snapshot["nodes"]}
    assessments = {a["id"]: a for a in snapshot["payload"]["assessments"]}
    source_labels = {s["id"]: s["label"] for s in snapshot["payload"]["sources"]}
    topics = []
    for topic in outline.topics if outline else []:
        key = topic_key(topic.name)
        node = nodes.get(normalized_name(topic.name))
        score = float(node["mastery_score"]) if node else None
        studied = key in reviewed or bool(node and node["times_studied"] > 0)
        timestamps = [_parse_timestamp(reviewed.get(key)), _parse_timestamp(node.get("last_studied_at")) if node else None]
        last = max((t for t in timestamps if t), default=None)
        weak = studied and score is not None and score < 0.45
        stale = studied and (last is None or now - last >= timedelta(days=REVIEW_AFTER_DAYS))
        status = "not_started" if not studied else "needs_review" if weak or stale else "mastered" if score is not None and score >= 0.75 else "in_progress"
        linked = [assessments[a] for a in topic.assessment_ids if a in assessments]
        linked.sort(key=lambda a: (a["due_date"], a["id"]))
        urgent = bool(linked and date.fromisoformat(linked[0]["due_date"]) <= now.date() + timedelta(days=7))
        prereq_gaps = [p for p in topic.prerequisites if (
            normalized_name(p) not in nodes or float(nodes[normalized_name(p)]["mastery_score"]) < 0.45
        )]
        topics.append({
            **topic.model_dump(exclude={"source_ids", "assessment_ids", "parent", "prerequisites"}),
            "id": key, "parent_id": topic_key(topic.parent) if topic.parent else None,
            "prerequisite_ids": [topic_key(p) for p in topic.prerequisites],
            "prerequisite_gaps": prereq_gaps, "status": status, "checked": key in reviewed,
            "mastery_score": score, "last_studied_at": last.isoformat() if last else None,
            "review_reasons": (["Weak mastery"] if weak else []) + (["Review overdue"] if stale else []),
            "priority": "high" if urgent and status != "mastered" or weak or prereq_gaps else "normal",
            "assessments": linked,
            "sources": [{"id": s, "label": source_labels[s]} for s in topic.source_ids if s in source_labels],
            "node_id": node["id"] if node else None,
        })
    topics.sort(key=lambda t: (t["priority"] != "high", min((a["due_date"] for a in t["assessments"]), default="9999"), -t["importance"], t["name"]))
    return {
        "course_id": scope["course"]["id"], "semester": scope["semester"],
        "generated_at": cache["generated_at"] if cache else None,
        "needs_refresh": bool(snapshot["payload"]["sources"]) and (cache is None or cache["input_hash"] != snapshot["hash"]),
        "topics": topics, "assessments": list(assessments.values()),
        "warnings": (["Some source text or source coverage was limited; the outline may not cover every detail."] if snapshot["truncated"] else [])
            + (["No course evidence is available yet. Upload course materials to generate a checklist."] if not snapshot["payload"]["sources"] else [])
            + (["The available sources do not describe academic topics. Upload a syllabus or study materials."] if outline is not None and not outline.topics else []),
        "review_after_days": REVIEW_AFTER_DAYS,
    }


def get_checklist(user_id: str, course_id: str, semester: str | None = None) -> dict:
    now = datetime.now(timezone.utc)
    scope = resolve_scope(user_id, course_id, semester)
    return present(scope, build_snapshot(user_id, scope, now.date()), _cache(scope), now)


async def _generate(payload: dict, user_id: str) -> TopicOutline:
    result = await asyncio.wait_for(topic_checklist_agent.run(
        json.dumps(payload), deps=payload, usage_limits=WORKER_LIMITS,
    ), timeout=60)
    # Attribute the usage row to the student explicitly: the per-user cost
    # rollups and the $ai_generation mirror both key on it.
    return record_agent_usage(
        result, feature="topic_checklist", task="topic_checklist", user_id=user_id,
    ).output


def refresh_checklist(user_id: str, course_id: str, semester: str | None = None) -> dict:
    now = datetime.now(timezone.utc)
    scope = resolve_scope(user_id, course_id, semester)
    snapshot = build_snapshot(user_id, scope, now.date())
    cache = _cache(scope)
    if not snapshot["payload"]["sources"] or cache and cache["input_hash"] == snapshot["hash"]:
        return present(scope, snapshot, cache, now)
    retry = check_rate_limit(f"topic-checklist:{user_id}", limit=6, window_sec=60)
    if retry is not None:
        raise HTTPException(429, "Please wait before generating another checklist.", headers={"Retry-After": str(retry)})
    try:
        prior = TopicOutline.model_validate(decrypt_json(cache["content"])) if cache else None
        outline = run_agent_sync(_generate({**snapshot["payload"],
            "existing_topic_names": [t.name for t in prior.topics] if prior else [],
        }, user_id))
        validate_evidence(outline, snapshot["payload"])
    except Exception:
        logger.exception("Topic checklist generation failed")
        raise HTTPException(503, "Topic generation is temporarily unavailable. Please try again.") from None
    cache = {
        "enrollment_id": scope["enrollment_id"], "input_hash": snapshot["hash"],
        "content": encrypt_json(outline.model_dump()), "generated_at": now.isoformat(),
    }
    table("topic_checklists").upsert(cache, on_conflict="enrollment_id")
    return present(scope, snapshot, cache, now)


def set_reviewed(user_id: str, course_id: str, key: str, checked: bool, semester: str | None = None) -> dict:
    now = datetime.now(timezone.utc)
    scope = resolve_scope(user_id, course_id, semester)
    cache = _cache(scope)
    if not cache or key not in {topic_key(t.name) for t in TopicOutline.model_validate(decrypt_json(cache["content"])).topics}:
        raise HTTPException(404, "Topic not found in this checklist.")
    filters = {"enrollment_id": f"eq.{scope['enrollment_id']}", "topic_key": f"eq.{key}"}
    if checked:
        table("topic_checklist_progress").upsert({
            "enrollment_id": scope["enrollment_id"], "topic_key": key, "reviewed_at": now.isoformat(),
        }, on_conflict="enrollment_id,topic_key")
    else:
        table("topic_checklist_progress").delete(filters)
    return present(scope, build_snapshot(user_id, scope, now.date()), cache, now)
