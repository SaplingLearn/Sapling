"""
backend/services/gradebook_service.py — alias shim (#118).

The grade math moved to ``services/gradebook/grades.py``. This path stays so
existing imports (``from services import gradebook_service``) and patch
targets (``patch("services.gradebook_service.<name>")``) keep working: the old
name is bound to the SAME module object, so a patch through either name
reaches the code that runs. New code imports ``services.gradebook.grades``.
"""
import sys

from services.gradebook import grades as _grades

sys.modules[__name__] = _grades
