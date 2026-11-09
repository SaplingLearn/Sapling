"""Seed one existing account with a realistic semester for a chosen major.

Admin-triggered (``POST /api/admin/accounts/{user_id}/seed``) on every
environment, prod included — see
docs/superpowers/specs/2026-11-08-admin-account-tools-design.md.

Shape of a run:

1. Validate the major (``UnknownMajor``) and that a live (not soft-deleted)
   ``users`` row exists (``UnknownAccount``), and resolve the current term
   (``NoCurrentTerm``) — all BEFORE anything is written, so a request that
   cannot succeed changes nothing.
2. Wipe the account's academic/study data (``services/account_wipe.py``).
   Re-seeding replaces, never stacks.
3. Resolve each pack course in the catalog by ``course_code`` (creating the
   ``courses`` row only when a bare stack lacks it) and its offering in the
   current term.
4. Build every row in memory (pure: ``build_rows``), then insert them one
   batch per table in FK order.

Not atomic — PostgREST has no transactions. Because step 2 always runs first,
re-running after a mid-way failure converges on the same end state.

No LLM calls and no fixed ids: content is the static pack, ids are uuid4, so
the same account can be seeded again (or another account seeded alongside).
Every 🔒 column is encrypted here with the environment's own key.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING

from learning.bkt import tier_for
from db.connection import table
from services.academics import clear_academics_caches, current_term, resolve_offering
from services.account_bundle import account_exists
from services.account_wipe import wipe_account_data
from services.auth_guard import clear_account_state_cache
from services.encryption import encrypt_if_present, encrypt_json
from services.growth import level_for_xp
from services.quiz_identity import question_hash

if TYPE_CHECKING:
    from services.account_seed.schema import Course, MajorPack

logger = logging.getLogger(__name__)

#: The fallback school for a catalog course a bare stack lacks, used only when
#: no ``courses`` row exists at all to borrow a school from.
SAMPLE_SCHOOL_SLUG = "sapling-sample"
SAMPLE_SCHOOL_NAME = "Sapling Sample University"

#: Same labels routes/quiz.py stamps on MCQ options (``_OPTION_LABELS``).
_OPTION_LABELS = ("A", "B", "C", "D", "E", "F")

#: Tables in insert (FK) order. Documents go before enrollments so the
#: syllabus document can be the enrollment's ``syllabus_doc_id``.
INSERT_ORDER = (
    "documents",
    "enrollments",
    "gradebook_categories",
    "assignments",
    "graph_nodes",
    "graph_edges",
    "node_mastery_events",
    "notes",
    "note_concepts",
    "flashcards",
    "study_guides",
    "quiz_attempts",
    "quiz_responses",
    "sessions",
    "messages",
    "xp_events",
)


class UnknownMajor(ValueError):
    """No pack for the requested major (raised before anything is written)."""


class UnknownAccount(LookupError):
    """No live (non-deleted) account with this id (raised before anything is written)."""


class NoCurrentTerm(RuntimeError):
    """The environment has no current term (raised before anything is written)."""


def packs() -> dict[str, MajorPack]:
    """The registry of major packs (lazy: the pack modules are heavy, static
    content and only the admin tools need them)."""
    from services.account_seed.packs import PACKS

    return PACKS


# ── helpers ──────────────────────────────────────────────────────────────────


def _new_id() -> str:
    return str(uuid.uuid4())


def _at(day: date, hour: int = 15, minute: int = 0) -> str:
    """An ISO timestamp (UTC) on ``day``."""
    return datetime.combine(day, time(hour, minute), tzinfo=timezone.utc).isoformat()


def _points(value: float) -> str:
    """``100.0`` -> ``"100"``: the string the 🔒 points columns hold."""
    return f"{value:g}"


def _utc_today() -> date:
    # UTC calendar days, as streak_service and the XP ledger use.
    return datetime.now(timezone.utc).date()


@dataclass(frozen=True)
class ResolvedCourse:
    course_id: str  # abstract catalog course (the graph's key)
    offering_id: str  # current-term offering (enrollment / class artifacts)
    name: str  # catalog course_name (the graph's subject label)


# ── catalog resolution ───────────────────────────────────────────────────────


def _fallback_school_id() -> str:
    rows = table("courses").select(
        "school_id", filters={"school_id": "not.is.null"}, limit=1,
    ) or []
    if rows and rows[0].get("school_id"):
        return rows[0]["school_id"]
    school = table("schools").upsert(
        {"name": SAMPLE_SCHOOL_NAME, "slug": SAMPLE_SCHOOL_SLUG}, on_conflict="slug",
    ) or []
    if school and school[0].get("id"):
        return school[0]["id"]
    rows = table("schools").select("id", filters={"slug": f"eq.{SAMPLE_SCHOOL_SLUG}"}, limit=1)
    if not rows:
        raise RuntimeError("could not resolve a school for the sample course")
    return rows[0]["id"]


def _resolve_course(course: Course, term_id: str) -> tuple[ResolvedCourse, bool]:
    """(resolved course, created_catalog_row). Catalog first; a missing code
    (a bare local stack without the pulled catalog) gets one ``courses`` row
    so seeding never fails for lack of catalog."""
    rows = table("courses").select(
        "id,course_name",
        filters={"course_code": f"eq.{course.code}"},
        order="created_at.asc",
        limit=1,
    ) or []
    created = False
    if rows:
        course_id, name = rows[0]["id"], rows[0].get("course_name") or course.name
    else:
        made = table("courses").upsert(
            {
                "school_id": _fallback_school_id(),
                "course_code": course.code,
                "course_name": course.name,
                "department": course.department,
                "credits": course.credits,
            },
            on_conflict="school_id,course_code",
        ) or []
        if not made or not made[0].get("id"):
            raise RuntimeError(f"could not create catalog course {course.code}")
        course_id, name, created = made[0]["id"], course.name, True
    offering_id = resolve_offering(course_id, term_id, create=True)
    if not offering_id:
        raise RuntimeError(f"could not resolve an offering for {course.code}")
    return ResolvedCourse(course_id=course_id, offering_id=offering_id, name=name), created


# ── row building (pure) ──────────────────────────────────────────────────────


def _course_rows(
    user_id: str,
    course: Course,
    rc: ResolvedCourse,
    *,
    term_start: date,
    today: date,
    rows: dict[str, list[dict]],
    activity: list[tuple[str, str, str, date]],
) -> None:
    """Append one course's rows to ``rows``; record XP-earning activity as
    (rule_key, source_type, source_id, day) in ``activity``."""

    def past(days_ago: int) -> date:
        return today - timedelta(days=max(0, days_ago))

    # A day in the term, never in the future.
    def in_term(offset: int) -> date:
        return min(today, term_start + timedelta(days=max(0, offset)))

    # Documents (before the enrollment: the syllabus is its syllabus_doc_id).
    syllabus_doc_id = None
    for i, doc in enumerate(course.documents):
        doc_id = _new_id()
        if doc.category == "syllabus" and syllabus_doc_id is None:
            syllabus_doc_id = doc_id
        day = in_term(1 + i * 9)
        stamp = _at(day, 10 + i)
        rows["documents"].append({
            "id": doc_id,
            "user_id": user_id,
            "offering_id": rc.offering_id,
            "file_name": doc.file_name,
            "category": doc.category,
            "summary": encrypt_if_present(doc.summary),
            "concept_notes": encrypt_json([n.model_dump() for n in doc.concept_notes]),
            "extracted_text": encrypt_if_present(doc.extracted_text),
            # The sweeper indexes these PRIVATELY: personal_notes at full
            # confidence can never enter a class pool (chunk_visibility).
            "index_status": "pending",
            "index_attempts": 0,
            "shareability": "personal_notes",
            "shareability_confidence": 1.0,
            "created_at": stamp,
            "processed_at": stamp,
        })
        activity.append(("document_uploaded", "document", doc_id, day))

    enrollment_id = _new_id()
    rows["enrollments"].append({
        "id": enrollment_id,
        "user_id": user_id,
        "offering_id": rc.offering_id,
        "color": course.color,
        "nickname": course.nickname,
        "syllabus_doc_id": syllabus_doc_id,
    })

    # Gradebook: categories, then assignments graded only once past due.
    category_ids: dict[str, str] = {}
    for order, cat in enumerate(course.categories):
        cat_id = _new_id()
        category_ids[cat.name] = cat_id
        rows["gradebook_categories"].append({
            "id": cat_id,
            "enrollment_id": enrollment_id,
            "name": cat.name,
            "weight": cat.weight,
            "drop_lowest": cat.drop_lowest,
            "sort_order": order,
        })
    midterm: tuple[str, str, date] | None = None
    for a in course.assignments:
        asg_id = _new_id()
        due = term_start + timedelta(days=a.due_offset_days)
        graded = a.points_earned is not None and due < today
        rows["assignments"].append({
            "id": asg_id,
            "enrollment_id": enrollment_id,
            "category_id": category_ids[a.category],
            "title": a.title,
            "due_date": due.isoformat(),
            "assignment_type": a.type,
            "source": "syllabus",
            "points_possible": encrypt_if_present(_points(a.points_possible)),
            "points_earned": encrypt_if_present(_points(a.points_earned)) if graded else None,
        })
        if a.is_midterm:
            midterm = (asg_id, a.title, due)

    # Knowledge graph on the ABSTRACT course (mastery is cumulative).
    node_ids: dict[str, str] = {}
    for i, concept in enumerate(course.concepts):
        node_id = _new_id()
        node_ids[concept.name] = node_id
        studied = concept.mastery > 0
        rows["graph_nodes"].append({
            "id": node_id,
            "user_id": user_id,
            "course_id": rc.course_id,
            "concept_name": concept.name,
            "subject": rc.name,
            "mastery_score": concept.mastery,
            "mastery_tier": tier_for(concept.mastery),
            # times_studied = 0 is how the app tells "never studied" apart
            # from "studied, still below the struggling floor".
            "times_studied": (1 + round(concept.mastery * 6)) if studied else 0,
            "last_studied_at": _at(past(1 + (i * 3) % 14), 19) if studied else None,
        })
    for e in course.edges:
        rows["graph_edges"].append({
            "id": _new_id(),
            "user_id": user_id,
            "source_node_id": node_ids[e.source],
            "target_node_id": node_ids[e.target],
            "relationship_type": e.relationship,
            "strength": e.strength,
        })
    for i, m in enumerate(course.mastery_events):
        rows["node_mastery_events"].append({
            "id": _new_id(),
            "node_id": node_ids[m.concept],
            "delta": m.delta,
            "reason": m.reason,
            "created_at": _at(past(2 + i * 4), 18),
        })

    # Notes (+ concept links).
    for i, note in enumerate(course.notes):
        note_id = _new_id()
        day = in_term(4 + i * 11)
        rows["notes"].append({
            "id": note_id,
            "user_id": user_id,
            "offering_id": rc.offering_id,
            "title": encrypt_if_present(note.title),
            "body": encrypt_if_present(note.body),
            "tags": list(note.tags),
            "created_at": _at(day, 20),
            "updated_at": _at(day, 20, 30),
        })
        for concept_name in note.concepts:
            rows["note_concepts"].append({
                "note_id": note_id,
                "concept_node_id": node_ids[concept_name],
            })
        activity.append(("note_created", "note", note_id, day))

    # Flashcards.
    for i, card in enumerate(course.flashcards):
        rows["flashcards"].append({
            "id": _new_id(),
            "user_id": user_id,
            "offering_id": rc.offering_id,
            "topic": rc.name,
            "front": encrypt_if_present(card.front),
            "back": encrypt_if_present(card.back),
            "created_at": _at(in_term(6 + i), 21),
        })

    # The cached study guide targets the midterm (exam_id = its assignment).
    if midterm is not None:
        exam_id, exam_title, exam_due = midterm
        # A few days before the exam, never before the term nor in the future.
        generated = min(today, max(term_start, min(today - timedelta(days=1),
                                                   exam_due - timedelta(days=3))))
        rows["study_guides"].append({
            "id": _new_id(),
            "user_id": user_id,
            "offering_id": rc.offering_id,
            "exam_id": exam_id,
            "generated_at": _at(generated, 17),
            "content": encrypt_json({
                "exam": exam_title,
                "due_date": exam_due.isoformat(),
                "overview": course.study_guide.overview,
                "topics": [t.model_dump() for t in course.study_guide.topics],
            }),
        })

    # Completed quiz attempts, in the wire shape routes/quiz.py stores.
    mastery_by_name = {c.name: c.mastery for c in course.concepts}
    for quiz in course.quizzes:
        attempt_id = _new_id()
        correct = {i for i in quiz.correct if 0 <= i < len(quiz.questions)}
        wire, answers = [], []
        completed_day = past(quiz.days_ago)
        completed = datetime.combine(completed_day, time(16, 0), tzinfo=timezone.utc)
        started = completed - timedelta(minutes=2 * len(quiz.questions) + 2)
        for qi, q in enumerate(quiz.questions):
            options = [
                {"label": _OPTION_LABELS[oi], "text": text, "correct": text == q.correct_answer}
                for oi, text in enumerate(q.options)
            ]
            right = next(oi for oi, o in enumerate(options) if o["correct"])
            wrong = next(oi for oi, o in enumerate(options) if not o["correct"])
            chosen = right if qi in correct else wrong
            wire.append({
                "id": qi + 1,
                "question": q.question,
                "options": options,
                "explanation": q.explanation,
                "concept_tested": quiz.concept,
                "difficulty": quiz.difficulty,
                "question_hash": question_hash(q.question, q.options),
            })
            answers.append({"question_id": qi + 1, "selected_label": _OPTION_LABELS[chosen]})
            rows["quiz_responses"].append({
                "id": _new_id(),
                "attempt_id": attempt_id,
                "question_index": qi,
                "selected_index": chosen,
                "is_correct": qi in correct,
                "time_ms": 25_000 + 7_000 * qi,
                "confidence": None,
                "answered_at": (started + timedelta(minutes=2 * qi + 1)).isoformat(),
            })
        score, total = len(correct), len(quiz.questions)
        after = mastery_by_name[quiz.concept]
        step = 0.06 if score * 2 >= total else -0.04
        before = min(1.0, max(0.0, after - step))
        rows["quiz_attempts"].append({
            "id": attempt_id,
            "user_id": user_id,
            "concept_node_id": node_ids[quiz.concept],
            "difficulty": quiz.difficulty,
            "questions_json": encrypt_json(wire),
            "answers_json": encrypt_json(answers),
            "score": score,
            "total": total,
            "mastery_before": round(before, 4),
            "mastery_after": round(after, 4),
            "created_at": started.isoformat(),
            "completed_at": completed.isoformat(),
        })
        activity.append(("quiz_completed", "quiz", attempt_id, completed_day))

    # One finished tutor session with its transcript.
    s = course.session
    session_id = _new_id()
    session_day = past(3)
    started = datetime.combine(session_day, time(19, 0), tzinfo=timezone.utc)
    minutes = 4 * len(s.messages)
    rows["sessions"].append({
        "id": session_id,
        "user_id": user_id,
        "offering_id": rc.offering_id,
        "mode": s.mode,
        "topic": s.topic,
        "name": s.name,
        # The shape routes/learn.py::_session_summary stores, plus the pack's
        # recap bullets.
        "summary_json": encrypt_json({
            "concepts_covered": [s.topic],
            "mastery_changes": [],
            "new_connections": [],
            "time_spent_minutes": minutes,
            "recommended_next": [],
            "bullets": list(s.summary_bullets),
        }),
        "started_at": started.isoformat(),
        "ended_at": (started + timedelta(minutes=minutes)).isoformat(),
    })
    for i, msg in enumerate(s.messages):
        rows["messages"].append({
            "id": _new_id(),
            "session_id": session_id,
            "role": msg.role,
            "content": encrypt_if_present(msg.content),
            "created_at": (started + timedelta(minutes=4 * i)).isoformat(),
        })
    activity.append(("session_completed", "session", session_id, session_day))


#: Amounts mirror the xp_rules seed (20260731193214_gamification.sql); the
#: ledger rows are what /activity and the XP achievements sum.
_XP_AMOUNTS = {
    "quiz_completed": 30,
    "session_completed": 25,
    "document_uploaded": 15,
    "note_created": 10,
}
_DAILY_RULE = "daily_goal_met"


def _xp_rows(
    user_id: str,
    activity: list[tuple[str, str, str, date]],
    *,
    total_xp: int,
    streak_days: int,
    today: date,
) -> list[dict]:
    """XP ledger rows summing to exactly ``total_xp``: one per seeded activity
    (until the budget runs out), the rest as daily-goal events over the
    streak's days so the activity chart agrees with the streak."""
    out: list[dict] = []
    spent = 0
    for n, (rule, source_type, source_id, day) in enumerate(sorted(activity, key=lambda a: a[3])):
        amount = _XP_AMOUNTS[rule]
        if spent + amount > total_xp:
            break
        spent += amount
        out.append({
            "id": _new_id(),
            "user_id": user_id,
            "rule_key": rule,
            "amount": amount,
            "source_type": source_type,
            "source_id": source_id,
            "idempotency_key": f"seed:{user_id}:{rule}:{n}",
            "created_at": _at(day, 21),
        })
    remaining = total_xp - spent
    days = max(1, streak_days)
    for k in range(days):
        amount = remaining // days + (remaining % days if k == days - 1 else 0)
        if amount <= 0:
            continue
        out.append({
            "id": _new_id(),
            "user_id": user_id,
            "rule_key": _DAILY_RULE,
            "amount": amount,
            "source_type": None,
            "source_id": None,
            "idempotency_key": f"seed:{user_id}:{_DAILY_RULE}:{k}",
            "created_at": _at(today - timedelta(days=k), 22),
        })
    return out


def build_rows(
    user_id: str,
    pack: MajorPack,
    resolved: list[ResolvedCourse],
    *,
    term_start: date,
    today: date,
) -> dict[str, list[dict]]:
    """Every row the seed inserts, per table — no I/O."""
    rows: dict[str, list[dict]] = {name: [] for name in INSERT_ORDER}
    activity: list[tuple[str, str, str, date]] = []
    for course, rc in zip(pack.courses, resolved, strict=True):
        _course_rows(
            user_id, course, rc,
            term_start=term_start, today=today, rows=rows, activity=activity,
        )
    rows["xp_events"] = _xp_rows(
        user_id, activity,
        total_xp=pack.total_xp, streak_days=pack.streak_days, today=today,
    )
    return rows


# ── entry point ──────────────────────────────────────────────────────────────


def seed_account(user_id: str, major: str, *, today: date | None = None) -> dict:
    """Wipe ``user_id``'s study data, then seed a semester of ``major``.

    Returns ``{"major", "wiped": {table: n}, "created": {table: n}}``.
    Raises ``UnknownMajor`` (a ``ValueError``), ``UnknownAccount`` (a
    ``LookupError``; soft-deleted accounts count as unknown) or
    ``NoCurrentTerm`` (a ``RuntimeError``) — each BEFORE the wipe. Anything
    raised after the wipe (e.g. ``AccountWipeIncomplete``) leaves a partly
    seeded account that a re-run converges.
    """
    try:
        pack = packs()[major]
    except KeyError:
        raise UnknownMajor(f"unknown major {major!r}") from None
    if not account_exists(user_id):
        raise UnknownAccount(f"user {user_id!r} not found")
    today = today or _utc_today()
    term = current_term(today)
    if not term:
        raise NoCurrentTerm("no current term is configured; cannot place seeded courses")
    term_id = term["id"]
    term_start = date.fromisoformat(str(term["start_date"])[:10])

    wiped = wipe_account_data(user_id)

    created: dict[str, int] = {}
    resolved: list[ResolvedCourse] = []
    for course in pack.courses:
        rc, made = _resolve_course(course, term_id)
        resolved.append(rc)
        if made:
            created["courses"] = created.get("courses", 0) + 1

    rows = build_rows(user_id, pack, resolved, term_start=term_start, today=today)
    for name in INSERT_ORDER:
        if rows[name]:
            table(name).insert(rows[name])
            created[name] = len(rows[name])

    total_xp = sum(r["amount"] for r in rows["xp_events"])
    table("users").update(
        {
            "onboarding_completed": True,
            "total_xp": total_xp,
            "level": level_for_xp(total_xp),
            "streak_count": pack.streak_days,
            "longest_streak": max(pack.streak_days, (pack.streak_days * 3 + 1) // 2),
            "last_active_date": today.isoformat(),
        },
        filters={"id": f"eq.{user_id}"},
    )
    table("user_profiles").upsert(
        {"user_id": user_id, "majors": [pack.label], "year": pack.year},
        on_conflict="user_id",
    )

    clear_account_state_cache(user_id)
    if "courses" in created:
        clear_academics_caches()

    logger.info(
        "account seed: user=%s major=%s term=%s created=%d rows wiped=%d rows",
        user_id, major, term_id, sum(created.values()), sum(wiped.values()),
    )
    return {"major": major, "wiped": wiped, "created": created}
