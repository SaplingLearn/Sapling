"""Patch one name in every module a split route now spreads it over (#118).

A Phase-4 split moves route code into ``services/<domain>/``. A test that
patched ``routes.<x>.table`` (or ``log_admin_action``, ``_persist_document``,
``_quiz_via_agent``, …) then has to patch the same name wherever the moved
code LOOKS IT UP, or it silently stops intercepting. ``patch_in`` applies ONE
mock to every listed module that has the name, and yields it, so
``with patch_in(MODULES, "table") as t:`` reads like the single ``patch(...)``
it replaces; ``setattr_in`` is its ``monkeypatch`` twin.

Each split domain has a ``<DOMAIN>_MODULES`` tuple (the route plus the
modules carved out of it) and ``patch_<domain>`` / ``setattr_<domain>``
conveniences. A tuple lists only the route and what was split OUT of it: a
module that already existed before the split (e.g. ``services/quiz_*.py``)
never saw a ``routes.<x>.<name>`` patch, and must not start to now.

The one module for every split (it replaces the per-split doc_patches.py,
quiz_patches.py and route_patches.py).
"""
from __future__ import annotations

import contextlib
import importlib
from unittest.mock import DEFAULT, patch


@contextlib.contextmanager
def patch_in(modules, name, new=DEFAULT, **kwargs):
    mods = [importlib.import_module(m) for m in modules]
    present = [m for m in mods if hasattr(m, name)]
    if not present:
        raise AttributeError(f"none of {modules} has {name!r}")
    first, *rest = present
    with patch.object(first, name, new, **kwargs) as mock, contextlib.ExitStack() as stack:
        for m in rest:
            stack.enter_context(patch.object(m, name, mock))
        yield mock


def setattr_in(monkeypatch, modules, name, value):
    """``monkeypatch.setattr`` twin of ``patch_in``."""
    found = False
    for m in modules:
        mod = importlib.import_module(m)
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, value)
            found = True
    if not found:
        raise AttributeError(f"none of {modules} has {name!r}")


# ── admin ─────────────────────────────────────────────────────────────────────

ADMIN_MODULES = (
    "routes.admin",
    "services.admin.roles",
    "services.admin.achievements",
    "services.admin.cosmetics",
    "services.admin.xp_rules",
    "services.admin.users",
    "services.admin.allowlist",
    "services.admin.feedback",
    "services.admin.audit",
    "services.admin.overview",
)


def patch_admin(name, new=DEFAULT, **kwargs):
    """``patch("routes.admin.<name>", ...)`` across routes/admin.py and
    services/admin/."""
    return patch_in(ADMIN_MODULES, name, new, **kwargs)


ADMIN_ANALYTICS_MODULES = (
    "routes.admin_analytics",
    "services.admin.analytics.scan",
    "services.admin.analytics.series",
)


# ── social ────────────────────────────────────────────────────────────────────

SOCIAL_MODULES = (
    "routes.social",
    "services.social.rooms",
    "services.social.overview",
    "services.social.messages",
    "services.social.matching",
    "services.social.directory",
    "services.social.friends",
)


def patch_social(name, new=DEFAULT, **kwargs):
    """``patch("routes.social.<name>", ...)`` across routes/social.py and
    services/social/."""
    return patch_in(SOCIAL_MODULES, name, new, **kwargs)


# ── profile ───────────────────────────────────────────────────────────────────

PROFILE_TABLE_MODULES = (
    "routes.profile",
    "services.profile.account",
    "services.profile.achievements",
    "services.profile.cosmetics",
    "services.profile.public",
    "services.profile.users",
)


def patch_profile_table(new=DEFAULT, **kwargs):
    """``patch("routes.profile.table", ...)`` across routes/profile.py and
    services/profile/."""
    return patch_in(PROFILE_TABLE_MODULES, "table", new, **kwargs)


# ── auth ──────────────────────────────────────────────────────────────────────

#: Every services/auth module that reads ``table``.
AUTH_TABLE_MODULES = (
    "services.auth.accounts",
    "services.auth.signin",
    "services.auth.waitlist",
)
#: Every module that reads its own imported ``SESSION_SECRET`` copy.
AUTH_SECRET_MODULES = (
    "routes.auth",
    "services.auth.oauth_state",
    "services.auth.pending",
)


def set_auth_table(monkeypatch, value) -> None:
    """``monkeypatch`` ``table`` across services/auth (was ``routes.auth.table``)."""
    for module in AUTH_TABLE_MODULES:
        monkeypatch.setattr(f"{module}.table", value)


def set_auth_session_secret(monkeypatch, value) -> None:
    """``monkeypatch`` the SESSION_SECRET the sign-in flow reads, wherever it
    reads it (was ``routes.auth.SESSION_SECRET`` alone)."""
    for module in AUTH_SECRET_MODULES:
        monkeypatch.setattr(f"{module}.SESSION_SECRET", value)


# ── gradescope ────────────────────────────────────────────────────────────────

GRADESCOPE_MODULES = (
    "routes.gradescope",
    "services.gradescope.credentials",
    "services.gradescope.links",
    "services.gradescope.sync",
)


def patch_gradescope(name, new=DEFAULT, **kwargs):
    """``patch("routes.gradescope.<name>", ...)`` across routes/gradescope.py
    and services/gradescope/ (credentials, links, sync)."""
    return patch_in(GRADESCOPE_MODULES, name, new, **kwargs)


# ── documents ─────────────────────────────────────────────────────────────────

DOCUMENTS_MODULES = (
    "routes.documents",
    "services.documents.upload",
    "services.documents.persistence",
    "services.documents.post_roll",
    "services.documents.library",
    "services.documents.scan",
    "services.documents.stream",
)


def patch_documents(name, new=DEFAULT, **kwargs):
    """``patch("routes.documents.<name>", ...)`` across routes/documents.py and
    services/documents/."""
    return patch_in(DOCUMENTS_MODULES, name, new, **kwargs)


# ── quiz ──────────────────────────────────────────────────────────────────────

# The modules that were already ``services/quiz_*.py`` (``signals``,
# ``reserve``, …) are deliberately absent: see the module docstring.
QUIZ_MODULES = (
    "routes.quiz",
    "services.quiz.limits",
    "services.quiz.wire",
    "services.quiz.attempts",
    "services.quiz.history",
    "services.quiz.grounding",
    "services.quiz.practice",
    "services.quiz.generation",
    "services.quiz.submission",
)


def patch_quiz(name, new=DEFAULT, **kwargs):
    """``patch("routes.quiz.<name>", ...)`` across routes/quiz.py and the
    modules split out of it."""
    return patch_in(QUIZ_MODULES, name, new, **kwargs)


def setattr_quiz(monkeypatch, name, value):
    """``monkeypatch.setattr(routes.quiz, name, value)`` across the split."""
    setattr_in(monkeypatch, QUIZ_MODULES, name, value)
