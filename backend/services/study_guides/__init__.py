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

__all__ = [
    "GuideBusy",
    "GuideGenerationFailed",
    "GuideInvalid",
    "GuideNotFound",
    "GuideRateLimited",
    "StudyGuideError",
]
