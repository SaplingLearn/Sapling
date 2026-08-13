"""Stable machine-readable error contract for the quiz routes (#540 A3).

Every 4xx/5xx under /api/quiz/* returns:

    {
      "error": {
        "code": "<QuizErrorCode>",   # stable machine string for the client
        "message": "<sentence a student can read>",
        "detail": ...,               # optional machine detail (e.g. Pydantic errors)
        "request_id": "<rid>"        # correlation for support; never inside message
      },
      "detail": ...,                 # legacy key — current QuizPanel reads data?.detail
      "request_id": "<rid>"
    }

The envelope is applied by main.py's exception handlers, scoped to quiz
paths only (`is_quiz_path`), so every raise inside the routes — including
shared dependencies like require_self — comes out enveloped without each
raise site needing to know about the format. Raise `QuizAPIError` to attach
a precise code; plain HTTPExceptions fall back to a status-derived code.

The frontend maps codes from this one enum; add codes here, never inline.
"""

from enum import Enum

from fastapi import HTTPException


class QuizErrorCode(str, Enum):
    QUIZ_DIFFICULTY_INVALID = "QUIZ_DIFFICULTY_INVALID"
    QUIZ_COUNT_OUT_OF_RANGE = "QUIZ_COUNT_OUT_OF_RANGE"
    QUIZ_VALIDATION_ERROR = "QUIZ_VALIDATION_ERROR"
    QUIZ_CONCEPT_NOT_FOUND = "QUIZ_CONCEPT_NOT_FOUND"
    QUIZ_ATTEMPT_NOT_FOUND = "QUIZ_ATTEMPT_NOT_FOUND"
    QUIZ_ATTEMPT_ALREADY_COMPLETED = "QUIZ_ATTEMPT_ALREADY_COMPLETED"
    # #542 D2: the attempt was swept as abandoned (past the TTL with no
    # activity). Distinct from "already completed" — the student never
    # finished it, and the client should offer a fresh quiz, not a resume.
    QUIZ_ATTEMPT_ABANDONED = "QUIZ_ATTEMPT_ABANDONED"
    # #542 review: the stored questions aren't in a shape we can safely
    # show without the answer key, so this attempt cannot be resumed.
    QUIZ_ATTEMPT_NOT_RESUMABLE = "QUIZ_ATTEMPT_NOT_RESUMABLE"
    # #541 C1: the answer endpoint got an index that doesn't exist on this
    # attempt (question_index past the quiz, selected_index past the options).
    QUIZ_QUESTION_INVALID = "QUIZ_QUESTION_INVALID"
    QUIZ_NOT_AUTHORIZED = "QUIZ_NOT_AUTHORIZED"
    QUIZ_GENERATION_FAILED = "QUIZ_GENERATION_FAILED"
    QUIZ_INTERNAL_ERROR = "QUIZ_INTERNAL_ERROR"
    # Uncoded HTTP errors that aren't one of the semantic states above —
    # router 404s/405s on version-skewed clients, library-raised
    # HTTPExceptions, anything without an explicit QuizErrorCode. A client
    # must never mistake these for a domain state like "attempt not found".
    QUIZ_HTTP_ERROR = "QUIZ_HTTP_ERROR"


# Fallback code when an ordinary HTTPException (no explicit code) escapes a
# quiz route. Deliberately narrow: only statuses whose meaning is unambiguous
# regardless of which code path raised them (auth guards, Pydantic). Domain
# states (404 concept/attempt, 409 replay, 502 generation) are NOT here —
# their raise sites all carry explicit codes, and a router-level 404/405 must
# come out as the generic QUIZ_HTTP_ERROR, not impersonate a domain state.
_STATUS_FALLBACK: dict[int, QuizErrorCode] = {
    401: QuizErrorCode.QUIZ_NOT_AUTHORIZED,
    403: QuizErrorCode.QUIZ_NOT_AUTHORIZED,
    422: QuizErrorCode.QUIZ_VALIDATION_ERROR,
}


class QuizAPIError(HTTPException):
    """HTTPException carrying a stable code + student-readable message.

    `detail` stays the legacy-compatible string (the message), so clients
    reading `data?.detail` see the same sentence as `error.message`.
    """

    def __init__(
        self,
        status_code: int,
        code: QuizErrorCode,
        message: str,
        machine_detail=None,
    ):
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.machine_detail = machine_detail


def is_quiz_path(path: str) -> bool:
    # Exact prefix match: '/api/quizzes' or '/api/quiz-x' must NOT envelope.
    return path == "/api/quiz" or path.startswith("/api/quiz/")


def quiz_error_body(
    status_code: int,
    legacy_detail,
    request_id: str | None,
    code: QuizErrorCode | None = None,
    message: str | None = None,
    machine_detail=None,
) -> dict:
    """Build the enveloped payload; keeps the legacy top-level keys."""
    if not isinstance(code, QuizErrorCode):
        # The handler duck-types `code` off the exception; a library
        # exception could carry an int or arbitrary string there. Treat
        # anything that isn't ours as absent — never crash the handler.
        code = None
    if code is None:
        if status_code >= 500:
            code = QuizErrorCode.QUIZ_INTERNAL_ERROR
        else:
            code = _STATUS_FALLBACK.get(status_code, QuizErrorCode.QUIZ_HTTP_ERROR)
    resolved_message = message or (
        legacy_detail
        if isinstance(legacy_detail, str)
        else "Something went wrong with this quiz request."
    )
    error: dict = {
        "code": code.value,
        "message": resolved_message,
        "request_id": request_id,
    }
    if machine_detail is not None:
        error["detail"] = machine_detail
    return {
        "error": error,
        "detail": legacy_detail,
        "request_id": request_id,
    }


def error_content(
    path: str,
    status_code: int,
    legacy_detail,
    request_id: str | None,
    code: QuizErrorCode | None = None,
    message: str | None = None,
    machine_detail=None,
) -> dict:
    """The one branch point between the quiz envelope and the legacy
    ``{detail, request_id}`` shape — main.py's three exception handlers all
    call this so the contract lives in exactly one place."""
    if is_quiz_path(path):
        return quiz_error_body(
            status_code, legacy_detail, request_id,
            code=code, message=message, machine_detail=machine_detail,
        )
    return {"detail": legacy_detail, "request_id": request_id}


def validation_error_code(errors: list[dict]) -> tuple["QuizErrorCode", str | None]:
    """Pick the (code, message) for a quiz-route RequestValidationError.

    QUIZ_COUNT_OUT_OF_RANGE only for an actual bounds violation on
    num_questions — a type error ("five", 5.5) on the same field is NOT
    out-of-range, and mislabelling it would send a clamping client into a
    retry loop on the identical 422. The message is filled by the caller
    (it owns the min/max constants).
    """
    for e in errors:
        if "num_questions" in {str(part) for part in e.get("loc", ())}:
            etype = str(e.get("type", ""))
            if etype.startswith(("greater_than", "less_than")):
                return QuizErrorCode.QUIZ_COUNT_OUT_OF_RANGE, None
    return (
        QuizErrorCode.QUIZ_VALIDATION_ERROR,
        "That quiz request wasn't valid — please try again.",
    )
