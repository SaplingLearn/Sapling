"""Study guides domain (#118): a student's durable guides, written as prose
with typed blocks. ``routes/study_guide.py`` is the HTTP layer over this
package; the shapes live in ``models/study_guide.py`` and the plan in
``docs/design/study-guide-redesign.md``."""
from services.study_guides.errors import (
    GuideBusy,
    GuideGenerationFailed,
    GuideInvalid,
    GuideNotFound,
    GuideRateLimited,
    StudyGuideError,
)
from services.study_guides.legacy import content_from_topics
from services.study_guides.store import (
    CLAIM_STALE_AFTER,
    GuideRow,
    aclaim_generation,
    ainsert_guide,
    alist_guides,
    aload_guide,
    apatch_state,
    arecord_answer,
    arelease_generation,
    asave_content,
    atouch_generation,
)

__all__ = [
    "CLAIM_STALE_AFTER",
    "GuideBusy",
    "GuideGenerationFailed",
    "GuideInvalid",
    "GuideNotFound",
    "GuideRateLimited",
    "GuideRow",
    "StudyGuideError",
    "aclaim_generation",
    "ainsert_guide",
    "alist_guides",
    "aload_guide",
    "apatch_state",
    "arecord_answer",
    "arelease_generation",
    "asave_content",
    "atouch_generation",
    "content_from_topics",
]
