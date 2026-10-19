"""PKG-13 fix round: db/e2e_handler_constants reads the handler module's E2E_*
strings from source — pinned here to the IMPORTED module, so the two can never
disagree (the seed and the learn_loop oracle read them this way to skip a
~2.5 s pydantic-ai/genai import per Playwright test)."""

from __future__ import annotations

import pytest

from db import e2e_handler_constants as ehc


def test_every_string_constant_the_reader_yields_matches_the_module():
    import agents.function_handlers_e2e as handlers

    env = ehc._module_constants()
    assert env, "no E2E_* strings read"
    for name, text in env.items():
        assert getattr(handlers, name) == text, name


def test_the_loop_seed_and_oracle_constants_are_read():
    import agents.function_handlers_e2e as handlers

    names = ("E2E_LOOP_FINAL_ANSWER", "E2E_LOOP_PROBE_PROMPT", "E2E_LOOP_REFERENCE")
    assert ehc.read_constants(*names) == tuple(getattr(handlers, n) for n in names)
    # E2E_LOOP_REFERENCE is an f-string over E2E_LOOP_FINAL_ANSWER
    assert handlers.E2E_LOOP_FINAL_ANSWER in ehc.read_constants("E2E_LOOP_REFERENCE")[0]


def test_an_unknown_or_non_string_name_raises():
    with pytest.raises(KeyError):
        ehc.read_constants("E2E_NOPE")
    with pytest.raises(KeyError):
        ehc.read_constants("E2E_LOOP_PHASE_PATTERNS")  # a dict, never read as a string


@pytest.mark.parametrize(
    "src",
    ['f"{X!r}"', 'f"{X:>4}"', 'f"{X + X}"', 'f"{UNKNOWN}"', "str(1)"],
)
def test_the_evaluator_refuses_anything_but_plain_string_expressions(src):
    import ast

    node = ast.parse(src, mode="eval").body
    with pytest.raises(ValueError):
        ehc._eval(node, {"X": "x"}, "E2E_T")


def test_importing_the_reader_does_not_import_the_handler_module():
    import subprocess
    import sys

    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from db.e2e_handler_constants import read_constants; "
            "read_constants('E2E_LOOP_FINAL_ANSWER'); "
            "print('agents.function_handlers_e2e' in sys.modules, 'pydantic_ai' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.split() == ["False", "False"]
