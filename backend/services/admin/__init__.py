"""
backend/services/admin/ — the admin domain (#118).

One module per admin surface; ``routes/admin.py`` keeps the auth checks
(``require_admin`` / ``get_session_user_id``) and calls these:

- ``roles``: roles, assign/revoke, role↔cosmetic links.
- ``achievements``: catalog, icon, grant, triggers, achievement↔cosmetic links.
- ``cosmetics``: cosmetic catalog.
- ``xp_rules``: XP rule amounts / enabled.
- ``users``: remove a user's access.
- ``allowlist``: the waitlist / allowlist (approve, bulk approve, revoke).
- ``feedback``: feedback + issue reports (decrypted, #520).
- ``audit``: the admin audit log.
- ``overview``: ``/analytics/overview`` totals and series.
- ``errors``: domain errors the route maps to HTTP statuses.
"""
from __future__ import annotations

from services.admin import (  # noqa: F401
    achievements,
    allowlist,
    audit,
    cosmetics,
    errors,
    feedback,
    overview,
    roles,
    users,
    xp_rules,
)
from services.admin.errors import (  # noqa: F401
    AdminError,
    Conflict,
    InvalidRequest,
    NotFound,
    Unprocessable,
)

__all__ = [
    "AdminError",
    "Conflict",
    "InvalidRequest",
    "NotFound",
    "Unprocessable",
    "achievements",
    "allowlist",
    "audit",
    "cosmetics",
    "errors",
    "feedback",
    "overview",
    "roles",
    "users",
    "xp_rules",
]
