"""The suite never sees a shell's slot overrides (tests/conftest.py: cleared
at import, before test modules build their agents, and again for every test by
`_no_shell_slot_overrides`). The owner's live-walkthrough shell exports a
SAPLING_MODEL_<SLOT> override for every learning-loop slot; before this, 41
tests failed under the grader and tutor ones alone — grader provenance labels
(spec §13 A116) and the A111 pins read a slot's provider at run time — and 4
more under all eight, because an agent's model and settings are fixed when its
module is imported.

Proven in a child pytest run with all eight exported: tests that assert slot
defaults (read at run time and at import) pass, and a test that sets its own
override still sees it."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from agents._providers import LOOP_SLOTS_PENDING_CLAUDE_EVAL

BACKEND = Path(__file__).resolve().parents[1]
#: the owner's live-walkthrough shell: one override per learning-loop slot
EXPORTED = {f"SAPLING_MODEL_{slot.upper()}": "claude-haiku-5-5" for slot in LOOP_SLOTS_PENDING_CLAUDE_EVAL}
#: each failed under the exports before the conftest clears
PINNED = (
    # run time: asserts the grader's default provider, then sets its own override
    "tests/test_loop_slots_claude_ready.py::test_slot_provider_follows_the_override",
    # run time: a grade's provenance label under the default slots
    "tests/test_learning_check_tool.py::test_grade_returns_all_yes_and_records_usage",
    # import time: the grader agent's generation bounds, fixed when it was built
    "tests/test_learning_grader_completeness.py::test_every_actual_model_request_keeps_generation_bounds",
    # import time: the decision agent's model and settings
    "tests/test_learning_decisions.py::test_decision_slot_is_flash_lite_thinking_off_one_prompt",
)


def test_exported_slot_overrides_never_reach_a_test():
    assert len(EXPORTED) == 8
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *PINNED],
        cwd=BACKEND,
        env={**os.environ, **EXPORTED},
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-1000:]
    assert f"{len(PINNED)} passed" in run.stdout


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
