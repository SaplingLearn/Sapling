"""Patch one name in every module a split route now spreads it over (#118).

A Phase-4 split moves route code into ``services/<domain>/``. A test that
patched ``routes.<x>.table`` (or ``log_admin_action``, …) then has to patch
the same name wherever the moved code looks it up, or it silently stops
intercepting. ``patch_in`` applies ONE mock to every listed module that has
the name, and yields it, so ``with patch_in(MODULES, "table") as t:`` reads
like the single ``patch(...)`` it replaces.
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
    for m in modules:
        mod = importlib.import_module(m)
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, value)


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
