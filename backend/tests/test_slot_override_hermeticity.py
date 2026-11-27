"""The suite never sees a shell's slot overrides (tests/conftest.py: cleared
at import, before test modules build their agents, and again for every test by
`_no_shell_slot_overrides`). The owner's live-walkthrough shell exports a
SAPLING_MODEL_<SLOT> override for every learning-loop slot; before the clears,
41 tests failed under the grader and tutor ones alone — grader provenance
labels (spec §13 A116) and the A111 pins read a slot's provider at run time —
and 4 more under all of them, because an agent's model and settings are fixed
when its module is imported."""

from __future__ import annotations

import os

#: the owner's live-walkthrough shell: one override per learning-loop slot
#: (the historical A111 pending set; still exported even after Claude evals clear)
_LOOP_SLOT_OVERRIDES = (
    "check_items", "grader", "grader_second", "learning_decision",
    "loop_tutor_lite", "loop_tutor", "loop_tutor_deep",
)
EXPORTED = {f"SAPLING_MODEL_{slot.upper()}": "gemini-2.5-flash-lite" for slot in _LOOP_SLOT_OVERRIDES}


def test_the_function_mode_seam_is_not_a_slot_override():
    """The clears name one `SAPLING_MODEL_<TASK>` per AgentTask, so they can
    never touch SAPLING_MODEL_MODE or SAPLING_FUNCTION_HANDLERS (the
    function-mode seam); every slot override is gone for this test."""
    from typing import get_args

    from agents._providers import AgentTask

    names = {f"SAPLING_MODEL_{task.upper()}" for task in get_args(AgentTask)}
    assert "SAPLING_MODEL_MODE" not in names
    assert not any(name.startswith("SAPLING_FUNCTION") for name in names)
    assert set(EXPORTED) <= names
    assert all(name not in os.environ for name in names)
