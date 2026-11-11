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
    # the learning loop's KPI report, split out of the route (spec §13 A149)
    "services.admin.analytics.learning_loop",
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
    # GET /plan's body (the learning loop's concept plan, spec §13 A143/A149)
    "services.quiz.plan",
)


def patch_quiz(name, new=DEFAULT, **kwargs):
    """``patch("routes.quiz.<name>", ...)`` across routes/quiz.py and the
    modules split out of it."""
    return patch_in(QUIZ_MODULES, name, new, **kwargs)


def setattr_quiz(monkeypatch, name, value):
    """``monkeypatch.setattr(routes.quiz, name, value)`` across the split."""
    setattr_in(monkeypatch, QUIZ_MODULES, name, value)


# ── tutor (learn) ─────────────────────────────────────────────────────────────

# services/chat_stream.py, tutor_router.py and tutor_sessions.py stayed flat
# beside the package and are deliberately absent: see the module docstring.
# (tutor_sessions' own `table` follows the tutor modules' through the autouse
# `_tutor_session_reads_follow_learn_table` fixture in conftest.py, as it
# followed routes.learn's before the split.)
TUTOR_MODULES = (
    "routes.learn",
    "services.tutor.run",
    "services.tutor.course",
    "services.tutor.messages",
    "services.tutor.pending",
    "services.tutor.turns",
    "services.tutor.streams",
    "services.tutor.sessions",
)


def patch_tutor(name, new=DEFAULT, **kwargs):
    """``patch("routes.learn.<name>", ...)`` across routes/learn.py and the
    services/tutor/ modules split out of it."""
    return patch_in(TUTOR_MODULES, name, new, **kwargs)


def setattr_tutor(monkeypatch, name, value):
    """``monkeypatch.setattr(routes.learn, name, value)`` across the split."""
    setattr_in(monkeypatch, TUTOR_MODULES, name, value)


# ── learning loop ─────────────────────────────────────────────────────────────

# services/loop/posed.py (the A93/A101 scan set, formerly services/loop_posed.py)
# existed before the split and is deliberately absent: see the module docstring.
# So are ``errors`` (the package's one fastapi import) and the package
# ``__init__`` (its lazy exports read the modules below at call time).
LOOP_MODULES = (
    "routes.learn_loop",
    "services.loop.constants",
    "services.loop.flags",
    "services.loop.state",
    "services.loop.history",
    "services.loop.learner",
    "services.loop.context",
    "services.loop.continuation",
    "services.loop.served",
    "services.loop.reveals",
    "services.loop.guard",
    "services.loop.planning",
    "services.loop.cursor",
    "services.loop.pose",
    "services.loop.practice",
    "services.loop.turn",
    "services.loop.opener",
    "services.loop.runner",
    "services.loop.sessions",
    "services.loop.claims",
    "services.loop.checkpoint",
    "services.loop.grading",
    "services.loop.teach",
)


class _LoopPatch:
    """What ``patch_loop`` returns: like ``mock.patch``'s patcher, it can be
    entered again (a fresh patch each time) and started / stopped."""

    def __init__(self, factory):
        self._factory, self._active = factory, []

    def __enter__(self):
        cm = self._factory()
        value = cm.__enter__()
        self._active.append(cm)
        return value

    def __exit__(self, *exc):
        return self._active.pop().__exit__(*exc)

    def start(self):
        return self.__enter__()

    def stop(self):
        return self.__exit__(None, None, None)


def _loop_patch(name, new, kwargs):
    head, dot, rest = name.partition(".")
    if not dot:
        return patch_in(LOOP_MODULES, name, new, **kwargs)
    mods = [importlib.import_module(m) for m in LOOP_MODULES]
    owner = next((getattr(m, head) for m in mods if hasattr(m, head)), None)
    if owner is None:
        raise AttributeError(f"none of {LOOP_MODULES} has {head!r}")
    *path, attr = rest.split(".")
    for part in path:
        owner = getattr(owner, part)
    return patch.object(owner, attr, new, **kwargs)


def patch_loop(name, new=DEFAULT, **kwargs):
    """``patch("routes.learn_loop.<name>", ...)`` across routes/learn_loop.py
    and the services/loop/ modules split out of it. A dotted name
    (``"policy.model_tier"``) patches the attribute of the object the loop
    names (there: ``learning.policy``), as the dotted route path did."""
    return _LoopPatch(lambda: _loop_patch(name, new, kwargs))


def setattr_loop(monkeypatch, name, value):
    """``monkeypatch.setattr(routes.learn_loop, name, value)`` across the split."""
    setattr_in(monkeypatch, LOOP_MODULES, name, value)
