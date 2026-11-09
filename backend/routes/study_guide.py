"""
backend/routes/study_guide.py

Study guide generation and caching.
"""

import logging
import threading
import uuid
import weakref
from contextlib import contextmanager
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Body, HTTPException, Query, Request

from agents._run import run_agent_sync
from agents.deps import SaplingDeps
from agents.study_guide import study_guide_agent
from agents.usage import record_agent_usage
from db.connection import table
from services.academics import (
    offering_course_id,
    resolve_offering,
    term_for_offering,
    term_id_for_label,
    user_enrollment_ids,
    user_offering_ids_for_course,
)
from services.graph_service import get_courses as graph_get_courses
from services.auth_guard import require_self
from services.exam_proximity import is_exam
from services.encryption import (
    decrypt_if_present,
    decrypt_json,
    decrypt_json_column,
    encrypt_json,
)
from services import pg_lease
from services.http_cache import cached_json, conditional, make_etag
from services.request_context import current_request_id

logger = logging.getLogger(__name__)

router = APIRouter()


def _offering_for(course_id: str, semester: str | None) -> str | None:
    """course → offering, term-aware (#141).

    No ``semester`` → the existing current-term resolution (with the
    any-offering fallback), byte-for-byte unchanged. An explicit ``semester``
    (term label) → STRICT (course, term) lookup: an unknown label or a term
    with no offering of the course returns None — never another term's
    offering — so callers degrade to their empty/404 behavior.
    """
    if not semester:
        return resolve_offering(course_id)
    term_id = term_id_for_label(semester)
    if not term_id:
        return None
    return resolve_offering(course_id, term_id, fallback=False)


def _course_enrollment_ids(
    user_id: str, course_id: str, semester: str | None = None
) -> list[str]:
    """The user's enrollment ids for the given abstract ``course_id``.

    The ``assignments`` table is enrollment-keyed (the gradebook table has no
    ``user_id``/``course_id`` column — see routes/gradebook.py). The HTTP
    boundary speaks the abstract course id, so we resolve
    course → the user's offering(s) of it → their enrollment rows, mirroring
    routes/calendar.py::_read_assignments.

    With a ``semester`` (#141) only the offerings in that term survive; an
    unknown label yields no enrollments (empty result, never a fallback).
    """
    course_offerings = set(user_offering_ids_for_course(user_id, course_id))
    if semester:
        term_id = term_id_for_label(semester)
        if not term_id:
            return []
        course_offerings = {
            o for o in course_offerings
            if (term_for_offering(o) or {}).get("id") == term_id
        }
    if not course_offerings:
        return []
    return [
        e["id"]
        for e in user_enrollment_ids(user_id)
        if e.get("offering_id") in course_offerings
    ]


class _KeyLock:
    """A per-(user, offering, exam) lock; weakly held so idle keys vanish."""

    __slots__ = ("lock", "__weakref__")

    def __init__(self) -> None:
        self.lock = threading.Lock()


_key_locks: "weakref.WeakValueDictionary[tuple[str, str, str], _KeyLock]" = (
    weakref.WeakValueDictionary()
)
_key_locks_guard = threading.Lock()


def _guide_lock(user_id: str, offering_id: str | None, exam_id: str) -> _KeyLock:
    """Single-flight per guide (#771): concurrent cache misses for the same
    guide used to generate (and insert) it twice. The caller holds the
    returned object for as long as it needs the lock. Per process: across
    replicas, :func:`_single_flight` adds a Postgres lease (`stateless_locks`);
    the insert-time doc check below keeps either result consistent with the
    documents."""
    key = (user_id, offering_id or "", exam_id)
    with _key_locks_guard:
        kl = _key_locks.get(key)
        if kl is None:
            kl = _key_locks[key] = _KeyLock()
        return kl


#: The cross-replica lease on one guide's generation (#117): held for this
#: long and renewed while the generation runs, so a crashed replica's lease
#: frees itself within a minute.
GUIDE_LEASE_TTL_S = 60
#: How long a request waits for ANOTHER replica's generation of the same guide
#: before generating anyway (what a second replica did before the lease). An
#: in-process waiter blocks on the thread lock without a bound, as before.
GUIDE_LEASE_WAIT_S = 150.0
GUIDE_LEASE_POLL_S = 1.0


@contextmanager
def _single_flight(user_id: str, offering_id: str | None, exam_id: str):
    """The in-process lock first, then (flag `stateless_locks`) the Postgres
    lease, so a concurrent miss on another replica waits for this generation
    and then reads its cached row, as an in-process waiter always has. If the
    other replica takes longer than GUIDE_LEASE_WAIT_S this one proceeds
    (the pre-lease behaviour); the store being off or down is a no-op."""
    flight = _guide_lock(user_id, offering_id, exam_id)
    key = pg_lease.hashed_key("study_guide", user_id, offering_id or "", exam_id)
    with flight.lock, pg_lease.lease(key, GUIDE_LEASE_TTL_S, wait_s=GUIDE_LEASE_WAIT_S,
                                     poll_s=GUIDE_LEASE_POLL_S):
        yield


def _material_fingerprint(user_id: str, offering_id: str) -> tuple[str, ...]:
    """The live documents a guide for (user, offering) is generated from.

    Uploading or deleting a document invalidates the offering's guides
    (routes/documents.py::_invalidate_study_guide_cache) — but a generation
    that read the documents BEFORE that and inserts AFTER it would leave a
    stale guide cached for good (#771). Comparing this before the read and
    after the insert catches exactly that: the document row lands before the
    invalidation runs, so either the check sees the new document or the
    invalidation deletes the inserted guide."""
    rows = table("documents").select(
        "id",
        filters={
            "user_id": f"eq.{user_id}",
            "offering_id": f"eq.{offering_id}",
            "deleted_at": "is.null",
        },
    ) or []
    return tuple(sorted(str(r.get("id")) for r in rows))


def _generate_and_insert(user_id: str, offering_id: str, exam_id: str) -> dict:
    """Generate a study guide, insert it into study_guides, and return
    ``{id, content, generated_at, cached}``.

    ``cached`` is False when the #771 stale-material check took the new row
    back out (the documents changed mid-generation): the student still gets
    ``content``, but no row with ``id`` exists, so a caller must not treat
    the new guide as having replaced anything.

    Study guides + the documents that feed them key on the OFFERING (0025);
    the caller resolves the abstract course id to an offering first.
    """
    # 1. Fetch exam info. Assignments key on enrollment_id (no user_id/course_id
    #    column); scope to the user's enrollment in THE RESOLVED OFFERING
    #    (#475 F3, the #462 CodeRabbit fix) — not all of their enrollments, or
    #    a multi-term user could generate (and persist) a guide keyed on one
    #    term's offering from another term's exam.
    enrollment_ids = [
        e["id"]
        for e in user_enrollment_ids(user_id)
        if e.get("offering_id") == offering_id
    ]
    exams = (
        table("assignments").select(
            "id,enrollment_id,title,due_date,assignment_type",
            filters={
                "id": f"eq.{exam_id}",
                "enrollment_id": f"in.({','.join(enrollment_ids)})",
            },
            limit=1,
        )
        if enrollment_ids
        else []
    )
    if not exams:
        # The frontend renders this detail verbatim, so it has to read like
        # guidance rather than a status line.
        raise HTTPException(
            status_code=404,
            detail="Exam not found. It may have been deleted — pick another exam.",
        )
    exam = exams[0]
    exam_title = exam.get("title", "")
    due_date = exam.get("due_date", "")

    # 2. Fetch documents for this user+offering. The id set is captured first
    #    so the insert below can tell whether the material changed meanwhile.
    material = _material_fingerprint(user_id, offering_id)
    docs = table("documents").select(
        "summary,concept_notes",
        filters={
            "user_id": f"eq.{user_id}",
            "offering_id": f"eq.{offering_id}",
            "deleted_at": "is.null",
        },
    ) or []

    # 3. Build combined context
    parts: list[str] = []
    for doc in docs:
        summary = decrypt_if_present(doc.get("summary"))
        if summary:
            parts.append(f"Summary: {summary}")
        notes_raw = doc.get("concept_notes")
        if isinstance(notes_raw, str):
            try:
                concept_notes = decrypt_json(notes_raw)
            except Exception:
                concept_notes = notes_raw
        else:
            concept_notes = notes_raw
        if concept_notes and isinstance(concept_notes, list):
            lines = []
            for note in concept_notes:
                if not isinstance(note, dict):
                    continue
                name = note.get("name")
                desc = note.get("description")
                if not name:
                    continue
                if desc:
                    lines.append(f"- {name}: {desc}")
                else:
                    lines.append(f"- {name}")
            if lines:
                parts.append("Key Concepts:\n" + "\n".join(lines))

    combined_context = "\n\n".join(parts) if parts else "No course material available."
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 4. Generate the study guide via the study_guide agent. The agent owns the
    #    persona + output schema; the user message carries the exam context.
    user_message = (
        f"Exam: {exam_title}\n"
        f"Due date: {due_date}\n"
        f"Today: {today}\n\n"
        f"Course material:\n{combined_context}"
    )
    # course_id/session are unused by this toolless agent; deps satisfies the type.
    from db.connection import _client  # opaque pass-through for SaplingDeps
    deps = SaplingDeps(
        user_id=user_id,
        course_id=None,
        supabase=_client,
        request_id=current_request_id() or "",
    )
    try:
        result = record_agent_usage(
            run_agent_sync(study_guide_agent.run(user_message, deps=deps)),
            feature="study_guide", task="study_guide", user_id=user_id,
        )
    except Exception as e:  # generation/transport failure → 502, not a raw 500
        raise HTTPException(
            status_code=502, detail="Study guide generation failed."
        ) from e
    content = result.output.model_dump()

    # 5. Insert into study_guides
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "offering_id": offering_id,
        "exam_id": exam_id,
        "generated_at": now,
        "content": encrypt_json(content),
    }
    row["id"] = _insert_or_replace(row)
    # #771: if the material changed while this guide was generating, its
    # invalidation may already have run — take the stale row back out so the
    # next request regenerates from the current documents. The student still
    # gets this answer; it just is not cached.
    cached = True
    if _material_fingerprint(user_id, offering_id) != material:
        logger.info(
            "study guide for offering %s generated across a document change; "
            "not caching it", offering_id,
        )
        table("study_guides").delete(filters={"id": f"eq.{row['id']}"})
        cached = False

    return {"id": row["id"], "content": content, "generated_at": now, "cached": cached}


def _is_unique_violation(exc: httpx.HTTPStatusError) -> bool:
    """PostgREST's 409 for a UNIQUE collision (23505), not an FK one (23503)."""
    if exc.response is None or exc.response.status_code != 409:
        return False
    try:
        return (exc.response.json() or {}).get("code") == "23505"
    except ValueError:
        return False


def _insert_or_replace(row: dict) -> str:
    """Insert the guide row and return its id. Where the
    `study_guides_user_offering_exam_key` unique index exists (migration
    20261109023732; created only on a table with no duplicates) a second row
    for the key is refused, so a regenerate — or a cross-replica race the
    lease did not serialise — replaces the key's row IN PLACE instead (new
    content and generated_at, same id). Without the index this is the plain
    insert it always was."""
    key = {"user_id": f"eq.{row['user_id']}", "offering_id": f"eq.{row['offering_id']}",
           "exam_id": f"eq.{row['exam_id']}"}
    for _attempt in range(2):
        try:
            table("study_guides").insert(row)
            return row["id"]
        except httpx.HTTPStatusError as exc:
            if not _is_unique_violation(exc):
                raise
        replaced = table("study_guides").update(
            {"content": row["content"], "generated_at": row["generated_at"]}, filters=key,
        ) or []
        if replaced:
            return replaced[0].get("id") or row["id"]
        # The row went between the two calls (an invalidation): insert again.
    raise HTTPException(status_code=409, detail="Study guide is being updated; try again.")


def _drop_older_guides(user_id: str, offering_id: str, exam_id: str, newer_than: str) -> None:
    """Best-effort: delete this key's guides generated BEFORE ``newer_than``
    (the just-inserted row's ``generated_at``).

    Keyed on time, not ``id=neq.<new id>``: the per-key lock is per-process,
    so two workers can regenerate the same guide concurrently, and with
    ``neq`` each would delete the OTHER's new row — leaving zero guides.
    With ``lt.<own generated_at>`` a row never deletes itself, so at least
    one new guide always survives. A failure here only leaves an older
    duplicate behind (reads take the newest), so it must never turn a
    successful, already-paid generation into a 500."""
    try:
        table("study_guides").delete(
            filters={
                "user_id": f"eq.{user_id}",
                "offering_id": f"eq.{offering_id}",
                "exam_id": f"eq.{exam_id}",
                "generated_at": f"lt.{newer_than}",
            }
        )
    except Exception:
        logger.warning(
            "study guide regenerate: could not drop older guides for offering %s exam %s",
            offering_id, exam_id, exc_info=True,
        )


@router.get("/{user_id}/cached")
def get_cached_guides(user_id: str, request: Request):
    require_self(user_id, request)
    guides = table("study_guides").select(
        "id,offering_id,exam_id,generated_at,content",
        filters={"user_id": f"eq.{user_id}"},
        order="generated_at.desc",
    )
    # ETag from the guides' (id, generated_at) — regenerate replaces rows with a
    # fresh id + timestamp, so this captures add/remove/regenerate. A matching
    # If-None-Match returns 304 and skips the per-offering course enrichment below.
    # "guides.v2": the shape gained per-entry `semester` (#475 F1); the version
    # bump revalidates bodies cached under the old shape.
    etag = make_etag("guides.v2", user_id, *sorted(f"{g['id']}:{g.get('generated_at')}" for g in guides))
    not_modified = conditional(request, etag)
    if not_modified is not None:
        return not_modified

    # Each guide keys on an offering; the frontend speaks abstract course ids.
    # Map each offering → its abstract course id + its term label (#475 F1: the
    # client opens a recent entry AS ITS OWN TERM, so each entry says which term
    # that is). Offering ids are deduped here; term_for_offering is lru-cached.
    offering_to_course: dict[str, str | None] = {}
    offering_terms: dict[str, str | None] = {}
    course_map: dict[str, str] = {}
    for g in guides:
        off_id = g.get("offering_id")
        if off_id and off_id not in offering_to_course:
            cid = offering_course_id(off_id)
            offering_to_course[off_id] = cid
            offering_terms[off_id] = (term_for_offering(off_id) or {}).get("label")
            if cid and cid not in course_map:
                rows = table("courses").select(
                    "id,course_name", filters={"id": f"eq.{cid}"}, limit=1
                )
                if rows:
                    course_map[cid] = rows[0]["course_name"]

    result = []
    for g in guides:
        try:
            content = decrypt_json_column(g.get("content")) or {}
        except Exception:
            logger.warning(
                "get_cached_guides: content decrypt failed for guide %s; degrading",
                g.get("id"),
            )
            content = {}
        course_id = offering_to_course.get(g.get("offering_id"))
        result.append({
            "id": g["id"],
            "course_id": course_id,
            "exam_id": g["exam_id"],
            "course_name": course_map.get(course_id or "", ""),
            "exam_title": content.get("exam", ""),
            "overview": content.get("overview", ""),
            "generated_at": g["generated_at"],
            # The entry's OWN term label (null when the offering has no term).
            "semester": offering_terms.get(g.get("offering_id")),
        })
    return cached_json({"guides": result}, etag)


@router.get("/{user_id}/courses")
def get_courses(user_id: str, request: Request):
    require_self(user_id, request)
    # The frontend enumerates courses via /api/graph/{user_id}/courses, so this
    # endpoint is currently unreachable from the UI. Kept alive (and off the old
    # non-existent courses.user_id filter that 500'd) by delegating to the same
    # enrollment-resolving helper the graph endpoint uses.
    return {"courses": graph_get_courses(user_id)}


@router.get("/{user_id}/exams")
def get_exams(
    user_id: str,
    request: Request,
    course_id: str = Query(...),
    semester: str | None = Query(None),
):
    require_self(user_id, request)
    enrollment_ids = _course_enrollment_ids(user_id, course_id, semester)
    if not enrollment_ids:
        return {"exams": []}
    all_assignments = table("assignments").select(
        "id,title,due_date,assignment_type",
        filters={"enrollment_id": f"in.({','.join(enrollment_ids)})"},
        order="due_date.asc",
    ) or []

    # The heuristic moved to services/exam_proximity.py (#555), which needed
    # the same question answered on the quiz path. One definition, two
    # callers — a second copy would drift, which is the failure #557 spent a
    # workstream undoing.
    return {"exams": [a for a in all_assignments if is_exam(a)]}


@router.get("/{user_id}/guide")
def get_guide(
    user_id: str,
    request: Request,
    course_id: str = Query(...),
    exam_id: str = Query(...),
    semester: str | None = Query(None),
):
    require_self(user_id, request)
    # The query param is the abstract course id; study guides key on the
    # offering. Without `semester` that's the current-term offering; with one,
    # the SELECTED term's (#141) — and a term with no offering is a 404, so a
    # guide is never generated for (or cached against) an offering that isn't
    # there.
    offering_id = _offering_for(course_id, semester)
    if semester and offering_id is None:
        raise HTTPException(
            status_code=404,
            detail="No offering of this course in that semester.",
        )
    def _cached() -> dict | None:
        rows = table("study_guides").select(
            "id,user_id,offering_id,exam_id,content,generated_at",
            filters={
                "user_id": f"eq.{user_id}",
                "offering_id": f"eq.{offering_id}",
                "exam_id": f"eq.{exam_id}",
            },
            # Newest first: a cross-worker race can still leave two rows.
            order="generated_at.desc",
            limit=1,
        )
        if not rows:
            return None
        row = rows[0]
        return {"guide": decrypt_json_column(row["content"]), "generated_at": row["generated_at"], "cached": True}

    hit = _cached()
    if hit:
        return hit
    with _single_flight(user_id, offering_id, exam_id):
        # A concurrent miss may have generated it while this one waited.
        hit = _cached()
        if hit:
            return hit
        result = _generate_and_insert(user_id, offering_id, exam_id)
    return {"guide": result["content"], "generated_at": result["generated_at"], "cached": False}


@router.post("/regenerate")
def regenerate_guide(request: Request, body: dict = Body(...)):
    user_id = body.get("user_id")
    course_id = body.get("course_id")
    exam_id = body.get("exam_id")
    # Optional term label (#141): regenerating replaces the SELECTED term's
    # guide, keyed on that term's offering.
    semester = body.get("semester")
    if not user_id or not course_id or not exam_id:
        raise HTTPException(status_code=400, detail="user_id, course_id, and exam_id are required.")
    require_self(user_id, request)

    offering_id = _offering_for(course_id, semester)
    if semester and offering_id is None:
        raise HTTPException(
            status_code=404,
            detail="No offering of this course in that semester.",
        )
    with _single_flight(user_id, offering_id, exam_id):
        # Generate FIRST, replace after: _generate_and_insert validates the exam
        # (404 for a missing/foreign one) and raises 502 on a failed generation,
        # and either must leave the student's existing guide in place. Only once
        # the new row is in do the older rows for this key go — and not at all
        # when the #771 stale-material check dropped the new row (deleting the
        # old ones then would leave the student with no guide).
        result = _generate_and_insert(user_id, offering_id, exam_id)
        if result["cached"]:
            _drop_older_guides(user_id, offering_id, exam_id, result["generated_at"])
    return {"success": True, "guide": result["content"], "generated_at": result["generated_at"]}
