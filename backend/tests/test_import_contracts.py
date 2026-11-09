"""The import-boundary contracts in backend/.importlinter hold (#118).

CI runs `lint-imports` as its own step; this is the same check inside the
hermetic suite, so a local `pytest tests/` catches a new layering or
cross-domain violation too. Skipped where import-linter is not installed.
"""
import os
import subprocess
import sys

import pytest

pytest.importorskip("importlinter")

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_import_contracts_are_kept():
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; from importlinter.cli import lint_imports; "
         "sys.exit(lint_imports(no_cache=True, no_logo=True))"],
        cwd=BACKEND, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
