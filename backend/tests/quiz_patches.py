"""Patch one name everywhere the #118 quiz split spreads its lookups.

``routes/quiz.py`` moved into ``services/quiz/``. A test that patched
``routes.quiz.table`` (or ``_quiz_via_agent``, ``apply_graph_update``, …) now
has to patch the name in the module that LOOKS IT UP, or it silently stops
intercepting. ``patch_quiz(name, ...)`` applies ONE mock to every module below
that has the name and yields it, so ``with patch_quiz("table", ...) as t:``
reads like the single ``patch("routes.quiz.table", ...)`` it replaces.

Only the route and the modules carved OUT of it are listed. The modules that
were already ``services/quiz_*.py`` (``signals``, ``reserve``, …) are not:
a ``routes.quiz.table`` patch never reached them before the split, and it must
not start to now.

Same shape as B1's ``tests/split_patches.py`` (``patch_in`` / ``setattr_in``),
kept separate so the two splits do not collide.
"""
from __future__ import annotations

import contextlib
import importlib
from unittest.mock import DEFAULT, patch

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


def patch_quiz(name, new=DEFAULT, **kwargs):
    """``patch("routes.quiz.<name>", ...)`` across routes/quiz.py and the
    modules split out of it."""
    return patch_in(QUIZ_MODULES, name, new, **kwargs)


def setattr_quiz(monkeypatch, name, value):
    """``monkeypatch.setattr(routes.quiz, name, value)`` across the split."""
    setattr_in(monkeypatch, QUIZ_MODULES, name, value)
