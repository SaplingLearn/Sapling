"""The #118 flat-module shims are aliases of the moved module, not copies.

Each old path binds ``sys.modules[<old>]`` to the module it moved into, so an
import through either name is the SAME object and a ``patch("<old>.<name>")``
reaches the code that runs. A name re-export (``from new import a, b``) would
silently stop intercepting: the patch lands on the shim's copy of the name.
"""
from __future__ import annotations

import importlib

import pytest

SHIMS = {
    "services.quiz_algebra": "services.quiz.algebra",
    "services.quiz_config": "services.quiz.config",
    "services.quiz_context_service": "services.quiz.context",
    "services.quiz_distractors": "services.quiz.distractors",
    "services.quiz_errors": "services.quiz.errors",
    "services.quiz_grading": "services.quiz.grading",
    "services.quiz_identity": "services.quiz.identity",
    "services.quiz_repetition": "services.quiz.repetition",
    "services.quiz_reserve": "services.quiz.reserve",
    "services.quiz_signals": "services.quiz.signals",
    "services.gradescope_jobs": "services.gradescope.jobs",
    "services.gradescope_service": "services.gradescope.client",
    "services.flashcard_import_service": "services.flashcards.importing",
    "services.gradebook_service": "services.gradebook.grades",
    "services.admin_db_scope": "services.admin.analytics.db_scope",
}


@pytest.mark.parametrize("old,new", sorted(SHIMS.items()))
def test_old_path_is_the_moved_module(old, new):
    assert importlib.import_module(old) is importlib.import_module(new)
