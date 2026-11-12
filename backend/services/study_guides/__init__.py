"""Study guides domain (#118): a student's durable guides, written as prose
with typed blocks. ``routes/study_guide.py`` is the HTTP layer over the
functions exported here; the shapes live in ``models/study_guide.py`` and the
plan in ``docs/design/study-guide-redesign.md``."""
from services.study_guides.answers import aanswer_check
from services.study_guides.cards import alist_cards
from services.study_guides.create import acreate_guide
from services.study_guides.detail import aget_detail
from services.study_guides.errors import (
    GuideBusy,
    GuideGenerationFailed,
    GuideInvalid,
    GuideNotFound,
    GuideRateLimited,
    StudyGuideError,
)
from services.study_guides.legacy import content_from_topics
from services.study_guides.options import aget_options
from services.study_guides.plan import aplan
from services.study_guides.state import apatch_guide

__all__ = [
    "GuideBusy",
    "GuideGenerationFailed",
    "GuideInvalid",
    "GuideNotFound",
    "GuideRateLimited",
    "StudyGuideError",
    "aanswer_check",
    "acreate_guide",
    "aget_detail",
    "aget_options",
    "alist_cards",
    "apatch_guide",
    "aplan",
    "content_from_topics",
]
