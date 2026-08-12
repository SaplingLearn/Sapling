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
    QUIZ_NOT_AUTHORIZED = "QUIZ_NOT_AUTHORIZED"
    QUIZ_GENERATION_FAILED = "QUIZ_GENERATION_FAILED"
    QUIZ_INTERNAL_ERROR = "QUIZ_INTERNAL_ERROR"


# Fallback code when an ordinary HTTPException (no explicit code) escapes a
# quiz route — e.g. require_self's 401/403.
_STATUS_FALLBACK: dict[int, QuizErrorCode] = {
    401: QuizErrorCode.QUIZ_NOT_AUTHORIZED,
    403: QuizErrorCode.QUIZ_NOT_AUTHORIZED,
    404: QuizErrorCode.QUIZ_ATTEMPT_NOT_FOUND,
    409: QuizErrorCode.QUIZ_ATTEMPT_ALREADY_COMPLETED,
    422: QuizErrorCode.QUIZ_VALIDATION_ERROR,
    502: QuizErrorCode.QUIZ_GENERATION_FAILED,
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
    resolved_code = code or _STATUS_FALLBACK.get(
        status_code,
        QuizErrorCode.QUIZ_INTERNAL_ERROR,
    )
    resolved_message = message or (
        legacy_detail
        if isinstance(legacy_detail, str)
        else "Something went wrong with this quiz request."
    )
    error: dict = {
        "code": resolved_code.value,
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
