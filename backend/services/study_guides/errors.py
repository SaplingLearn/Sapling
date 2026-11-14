"""Domain errors the study-guides package raises instead of ``HTTPException``
(no ``fastapi`` in a domain package, #118). ``routes/study_guide.py`` answers
each with its ``status_code`` and ``detail``."""
from __future__ import annotations


class StudyGuideError(Exception):
    """Base class: ``detail`` is the client-facing message."""

    status_code = 400

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class GuideInvalid(StudyGuideError):
    """A choice in the request does not hold up (422): a material that is not
    in the class, a section id the guide does not have."""

    status_code = 422


class GuideNotFound(StudyGuideError):
    """The guide, its class, its exam or one of its blocks is missing or is not
    the caller's (404: the same answer for "not there" and "not yours")."""

    status_code = 404


class GuideBusy(StudyGuideError):
    """Another request is writing this guide right now (409)."""

    status_code = 409


class GuideRateLimited(StudyGuideError):
    """Too many generations in the window (429)."""

    status_code = 429


class GuideGenerationFailed(StudyGuideError):
    """The model could not write the guide, or a part of it (502)."""

    status_code = 502
