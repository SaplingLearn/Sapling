"""Patch one name in every module a split route now spreads it over (#118).

A Phase-4 split moves route code into ``services/<domain>/``. A test that
patched ``routes.<x>.table`` (or ``_persist_document``, …) then has to patch
the same name wherever the moved code looks it up, or it silently stops
intercepting. ``patch_in`` applies ONE mock to every listed module that has
the name, and yields it, so ``with patch_in(MODULES, "table") as t:`` reads
like the single ``patch(...)`` it replaces.

(Same helper as tests/split_patches.py on the admin/social split branch; the
two are reconciled when the splits land.)
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
