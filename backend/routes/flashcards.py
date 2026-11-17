"""
backend/routes/flashcards.py — the /api/flashcards HTTP surface.

Each handler parses the request, checks the caller, calls the same-named
function in ``services/flashcards/`` (#118; the saved-set handlers call
``sets.py``'s ``*_flashcard_set``) and maps that package's domain errors to
the status codes in ``_ERROR_STATUS``. A test patch must target the module
that LOOKS UP the name now (``tests/split_patches.py::patch_flashcards``).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from models import Id, LongText, ShortText

from learning.gate import learning_loop_for_request
from routes._errors import domain_status
from services import abuse_limits, crisis_support
from services.auth_guard import require_self
from services.request_limits import aenforce_abuse_limit
from services.flashcards import (
    FlashcardError,
    FlashcardSetInvalid,
    FlashcardSetLimitReached,
    FlashcardSetNotFound,
    FlashcardSetRateLimited,
    InvalidRequest,
    NotFound,
    PayloadTooLarge,
    RateLimited,
    StorageError,
    Unprocessable,
    UpstreamError,
    cards,
    concept_topic,
    create_flashcard_set,
    delete_flashcard_set,
    generation,
    import_flow,
    list_flashcard_sets,
    suggest_flashcard_set,
    update_flashcard_set,
)
from services.flashcards.cards import (  # noqa: F401  (re-export, #118)
    _FSRS_LIST_COLS,
    _LEGACY_LIST_COLS,
    _loop_order,
    _order_due_rows,
)
from services.flashcards.integrity import IntegrityRefused
from services.flashcards.context import (  # noqa: F401  (re-export, #118)
    _COURSE_DOC_COLS,
    _COURSE_DOC_LIMIT,
    _enrolled_course_by_name,
    _get_course_documents,
    _get_session_summary,
    _get_weak_concepts,
)
from services.flashcards.import_flow import (  # noqa: F401  (re-export, #118)
    MAX_UPLOAD_BYTES as _MAX_UPLOAD_BYTES,
)

router = APIRouter()


# ── Request / Response models ──────────────────────────────────────────────────

class GenerateFlashcardsBody(BaseModel):
    user_id: Id
    topic: str = Field(max_length=500)
    count: int = Field(default=5, ge=1, le=abuse_limits.FLASHCARD_GENERATE_MAX_COUNT)
    session_id: Id | None = None
    # Optional term label (#141): grounds generation in the SELECTED term's
    # course documents instead of always the current term's.
    semester: ShortText | None = None
    # The selected course's abstract id (#829). When present it scopes the
    # grounding documents directly; `topic` is then only the prompt's label.
    course_id: Id | None = None


class FlashcardRatingBody(BaseModel):
    user_id: Id
    card_id: Id
    # 1 = forgot, 2 = hard, 3 = easy: FSRS Again/Hard/Good via
    # learning.params.FLASHCARD_RATING_TO_FSRS (PKG-11); any other value is a 422.
    rating: int


#: Cards one import may carry (a large Anki deck is a few thousand).
IMPORT_CARDS_MAX = 10_000


class CardInput(BaseModel):
    front: LongText
    back: LongText


class ImportParseBody(BaseModel):
    user_id: Id
    source: Literal["anki", "xlsx", "url", "ocr"]
    # base64 for files (import_flow caps the decoded file at 5 MB, ~6.7 M
    # base64 characters), plain text for url; filename in options
    payload: str = Field(max_length=8_000_000)
    options: dict = {}


class ImportCommitBody(BaseModel):
    user_id: Id
    course_id: Id | None = None
    topic: str = Field(max_length=500)
    cards: list[CardInput] = Field(max_length=IMPORT_CARDS_MAX)
    dedup: bool = True


class ImportGenerateBody(BaseModel):
    user_id: Id
    source: Literal["paste", "library_doc"]
    text: str | None = Field(default=None, max_length=200_000)
    document_id: Id | None = None
    count: int = Field(default=25, ge=1, le=abuse_limits.FLASHCARD_IMPORT_MAX_COUNT)
    difficulty: Literal["recall", "application", "conceptual"] = "recall"


class ImportCleanupBody(BaseModel):
    user_id: Id
    cards: list[CardInput] = Field(max_length=IMPORT_CARDS_MAX)


class ImportClozeBody(BaseModel):
    user_id: Id
    paragraph: LongText


class FlashcardSetCreateBody(BaseModel):
    """A saved set. Field rules (lengths, de-duplication, the option keys) are
    `services/flashcards/sets.py`'s, answered as 422 with a readable detail."""
    user_id: Id
    # The service's own rules (NAME_MAX, CONCEPTS_MAX...) answer the readable
    # 422s; these bounds only cap what is parsed at all.
    name: ShortText
    course_id: Id
    concepts: list[ShortText] = Field(max_length=1000)
    options: dict | None = None
    exam_id: Id | None = None


class FlashcardSetPatchBody(BaseModel):
    """Only the fields SENT change; `exam_id: null` clears the exam."""
    user_id: Id
    name: ShortText | None = None
    concepts: list[ShortText] | None = Field(default=None, max_length=1000)
    options: dict | None = None
    exam_id: Id | None = None


class FlashcardSetSuggestBody(BaseModel):
    user_id: Id
    description: str = Field(max_length=2000)  # the service answers past DESCRIPTION_MAX
    course_id: Id | None = None


# ── Domain errors → HTTP ───────────────────────────────────────────────────────

_ERROR_STATUS = {
    InvalidRequest: 400, NotFound: 404, PayloadTooLarge: 413, Unprocessable: 422,
    RateLimited: 429, StorageError: 500, UpstreamError: 502,
    FlashcardSetInvalid: 422, FlashcardSetNotFound: 404,
    FlashcardSetLimitReached: 409, FlashcardSetRateLimited: 429,
    IntegrityRefused: 409,  # spec §13 A125 (services/flashcards/integrity.py)
}


def llm_http_error(exc: BaseException) -> HTTPException:
    """Kept for importers of the pre-split route (#118): the HTTP error a
    failed generation is answered with, now built from
    ``generation.generation_failed`` (the 502, or the budget refusal in
    ``exc`` re-raised as itself)."""
    err = generation.generation_failed(exc)
    return HTTPException(status_code=_ERROR_STATUS[UpstreamError], detail=err.detail)


@contextmanager
def _flashcard_errors():
    """Map a ``services.flashcards`` domain error to its HTTP status, same
    detail (plus ``Retry-After`` when the error names a wait)."""
    try:
        yield
    except FlashcardError as e:
        retry = getattr(e, "retry_after", None)
        raise HTTPException(
            status_code=domain_status(e, _ERROR_STATUS),
            detail=e.detail,
            headers={"Retry-After": str(retry)} if retry is not None else None,
        ) from e


def _rate_limited_import(fn, /, *args, **kwargs):
    """Call one of the rate-limited import functions. A refusal by the import
    limiter is answered as these routes always have: 429 with the bare
    ``{detail}`` body and ``Retry-After``."""
    with _flashcard_errors():
        try:
            return fn(*args, **kwargs)
        except RateLimited as e:
            return JSONResponse(
                status_code=429,
                content={"detail": e.detail},
                headers={"Retry-After": str(e.retry_after)},
            )


def _card_inputs(items: list[CardInput]) -> list[dict]:
    return [{"front": c.front, "back": c.back} for c in items]


# ── Cards ──────────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate(body: GenerateFlashcardsBody, request: Request):
    """
    Generate AI flashcards grounded in the student's actual course material.
    Pulls library documents + weak concepts from the knowledge graph automatically.
    """
    # docs/safety/crisis-support.md: first, before the budget; no cards are made...
    if crisis := await crisis_support.screen_async(request, body.user_id, "flashcard_generate", body.topic):
        # ...unless the topic is one of the student's own graph concepts (course
        # material, not typed): the cards are made with the card beside them
        if await run_in_threadpool(
            concept_topic.topic_is_graph_concept, body.user_id, body.topic, body.course_id,
        ):
            return await crisis_support.alongside(
                crisis_support.ContentScreen(request, crisis), _generate(body, request),
            )
        return crisis_support.json_body(crisis, flashcards=[])
    return await _generate(body, request)


async def _generate(body: GenerateFlashcardsBody, request: Request) -> dict:
    """`generate`'s own work: the guard, then the generation (both blocking,
    so off the event loop)."""
    await run_in_threadpool(require_self, body.user_id, request)
    await aenforce_abuse_limit(abuse_limits.FLASHCARD_GENERATE, body.user_id)

    def run() -> dict:
        with _flashcard_errors():
            return generation.generate(
                body.user_id, topic=body.topic, count=body.count, session_id=body.session_id,
                semester=body.semester, course_id=body.course_id,
                loop_on=learning_loop_for_request(body.user_id),  # spec §13 A125
            )

    return await run_in_threadpool(run)


@router.get("/user/{user_id}")
def get_flashcards(
    user_id: str,
    request: Request,
    topic: str | None = None,
    semester: str | None = None,
    due_only: bool = False,
):
    require_self(user_id, request)
    with _flashcard_errors():
        return cards.get_flashcards(user_id, topic, semester, due_only=due_only)


@router.post("/rate")
def rate_card(body: FlashcardRatingBody, request: Request):
    require_self(body.user_id, request)
    with _flashcard_errors():
        return {"ok": True, **cards.rate_card(body.user_id, body.card_id, body.rating)}


@router.delete("/{card_id}")
def delete_card(card_id: str, user_id: str, request: Request):
    require_self(user_id, request)
    with _flashcard_errors():
        cards.delete_card(user_id, card_id)
    return {"ok": True}


# ── Saved sets ─────────────────────────────────────────────────────────────────
#
# A set is a name, a course, concept names and options; it owns no cards. The
# logic is `services/flashcards/sets.py` (and `suggest.py`). `/sets/...` is two
# segments, so it never collides with `DELETE /{card_id}` above.

@router.get("/sets/{user_id}")
def get_flashcard_sets(user_id: str, request: Request, course_id: str | None = None):
    require_self(user_id, request)
    return {"sets": list_flashcard_sets(user_id, course_id)}


@router.post("/sets")
def create_set(body: FlashcardSetCreateBody, request: Request):
    require_self(body.user_id, request)
    with _flashcard_errors():
        return {"set": create_flashcard_set(
            body.user_id, name=body.name, course_id=body.course_id,
            concepts=body.concepts, options=body.options, exam_id=body.exam_id,
        )}


@router.post("/sets/suggest")
async def suggest_set(body: FlashcardSetSuggestBody, request: Request):
    """Concepts a described set should hold (a suggestion; nothing is saved)."""
    # docs/safety/crisis-support.md: first, before the suggest limiter and the budget
    if crisis := await crisis_support.screen_async(
        request, body.user_id, "flashcard_set_suggest", body.description
    ):
        return crisis_support.json_body(crisis, name="", concepts=[], considered=0, backend="none")
    # The guard can read the DB: off the event loop in an async handler (#756).
    await run_in_threadpool(require_self, body.user_id, request)
    with _flashcard_errors():
        return await suggest_flashcard_set(body.user_id, body.description, body.course_id)


@router.patch("/sets/{set_id}")
def update_set(set_id: str, body: FlashcardSetPatchBody, request: Request):
    require_self(body.user_id, request)
    changes = body.model_dump(exclude_unset=True, exclude={"user_id"})
    with _flashcard_errors():
        return {"set": update_flashcard_set(body.user_id, set_id, changes)}


@router.delete("/sets/{set_id}")
def delete_set(set_id: str, user_id: str, request: Request):
    require_self(user_id, request)
    with _flashcard_errors():
        delete_flashcard_set(user_id, set_id)
    return {"deleted": True}


# ── Import routes ──────────────────────────────────────────────────────────────

@router.post("/import/commit")
def import_commit(body: ImportCommitBody, request: Request):
    require_self(body.user_id, request)
    with _flashcard_errors():
        return import_flow.import_commit(
            body.user_id, course_id=body.course_id, topic=body.topic,
            cards=_card_inputs(body.cards), dedup=body.dedup,
        )


@router.post("/import/parse")
def import_parse(body: ImportParseBody, request: Request):
    require_self(body.user_id, request)
    return _rate_limited_import(
        import_flow.import_parse, body.user_id, body.source, body.payload, body.options,
        loop_on=learning_loop_for_request(body.user_id),
    )


@router.post("/import/generate")
def import_generate(body: ImportGenerateBody, request: Request):
    # docs/safety/crisis-support.md: first, before the import limiter and the budget
    # (pasted text only: a library document is uploaded course material)
    if body.source == "paste" and (crisis := crisis_support.screen(
        request, body.user_id, "flashcard_import_paste", body.text
    )):
        return crisis_support.json_body(crisis, cards=[])
    require_self(body.user_id, request)
    return _rate_limited_import(
        import_flow.import_generate, body.user_id, source=body.source, text=body.text,
        document_id=body.document_id, count=body.count, difficulty=body.difficulty,
        loop_on=learning_loop_for_request(body.user_id),
    )


@router.post("/import/cleanup")
def import_cleanup(body: ImportCleanupBody, request: Request):
    # Not crisis-screened (docs/safety/crisis-support.md, "Checked and not
    # covered"): the cards are an imported deck, someone else's material.
    require_self(body.user_id, request)
    return _rate_limited_import(
        import_flow.import_cleanup, body.user_id, _card_inputs(body.cards),
        loop_on=learning_loop_for_request(body.user_id),
    )


@router.post("/import/cloze")
def import_cloze(body: ImportClozeBody, request: Request):
    # docs/safety/crisis-support.md: first, before the import limiter and the budget
    if crisis := crisis_support.screen(request, body.user_id, "flashcard_import_cloze", body.paragraph):
        return crisis_support.json_body(crisis, cards=[])
    require_self(body.user_id, request)
    return _rate_limited_import(
        import_flow.import_cloze, body.user_id, body.paragraph,
        loop_on=learning_loop_for_request(body.user_id),
    )
