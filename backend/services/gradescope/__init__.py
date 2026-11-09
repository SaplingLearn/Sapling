"""
backend/services/gradescope/ — the Gradescope domain (#118).

- ``client``: the scraping client over ``gradescopeapi`` + the BU SSO login;
  was ``services/gradescope_service.py`` (that path is now an alias of it).
- ``credentials``: stored credentials (save, read/decrypt, log in, record
  connection state, the /status answer).
- ``links``: (user, course, semester) -> the enrollments a link keys on, and
  the course-link reads/writes.
- ``sync``: the sync body ``_run_linked_sync`` (inline route + worker).
- ``jobs``: the queued sync (#116); was ``services/gradescope_jobs.py`` (that
  path is now an alias of it). Its outcome -> HTTP mapping lives in
  ``routes/gradescope.py``.
- ``errors``: domain errors the route maps to HTTP statuses.

Names keep their leading underscores from the route they came out of, so open
PRs against ``routes/gradescope.py`` re-apply onto the moved bodies.
"""
from __future__ import annotations

from services.gradescope import client, jobs  # noqa: F401
from services.gradescope.credentials import (
    AuthMode,
    StoredCreds,
    _establish_connection,
    _load_creds,
    _now_iso,
    _write_connection_state,
    connection_status,
    save_cookie_creds,
    save_password_creds,
)
from services.gradescope.errors import (
    AmbiguousEnrollment,
    AmbiguousLink,
    CourseNotFound,
    GradescopeCredsError,
    GradescopeLinkError,
    NoCourseLink,
)
from services.gradescope.links import (
    _all_enrollments_for,
    _enrollment_for,
    _enrollments_in,
    course_links,
    link_course,
    linked_course,
)
from services.gradescope.sync import _due_to_date_string, _run_linked_sync

__all__ = [
    "AmbiguousEnrollment",
    "AmbiguousLink",
    "AuthMode",
    "CourseNotFound",
    "GradescopeCredsError",
    "GradescopeLinkError",
    "NoCourseLink",
    "StoredCreds",
    "_all_enrollments_for",
    "_due_to_date_string",
    "_enrollment_for",
    "_enrollments_in",
    "_establish_connection",
    "_load_creds",
    "_now_iso",
    "_run_linked_sync",
    "_write_connection_state",
    "client",
    "connection_status",
    "course_links",
    "jobs",
    "link_course",
    "linked_course",
    "save_cookie_creds",
    "save_password_creds",
]
