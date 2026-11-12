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
from pydantic import BaseModel

from routes._errors import domain_status
from services.auth_guard import require_self
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
    create_flashcard_set,
    delete_flashcard_set,
    generation,
    import_flow,
    list_flashcard_sets,
    suggest_flashcard_set,
    update_flashcard_set,
)
from services.flashcards.context import (  # noqa: F401  (re-export, #118)
    _COURSE_DOC_COLS,
    _COURSE_DOC_LIMIT,
    _enrolled_course_by_name,
    _get_course_documents,
    _get_session_summary,
    _get_weak_concepts,
)

router = APIRouter()


# ── Request / Response models ──────────────────────────────────────────────────

class GenerateFlashcardsBody(BaseModel):
    user_id: str
    topic: str
    count: int = 5
    session_id: str | None = None
    # Optional term label (#141): grounds generation in the SELECTED term's
    # course documents instead of always the current term's.
    semester: str | None = None
    # The selected course's abstract id (#829). When present it scopes the
    # grounding documents directly; `topic` is then only the prompt's label.
    course_id: str | None = None


class FlashcardRatingBody(BaseModel):
    user_id: str
    card_id: str
    rating: int  # 1 = forgot, 2 = hard, 3 = easy


class CardInput(BaseModel):
    front: str
    back: str


class ImportParseBody(BaseModel):
    user_id: str
    source: Literal["anki", "xlsx", "url", "ocr"]
    payload: str  # base64 for files, plain text for url; filename in options
    options: dict = {}


class ImportCommitBody(BaseModel):
    user_id: str
    course_id: str | None = None
    topic: str
    cards: list[CardInput]
    dedup: bool = True


class ImportGenerateBody(BaseModel):
    user_id: str
    source: Literal["paste", "library_doc"]
    text: str | None = None
    document_id: str | None = None
    count: int = 25
    difficulty: Literal["recall", "application", "conceptual"] = "recall"


class ImportCleanupBody(BaseModel):
    user_id: str
    cards: list[CardInput]


class ImportClozeBody(BaseModel):
    user_id: str
    paragraph: str


class FlashcardSetCreateBody(BaseModel):
    """A saved set. Field rules (lengths, de-duplication, the option keys) are
    `services/flashcards/sets.py`'s, answered as 422 with a readable detail."""
    user_id: str
    name: str
    course_id: str
    concepts: list[str]
    options: dict | None = None
    exam_id: str | None = None


class FlashcardSetPatchBody(BaseModel):
    """Only the fields SENT change; `exam_id: null` clears the exam."""
    user_id: str
    name: str | None = None
    concepts: list[str] | None = None
    options: dict | None = None
    exam_id: str | None = None


class FlashcardSetSuggestBody(BaseModel):
    user_id: str
    description: str
    course_id: str | None = None


# ── Domain errors → HTTP ───────────────────────────────────────────────────────

_ERROR_STATUS = {
    InvalidRequest: 400, NotFound: 404, PayloadTooLarge: 413, Unprocessable: 422,
    RateLimited: 429, StorageError: 500, UpstreamError: 502,
    FlashcardSetInvalid: 422, FlashcardSetNotFound: 404,
    FlashcardSetLimitReached: 409, FlashcardSetRateLimited: 429,
}


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
def generate(body: GenerateFlashcardsBody, request: Request):
    """
    Generate AI flashcards grounded in the student's actual course material.
    Pulls library documents + weak concepts from the knowledge graph automatically.
    """
    require_self(body.user_id, request)
    with _flashcard_errors():
        return generation.generate(
            body.user_id, topic=body.topic, count=body.count, session_id=body.session_id,
            semester=body.semester, course_id=body.course_id,
        )


@router.get("/user/{user_id}")
def get_flashcards(
    user_id: str,
    request: Request,
    topic: str | None = None,
    semester: str | None = None,
):
    require_self(user_id, request)
    with _flashcard_errors():
        return {"flashcards": cards.get_flashcards(user_id, topic, semester)}


@router.post("/rate")
def rate_card(body: FlashcardRatingBody, request: Request):
    require_self(body.user_id, request)
    with _flashcard_errors():
        cards.rate_card(body.user_id, body.card_id, body.rating)
    return {"ok": True}


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
    with _flashcard_errors():
        return import_flow.import_parse(body.source, body.payload, body.options)


@router.post("/import/generate")
def import_generate(body: ImportGenerateBody, request: Request):
    require_self(body.user_id, request)
    return _rate_limited_import(
        import_flow.import_generate, body.user_id, source=body.source, text=body.text,
        document_id=body.document_id, count=body.count, difficulty=body.difficulty,
    )


@router.post("/import/cleanup")
def import_cleanup(body: ImportCleanupBody, request: Request):
    require_self(body.user_id, request)
    return _rate_limited_import(
        import_flow.import_cleanup, body.user_id, _card_inputs(body.cards),
    )


@router.post("/import/cloze")
def import_cloze(body: ImportClozeBody, request: Request):
    require_self(body.user_id, request)
    return _rate_limited_import(import_flow.import_cloze, body.user_id, body.paragraph)
