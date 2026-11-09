"""Patch ``table`` across a split domain at once (#118).

A route split moves data access out of ``routes/<x>.py`` into
``services/<domain>/<topic>.py``, so one handler can now reach ``table()``
through several modules. A test that used to ``patch("routes.x.table", ...)``
patches every module the request touches with ONE mock instead, so its
``.select`` setups and assertions see every call, wherever it is made.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, patch

PROFILE_TABLE_MODULES = (
    "routes.profile",
    "services.profile.account",
    "services.profile.achievements",
    "services.profile.cosmetics",
    "services.profile.public",
    "services.profile.users",
)


@contextmanager
def patch_table(modules, new=None, **kwargs):
    """Patch ``<module>.table`` in each of ``modules`` with one mock.

    ``new`` is used as-is when given; otherwise a ``MagicMock(**kwargs)``
    (the mock ``patch("...table", **kwargs)`` would have made). Yields it.
    """
    mock = new if new is not None else MagicMock(**kwargs)
    with ExitStack() as stack:
        for module in modules:
            stack.enter_context(patch(f"{module}.table", mock))
        yield mock


def patch_profile_table(new=None, **kwargs):
    """:func:`patch_table` over the profile route + ``services/profile/``."""
    return patch_table(PROFILE_TABLE_MODULES, new, **kwargs)


# ── auth (#118) ───────────────────────────────────────────────────────────────

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
