"""Enrollment-scoped outlines with live, deterministic study/review priorities."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from pydantic_ai.usage import RunUsage

from agents._run import run_agent_sync
from agents.topic_checklist import (
    CHECKLIST_LIMITS, PROMPT_VERSION, TopicOutline, normalized_name, topic_checklist_agent,
)
from db.connection import page_all, table
from learning.bkt import in_mastered_tier, is_weak
from services.academics import (
    current_term,
    term_for_offering,
    term_id_for_label,
    user_enrollment_ids,
    user_offering_ids_for_course,
)
from services.encryption import decrypt_if_present, decrypt_json, encrypt_json
from services.request_limits import check_rate_limit
from services import ai_budget, checklist_budget
from services.checklist_budget_run import ChecklistDispatches
from services.request_context import current_request_id
from services.usage_receipts import UsageReceiptUnavailable, prepare_checklist_usage_receipt

logger = logging.getLogger(__name__)
REVIEW_AFTER_DAYS = 7
ASSESSMENT_WINDOW_DAYS = 30
MAX_DOCUMENTS = 30
MAX_ASSESSMENTS = 50
MAX_SOURCE_CHARS = 60000
EDGE_READ_BATCH = 100
GENERATION_WAIT_SECONDS = 5.0
# All counter/generation/validation attempts share this deadline. Cancellation
# is cooperative and does not prove that remote provider work stopped billing.
GENERATION_TIMEOUT_SECONDS = 60.0

# Serialize only paid cache misses for one student within this process, across
# enrollments too. Reference counts retain a lock for waiters and release idle
# entries, so the registry does not grow with every student who ever refreshes.
_generation_guard = threading.Lock()
_generation_locks: dict[str, tuple[threading.Lock, int]] = {}


@contextmanager
def _generation_slot(user_id: str):
    with _generation_guard:
        lock, waiters = _generation_locks.get(user_id, (threading.Lock(), 0))
        _generation_locks[user_id] = (lock, waiters + 1)
    acquired = False
    try:
        acquired = lock.acquire(timeout=GENERATION_WAIT_SECONDS)
        if not acquired:
            raise HTTPException(503, "A checklist is already generating. Please try again.", headers={"Retry-After": "2"})
        yield
    finally:
        if acquired:
            lock.release()
        with _generation_guard:
            _, waiters = _generation_locks[user_id]
            if waiters == 1:
                del _generation_locks[user_id]
            else:
                _generation_locks[user_id] = (lock, waiters - 1)


def topic_key(name: str) -> str:
    return hashlib.sha256(normalized_name(name).encode()).hexdigest()[:32]


def resolve_scope(user_id: str, course_id: str, semester: str | None) -> dict:
    """Resolve only an owned enrollment, never fall back across an explicit term.

    Term/offering/enrollment reads go through services/academics.py. Without an
    explicit semester: the current term's enrollment, else the most recent term
    (by term order, not creation time) the student is enrolled in.
    """
    term_id = term_id_for_label(semester) if semester else None
    if semester and not term_id:
        raise HTTPException(404, "Semester not found.")
    courses = table("courses").select("id,course_code,course_name,description", filters={
        "id": f"eq.{course_id}", "deleted_at": "is.null",
    }, limit=1)
    if not courses:
        raise HTTPException(404, "Course not found.")
    offering_ids = sorted(set(user_offering_ids_for_course(user_id, course_id)))
    terms = {oid: term_for_offering(oid) or {} for oid in offering_ids}
    candidates = [oid for oid in offering_ids if not term_id or terms[oid].get("id") == term_id]
    if not candidates:
        raise HTTPException(404, "You are not enrolled in this course and semester.")
    current = current_term() if not semester else None
    chosen = next((oid for oid in candidates if current and terms[oid].get("id") == current["id"]), None)
    if chosen is None:
        chosen = max(candidates, key=lambda oid: terms[oid].get("sort_key") or 0)
    enrollment_id = next((r["id"] for r in user_enrollment_ids(user_id) if r.get("offering_id") == chosen), None)
    if not enrollment_id:
        raise HTTPException(404, "You are not enrolled in this course and semester.")
    return {
        "course": courses[0], "enrollment_id": enrollment_id,
        "offering_id": chosen, "semester": terms[chosen].get("label", ""),
    }


def _tracked_graph(user_id: str, course_id: str) -> tuple[list[dict], list[tuple[str, str]]]:
    """The student's tracked concepts for this course and the prerequisite
    relationships BETWEEN them, as (edge id, sentence) pairs in id order.

    Edges carry no course column, so they are read by this course's node ids
    (batched to keep each ``in.(...)`` filter short) rather than paging every
    edge the student owns across all courses.
    """
    nodes = list(page_all(table("graph_nodes"), "id,concept_name,mastery_score,times_studied,last_studied_at", filters={
        "user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}",
        "mastery_tier": "neq.subject_root",
    }, order="id"))
    node_names = {n["id"]: n["concept_name"] for n in nodes}
    ids = sorted(node_names)
    edges: list[dict] = []
    for start in range(0, len(ids), EDGE_READ_BATCH):
        edges.extend(page_all(table("graph_edges"), "id,source_node_id,target_node_id,relationship_type", filters={
            "user_id": f"eq.{user_id}", "relationship_type": "in.(prerequisite,builds_on)",
            "source_node_id": f"in.({','.join(ids[start:start + EDGE_READ_BATCH])})",
        }, order="id"))
    relationships = []
    for edge in sorted(edges, key=lambda e: e["id"]):
        source = node_names.get(edge["source_node_id"])
        target = node_names.get(edge["target_node_id"])
        if source and target:
            text = f"{source} is a prerequisite for {target}." if edge["relationship_type"] == "prerequisite" else f"{target} builds on {source}."
            relationships.append((edge["id"], text))
    return nodes, relationships


def _assessments(scope: dict, columns: str) -> tuple[list[dict], int]:
    """Every exam/quiz of the enrollment, independent of today's date.

    The evidence (and so its hash) must not move as days pass; the upcoming
    window is applied only when presenting (see present()). Keeps the latest
    MAX_ASSESSMENTS, returned in due-date order.
    """
    rows, count = table("assignments").select_with_count(columns, filters={
        "enrollment_id": f"eq.{scope['enrollment_id']}",
        "assignment_type": "in.(exam,quiz)", "due_date": "not.is.null",
    }, order="due_date.desc,id", limit=MAX_ASSESSMENTS)
    rows = [r for r in rows if r.get("due_date")]
    rows.sort(key=lambda r: (r["due_date"], r["id"]))
    return rows, count


def build_snapshot(user_id: str, scope: dict, today: date | None = None, *, evidence: bool = True) -> dict:
    """Bound prompt size; never read another student's uploaded material.

    ``evidence=False`` is the cheap live view a checkmark needs: source ids and
    labels, assessments and tracked nodes, without reading or decrypting any
    source text, and without a hash (a checkmark never changes evidence).
    ``today`` is accepted for call-site compatibility only — the evidence is
    deliberately independent of the date.
    """
    course = scope["course"]
    sources = []
    budget = MAX_SOURCE_CHARS
    truncated = False

    def add_source(source_id: str, label: str, text: str | None):
        nonlocal budget, truncated
        if len(label) > 256:
            truncated = True
            label = label[:256]
        if not evidence:
            sources.append({"id": source_id, "label": label})
            return
        text = (text or "").strip()
        if not text:
            return
        # Account for IDs/labels and JSON escaping too: thousands of tiny
        # concept names must not evade the evidence-size ceiling.
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
    catalogs = table("course_chunks").select("id,chunk_text" if evidence else "id", filters={
        "course_id": f"eq.{course['course_code']}", "category": "eq.catalog",
    }, order="created_at.desc,id", limit=5)
    for row in catalogs:
        add_source(f"catalog:{row['id']}", "BU catalog", decrypt_if_present(row.get("chunk_text")) if evidence else None)

    docs, doc_count = table("documents").select_with_count(
        "id,file_name,summary,extracted_text,concept_notes" if evidence else "id,file_name", filters={
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
        ])) if evidence else None
        add_source(f"document:{row['id']}", row["file_name"], text)

    assessments, assessment_count = _assessments(
        scope, "id,title,due_date,assignment_type,notes" if evidence else "id,title,due_date,assignment_type",
    )
    for row in assessments:
        if len(row["title"]) > 256:
            truncated = True
            row["title"] = row["title"][:256]
        notes = (decrypt_if_present(row.pop("notes", None)) or "") if evidence else ""
        add_source(f"assessment:{row['id']}", row["title"], f"{row['title']}\n{notes}")

    # Tracked graph concepts are evidence for material already processed; scores
    # are excluded from the prompt/hash because they change independently.
    nodes, relationships = _tracked_graph(user_id, course["id"])
    for node in nodes:
        add_source(f"concept:{node['id']}", "Tracked course concept", node["concept_name"])
    for edge_id, text in relationships:
        add_source(f"relationship:{edge_id}", "Tracked course relationship", text)
    payload = {
        "course": {"code": course["course_code"], "name": course["course_name"]},
        "sources": sources,
        "assessments": [{k: r[k] for k in ("id", "title", "due_date", "assignment_type")} for r in assessments],
    }
    if not evidence:
        return {"payload": payload, "nodes": nodes}
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
    """The checklist as served. Freshness (``needs_refresh``/``warnings``) is
    reported only for a full evidence snapshot; a live snapshot (a checkmark)
    leaves those to the client's last GET/refresh."""
    outline = TopicOutline.model_validate(decrypt_json(cache["content"])) if cache and snapshot["payload"]["sources"] else None
    progress = list(page_all(table("topic_checklist_progress"), "topic_key,reviewed_at", filters={
        "enrollment_id": f"eq.{scope['enrollment_id']}",
    }, order="topic_key")) if cache else []
    reviewed = {r["topic_key"]: r["reviewed_at"] for r in progress}
    nodes = {normalized_name(n["concept_name"]): n for n in snapshot["nodes"]}
    # The upcoming window is a presentation concern only (never in the hash).
    window_end = (now.date() + timedelta(days=ASSESSMENT_WINDOW_DAYS)).isoformat()
    assessments = {a["id"]: a for a in snapshot["payload"]["assessments"]
                   if now.date().isoformat() <= a["due_date"][:10] <= window_end}
    source_labels = {s["id"]: s["label"] for s in snapshot["payload"]["sources"]}
    topics = []
    for topic in outline.topics if outline else []:
        key = topic_key(topic.name)
        node = nodes.get(normalized_name(topic.name))
        score = float(node["mastery_score"]) if node else None
        studied = key in reviewed or bool(node and node["times_studied"] > 0)
        timestamps = [_parse_timestamp(reviewed.get(key)), _parse_timestamp(node.get("last_studied_at")) if node else None]
        last = max((t for t in timestamps if t), default=None)
        weak = studied and score is not None and is_weak(score)
        stale = studied and (last is None or now - last >= timedelta(days=REVIEW_AFTER_DAYS))
        # Match the graph's presentation tier, not strict learning mastery
        # (which also requires strong unassisted evidence). Checkmarks only
        # record study/review dates and never supply mastery evidence.
        status = "not_started" if not studied else "needs_review" if weak or stale else "mastered" if score is not None and in_mastered_tier(score) else "in_progress"
        linked = [assessments[a] for a in topic.assessment_ids if a in assessments]
        linked.sort(key=lambda a: (a["due_date"], a["id"]))
        urgent = bool(linked and date.fromisoformat(linked[0]["due_date"]) <= now.date() + timedelta(days=7))
        # A gap is a KNOWN weakness: a prerequisite that is a tracked node with
        # weak mastery and that the student has not checked off. Untracked is
        # unknown, not a gap.
        prereq_gaps = [p for p in topic.prerequisites if (
            topic_key(p) not in reviewed and normalized_name(p) in nodes
            and is_weak(float(nodes[normalized_name(p)]["mastery_score"]))
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
    result = {
        "course_id": scope["course"]["id"], "semester": scope["semester"],
        "generated_at": cache["generated_at"] if cache else None,
        "topics": topics, "assessments": list(assessments.values()),
        "review_after_days": REVIEW_AFTER_DAYS,
    }
    if "hash" not in snapshot:
        return result
    result["needs_refresh"] = bool(snapshot["payload"]["sources"]) and (cache is None or cache["input_hash"] != snapshot["hash"])
    result["warnings"] = (
        (["Some source text or source coverage was limited; the outline may not cover every detail."] if snapshot["truncated"] else [])
        + (["No course evidence is available yet. Upload course materials to generate a checklist."] if not snapshot["payload"]["sources"] else [])
        + (["The available sources do not describe academic topics. Upload a syllabus or study materials."] if outline is not None and not outline.topics else [])
    )
    return result


def get_checklist(user_id: str, course_id: str, semester: str | None = None) -> dict:
    now = datetime.now(timezone.utc)
    scope = resolve_scope(user_id, course_id, semester)
    return present(scope, build_snapshot(user_id, scope, now.date()), _cache(scope), now)


@dataclass
class ChecklistGeneration:
    usage: RunUsage
    dispatches: ChecklistDispatches
    outline: TopicOutline | None = None
    error: BaseException | None = None


async def _generate(payload: dict, user_id: str, reservation: checklist_budget.Reservation, *, agent=None) -> ChecklistGeneration:
    usage = RunUsage()
    dispatches = ChecklistDispatches(reservation=reservation)
    try:
        result = await asyncio.wait_for((agent or topic_checklist_agent).run(
            json.dumps(payload), deps=payload, usage=usage, usage_limits=CHECKLIST_LIMITS,
            capabilities=[dispatches],
        ), timeout=GENERATION_TIMEOUT_SECONDS)
        return ChecklistGeneration(usage, dispatches, result.output)
    except BaseException as error:
        # A response may be billed even when output validation fails. Preserve
        # actual responses and an independent count of handlers entered. Never
        # queue a duplicate analytics bill alongside the durable receipt.
        return ChecklistGeneration(usage, dispatches, error=error)


def _finish_generation(generation: ChecklistGeneration, payload: dict, *, publish: bool = True) -> None:
    tracker = generation.dispatches
    content = None
    if generation.error is None:
        try:
            validate_evidence(generation.outline, payload)
            if publish:
                content = encrypt_json(generation.outline.model_dump())
        except Exception as error:
            generation.error = error
    receipt = None
    no_dispatch = tracker.dispatched == 0 or tracker.nonbillable_test
    if not no_dispatch:
        try:
            receipt = prepare_checklist_usage_receipt(
                operation_id=tracker.reservation.operation_id,
                user_id=tracker.reservation.user_id, approved_model=checklist_budget.MODEL,
                responses=tuple(tracker.responses), dispatched_requests=tracker.dispatched,
                usage=generation.usage,
                # A semantic/validation failure does not erase complete bills.
                completed=tracker.dispatched == len(tracker.responses),
                dispatched_at=tracker.reservation.dispatch_at,
                request_id=current_request_id(),
            )
        except UsageReceiptUnavailable:
            content = None
            if generation.error is None:
                generation.error = RuntimeError("Checklist bill is incomplete")
    try:
        checklist_budget.reconcile(tracker.reservation, receipt=receipt, content=content,
                                   no_dispatch=no_dispatch)
    except Exception:
        if generation.error is not None and not isinstance(generation.error, Exception):
            logger.warning("Checklist cancellation left usage pending reconciliation")
            raise generation.error
        raise
    if generation.error is not None:
        raise generation.error


def _current_checklist(user_id: str, course_id: str, semester: str | None):
    now = datetime.now(timezone.utc)
    scope = resolve_scope(user_id, course_id, semester)
    snapshot = build_snapshot(user_id, scope, now.date())
    return now, scope, snapshot, _cache(scope)


def _needs_generation(snapshot: dict, cache: dict | None) -> bool:
    return bool(snapshot["payload"]["sources"]) and (cache is None or cache["input_hash"] != snapshot["hash"])


def refresh_checklist(user_id: str, course_id: str, semester: str | None = None) -> dict:
    now, scope, snapshot, cache = _current_checklist(user_id, course_id, semester)
    if not _needs_generation(snapshot, cache):
        return present(scope, snapshot, cache, now)
    with _generation_slot(user_id):
        # Another request may have filled this cache or changed the evidence
        # while we waited. Recheck owned scope, material and cache before any
        # rate/spend check or paid generation; a coalesced cache hit stays free.
        now, scope, snapshot, cache = _current_checklist(user_id, course_id, semester)
        if not _needs_generation(snapshot, cache):
            return present(scope, snapshot, cache, now)
        # SQL coalesces an already-committed same-hash cache before its atomic
        # capacity check. Do not deny a now-free cross-worker hit via a stale
        # Python budget preflight first.
        reservation = checklist_budget.admit(user_id, scope["enrollment_id"], snapshot["hash"])
        if reservation is None:
            return present(scope, snapshot, _cache(scope), now)
        try:
            try:
                decision = ai_budget.check(user_id, "generation")
            except ai_budget.AIBudgetUnavailable:
                raise HTTPException(503, "AI usage is temporarily unavailable. Please try again.") from None
            if decision.level == "hard":
                raise ai_budget.AIBudgetExceeded(decision)
            retry = check_rate_limit(f"topic-checklist:{user_id}", limit=6, window_sec=60)
            if retry is not None:
                raise HTTPException(429, "Please wait before generating another checklist.", headers={"Retry-After": str(retry)})
            prior = TopicOutline.model_validate(decrypt_json(cache["content"])) if cache else None
        except BaseException:
            # No model handler/coroutine has been entered. A failed ACK here
            # leaves only a reclaimable prepared lease, never a possible bill.
            try:
                checklist_budget.reconcile(reservation, no_dispatch=True)
            except Exception:
                logger.warning("Could not release an unused checklist reservation")
            raise
        try:
            generation = run_agent_sync(_generate({**snapshot["payload"],
                "existing_topic_names": [t.name for t in prior.topics] if prior else [],
            }, user_id, reservation))
            _finish_generation(generation, snapshot["payload"])
        except HTTPException:
            raise
        except Exception:
            logger.exception("Topic checklist generation failed")
            raise HTTPException(503, "Topic generation is temporarily unavailable. Please retry; any unconfirmed usage remains reserved.",
                                headers={"Retry-After": "120"}) from None
        # Cache publication and the stable bill were one database transaction.
        # A newer operation/ownership change can fence this result out safely.
        return present(scope, snapshot, _cache(scope), now)


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
    # A checkmark changes progress, never evidence: present it over the cheap
    # live view instead of re-reading and decrypting every source.
    return present(scope, build_snapshot(user_id, scope, evidence=False), cache, now)
