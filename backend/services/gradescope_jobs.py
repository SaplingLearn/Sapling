"""
backend/services/gradescope_jobs.py — re-export shim (#118).

The queued Gradescope sync moved to ``services/gradescope/jobs.py``; its
outcome -> HTTP mapping (``response_for_outcome``, ``sync_via_queue``,
``status_response``) moved to ``routes/gradescope.py``. This path stays so
existing imports, ``worker/__main__.py``'s handler list and patch targets
(``patch.object(gradescope_jobs, ...)``) keep working: the old name is bound to
the SAME module object, so a patch through either name reaches the code that
runs. New code imports ``services.gradescope.jobs``.
"""
import sys

from services.gradescope import jobs as _jobs

sys.modules[__name__] = _jobs
