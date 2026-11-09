"""
backend/services/quiz/grounding.py — moved from routes/quiz.py (#118).

Course-material grounding for generation: the course row, BU code,
catalog + RAG chunks, the E8 uncovered report and the E6 do-not-repeat
block.

Function bodies are verbatim from the route; names (leading
underscores included) are unchanged, and routes/quiz.py re-exports them.
"""
import logging
from typing import NamedTuple

from db.connection import pg_quote_value, table
from services import events_service
from services.quiz.repetition import RecentQuestion
from services.rag_service import retrieve_chunks_detailed, format_rag_context
# The catalog read is routes/learn.py's and moves with the learn split
# (services/tutor/, last in the #118 order). Until then it is the one route
# this package imports: "don't touch other routers" outranks "no routes
# imports" for a move-only PR.
from routes.learn import _get_catalog_chunk

# Log records keep the name they had in routes/quiz.py before the #118 split:
# the move must not change what an operator (or a caplog test) filters on.
logger = logging.getLogger("routes.quiz")


class BuCodeLookup(NamedTuple):
    """Tri-state result of course id -> BU course_code resolution (E8).

    `code` set                  — resolved.
    `code=None, failed=False`   — this course genuinely has no BU code.
    `code=None, failed=True`    — the read raised; we do not know.

    The last two were one bare `None` until E8 started reporting reasons, and
    collapsing them made a Supabase outage report as `course_unresolved` —
    "this course has no BU code", a statement about the data. E8 exists to
    tell problems apart, so the can't-tell case has to stay separable.
    """

    code: str | None = None
    failed: bool = False


class CourseRow(NamedTuple):
    """The one `courses` read a generation needs, shared across its legs.

    Two consumers want columns off the same row — grounding wants
    `course_code`, the H4 flashcard signal wants `course_name` — and they run
    in CONCURRENT legs of the gather below, so nothing can be shared by
    accident. Reading it once here is what keeps that one read one read.

    `failed` is tri-state exactly as `BuCodeLookup` is: a read that raised is
    "we could not look", not "there is nothing to look up".
    """

    code: str | None = None
    name: str | None = None
    failed: bool = False


def _course_row(course_id: str | None) -> CourseRow:
    """The course's catalog code and display name. Never raises."""
    if not course_id:
        return CourseRow()
    try:
        rows = table("courses").select(
            "course_code,course_name", filters={"id": f"eq.{course_id}"}, limit=1
        )
    except Exception:
        logger.warning(
            "quiz: course lookup failed for course=%s; grounding coverage is "
            "unknown (not absent), and the flashcard signals report unknown "
            "rather than counting an offering-only subset", course_id,
            exc_info=True,
        )
        return CourseRow(failed=True)
    row = rows[0] if rows else {}
    return CourseRow(
        code=(row.get("course_code") or None),
        name=(row.get("course_name") or None),
    )


def _resolve_bu_code(
    course_id: str | None, *, course: CourseRow | None = None
) -> BuCodeLookup:
    """Resolve a Sapling course UUID to its BU course_code (course_chunks
    partition key). Never raises — grounding must never break quiz
    generation — so a failed read comes back as `failed=True` rather than as
    an exception or an indistinguishable None.

    `course` injects a row the caller already read, so a generation that
    needs the same row for something else does not pay for it twice."""
    row = course if course is not None else _course_row(course_id)
    return BuCodeLookup(code=row.code, failed=row.failed)


class CourseMaterial(NamedTuple):
    """What grounding produced for one generation (E5 + E8).

    Before E5 this was a bare string: the chunk ids that grounded a question
    were resolved, formatted into the prompt, and dropped on the floor. That
    made two things impossible — saying which source a stored question came
    from, and telling an ungrounded generation apart from a grounded one.
    """

    #: The assembled prompt text ("" when there is nothing to ground on).
    block: str = ""
    #: Ids of the `course_chunks` rows in `block`, in rank order.
    chunk_ids: tuple[str, ...] = ()
    #: How many chunks are IN the prompt. Tracked separately from
    #: len(chunk_ids) because groundedness is a property of the text the
    #: model saw, not of our ability to name its sources: a row missing an
    #: id still grounded the question, and reporting that generation as
    #: ungrounded would be a lie in the direction that matters.
    k_chunks: int = 0
    #: Whether the official catalog chunk was included.
    has_catalog: bool = False
    #: Total chunks indexed for this course. Resolved ONLY when retrieval
    #: came back empty — it is the difference between "this course has no
    #: material at all" and "it has material, none of it matched this
    #: concept", which are different problems with different fixes. None
    #: means not asked, or the count read failed.
    course_chunks: int | None = None
    #: The BU course_code partition key, or None when unresolvable.
    bu_code: str | None = None
    #: Whether assembling this material FAILED rather than found nothing:
    #: the course_code read raised, or `_course_material` itself blew up and
    #: the caller degraded. Distinct from `bu_code is None` because E8's whole
    #: job is telling problems apart, and "we could not look" is a different
    #: problem from "this course has no BU code" — the honest label for the
    #: former is `coverage_unknown`, not `course_unresolved`.
    resolution_failed: bool = False
    #: Whether concept-scoped RETRIEVAL raised (as opposed to cleanly matching
    #: nothing). `retrieve_chunks` degrades to [] on failure, which is
    #: indistinguishable from a clean miss — so without this, a course with
    #: material indexed whose retrieval broke was reported as
    #: `no_match_for_concept`: "it has material, none covers this concept".
    #: That is a claim about data we never read. Same reasoning as
    #: `resolution_failed`, one layer down.
    retrieval_failed: bool = False

    @property
    def chunk_count(self) -> int:
        """Chunks in the prompt.

        Falls back to the id count so a partially-specified instance can
        never read as ungrounded while visibly carrying sources — the two
        fields disagreeing should be impossible, not merely unlikely.
        """
        return max(self.k_chunks, len(self.chunk_ids))

    @property
    def rag_grounded(self) -> bool:
        """Whether retrieved DOCUMENT chunks are in the prompt.

        Deliberately not named `grounded`: the catalog block is course
        material too, and a course with catalog data but nothing indexed
        does put real material in front of the model. Calling that
        "ungrounded" would write a false record into every stored
        question's provenance — the same class of lie `chunk_count` exists
        to prevent. `has_catalog` carries the other half, and both are
        stamped separately.
        """
        return self.chunk_count > 0


_EMPTY_MATERIAL = CourseMaterial()
# Grounding could not be assessed at all (an unexpected raise out of
# `_course_material`). Distinct from _EMPTY_MATERIAL, which means "we looked
# and there was nothing".
_UNKNOWN_MATERIAL = CourseMaterial(resolution_failed=True)


# k for concept-scoped retrieval. Named because E8 reports it and the audit's
# proposed budget wants to trim it from 5 to 4 once the numbers are measured
# (F6) rather than estimated.
_RAG_K = 5


def _course_chunk_coverage(bu_code: str, user_id: str | None) -> int | None:
    """How many chunks are indexed for this course, or None if unknown.

    Cheap: PostgREST's exact count with a one-row window — never pulls the
    table. Only called when retrieval returned nothing, so the common
    (grounded) path pays for no extra query at all.

    A count of 0 is only reported when it is TRUSTWORTHY.
    `select_with_count` returns `total = 0` both for a genuinely empty table
    and for a missing or unparseable `Content-Range` header
    (db/connection.py) — and those two mean opposite things here. Reporting a
    degraded count as 0 would have E8 assert "this course has nothing
    indexed" about a course that may be fully indexed, destroying the exact
    distinction the reason taxonomy exists to draw. So a zero count with rows
    actually returned is treated as unknown.
    """
    # Scoped to what THIS student could actually retrieve (#629). An unscoped
    # count would report a course as covered on the strength of rows the
    # reader is not allowed to see, which sends E8's grounding diagnosis the
    # wrong way for precisely the students the privacy filter applies to.
    # `uploader_id` rather than the contributor ledger: this is a diagnostic
    # counter, and a shared row that an opt-out later flipped private can be
    # reachable via the ledger while not counted here. Undercounting a
    # diagnostic is the acceptable direction; a join per quiz is not.
    filters: dict = {"course_id": f"eq.{bu_code}"}
    if user_id:
        # `pg_quote_value`: inside a logic tree a bare operand ends at the
        # first comma or paren, so an id carrying either would reshape the
        # filter rather than error.
        filters["or"] = (
            f"(visibility.eq.shared,uploader_id.eq.{pg_quote_value(user_id)})"
        )
    else:
        filters["visibility"] = "eq.shared"
    try:
        rows, total = table("course_chunks").select_with_count(
            "id", filters=filters, limit=1,
        )
        if total == 0 and rows:
            logger.warning(
                "quiz: course-chunk count came back 0 while rows exist for "
                "course_code=%s — treating coverage as unknown", bu_code,
            )
            return None
        return total
    except Exception:
        logger.warning(
            "quiz: course-chunk coverage read failed for course_code=%s", bu_code,
        )
        return None


def _course_material(
    course_id: str | None,
    concept_name: str,
    *,
    course: CourseRow | None = None,
    user_id: str | None = None,
) -> CourseMaterial:
    """Best-effort catalog + document-chunk context for a concept.

    Returns an empty CourseMaterial if nothing is available (no course, no
    bu_code, no chunks) or if retrieval raises — grounding must never break
    quiz generation. A course_code read that FAILED is reported as such
    (`resolution_failed`) rather than as an absent bu_code, so E8 can tell
    "we could not look" from "there is nothing to look up".

    `course` injects a `courses` row the caller already read (see `CourseRow`).

    `user_id` is the READER (#629). Shared course rows plus this student's own
    uploads; omitting it asks for shared rows only, which is fail-closed but
    would cut an opted-out student off from their own material.
    """
    lookup = _resolve_bu_code(course_id, course=course)
    bu_code = lookup.code
    if not bu_code:
        return _UNKNOWN_MATERIAL if lookup.failed else _EMPTY_MATERIAL
    blocks: list[str] = []
    try:
        catalog = _get_catalog_chunk(bu_code)
    except Exception:
        catalog = ""
    if catalog:
        blocks.append("COURSE CATALOG (official BU course data):\n\n" + catalog)
    # `_detailed` because [] alone cannot say whether retrieval ran: it is
    # both "nothing matched" and "the index was unreachable". E8 reports on
    # that difference, so it has to be carried rather than inferred.
    retrieval = retrieve_chunks_detailed(
        concept_name, course_id=bu_code, k=_RAG_K, user_id=user_id
    )
    chunks = retrieval.chunks
    # Drop any retrieved chunk that merely repeats the catalog block already
    # injected above — catalog chunks share the course_chunks store and can
    # rank into the semantic results, which would send the same
    # course-description text to the model twice (wasted prompt tokens).
    if catalog:
        catalog_norm = catalog.strip()
        chunks = [c for c in chunks if (c.get("chunk_text") or "").strip() != catalog_norm]
    rag_block = format_rag_context(chunks)
    if rag_block:
        blocks.append(rag_block)
    # Ids are what make a stored question traceable back to its source. Rows
    # without one are still usable as prompt text, so they are kept in the
    # block and simply absent from the provenance list.
    chunk_ids = tuple(
        str(c.get("id")) for c in chunks if isinstance(c, dict) and c.get("id")
    )
    return CourseMaterial(
        block="\n\n".join(blocks),
        chunk_ids=chunk_ids,
        k_chunks=len(chunks),
        has_catalog=bool(catalog),
        course_chunks=None if chunks else _course_chunk_coverage(bu_code, user_id),
        bu_code=bu_code,
        retrieval_failed=retrieval.failed,
    )


def _log_rag_uncovered(
    material: CourseMaterial,
    *,
    user_id: str,
    concept_node_id: str,
    request_id: str | None,
) -> None:
    """E8: make an ungrounded generation a decision, not an accident.

    Generation is NOT blocked on this — a course with nothing indexed is a
    legitimate mode, and refusing to quiz a student because their class
    hasn't uploaded slides would be worse than a general-knowledge quiz.
    But it stops being invisible: the reasons below are different
    problems, and telling them apart is the whole point.
    """
    if material.rag_grounded:
        return
    if material.resolution_failed:
        # The course_code read raised, or assembly blew up entirely. We never
        # learned whether this course has material, so `course_unresolved`
        # ("it has no BU code") would be an assertion about data we never
        # read. `coverage_unknown` is the honest can't-tell label, and it
        # already exists for exactly this shape of ignorance.
        reason = "coverage_unknown"
    elif material.retrieval_failed:
        # Retrieval raised, so we never learned whether this course's material
        # covers the concept. `no_match_for_concept` would assert that it
        # doesn't. `rag.retrieval_failed` carries the cause under the same
        # request_id; this event's job is only to stop claiming more than we
        # know.
        reason = "coverage_unknown"
    elif material.bu_code is None:
        reason = "course_unresolved"
    elif material.course_chunks is None:
        reason = "coverage_unknown"
    elif material.course_chunks == 0:
        reason = "no_chunks_for_course"
    else:
        reason = "no_match_for_concept"
    # INFO, not WARNING: in function mode the embedding seam is disabled by
    # design (#439), so every E2E generation lands here. A warning per run
    # would train readers to ignore the one that matters.
    logger.info(
        "quiz: generating without course grounding (reason=%s course_chunks=%s "
        "request_id=%s)", reason, material.course_chunks, request_id,
    )
    events_service.log_event(
        "quiz.rag_uncovered",
        # category="usage", NOT "error". Ungrounded generation is a
        # legitimate mode — this event exists to make it countable, not to
        # report a failure — and /api/admin/analytics/errors scans
        # `category = error` newest-first (B re-keyed it off the error.*
        # name prefix precisely so non-HTTP failures would surface). Since
        # this fires on EVERY generation for any unindexed course, and on
        # every function-mode run, filing it as an error would bury
        # quiz.context_write_failed and rag.retrieval_failed under routine
        # traffic and inflate the error series — degrading the surface that
        # workstream B just repaired. `rag.retrieval_failed` stays an error
        # because retrieval FAILING is one; nothing failed here.
        category="usage",
        user_id=user_id,
        request_id=request_id,
        payload={
            "concept_node_id": concept_node_id,
            "reason": reason,
            "course_chunks": material.course_chunks,
            "k_chunks": material.chunk_count,
        },
    )


def _do_not_repeat_block(recent: list[RecentQuestion]) -> str:
    """E6: name the questions this student has already been served.

    Stems, not hashes — "do not repeat 9f3a2c…" is unactionable for a model.
    Neutralized at this boundary because a stem is LLM-written text derived
    from student-uploaded course material, so it re-enters a prompt as
    untrusted content (#150), exactly like the top-up's already-asked list.
    """
    if not recent:
        return ""
    from services.prompt_safety import neutralize_delimiters

    lines = "\n".join(f"- {neutralize_delimiters(r.stem)}" for r in recent)
    return (
        "\n\n[RECENTLY ASKED] This student has already been served the "
        "questions below on this concept. Do NOT repeat them or trivially "
        "reword them — write new questions, on the same concept, that probe "
        "it differently:\n" + lines
    )
