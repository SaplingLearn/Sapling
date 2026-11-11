"""PKG-00 review fixes: tests for the helpers that the gate tests and the
invariants module rely on. The counts other packages pin
(`test_learning_gate.py` 13, invariants `4 passed, 8 skipped`) stay the same,
so these checks live in their own module.

- config.py calls load_dotenv() at import time, so reloading config re-reads
  backend/.env. A .env that turns the loop on would put back the variable an
  "env unset" test had just deleted.
- A reload rebinds config.LEARNING_LOOP_ENABLED. monkeypatch restores the env
  var, but not the module attribute computed from it.
- `_imports_of` must see every alias, relative imports, imports inside
  functions, and anything a pure module pulls in through another learning
  module.
"""

from __future__ import annotations

import os
import subprocess
import warnings

import dotenv
import pytest
import test_learning_gate as gate_tests
import test_learning_loop_invariants as inv


@pytest.fixture(autouse=True)
def _leave_config_and_gate_as_found():
    """These tests exercise the helpers' own clean-up. If a helper regresses,
    this keeps the damage inside this module."""
    import config
    from learning import gate

    saved = {config: dict(vars(config)), gate: dict(vars(gate))}
    yield
    for module, attrs in saved.items():
        vars(module).update(attrs)


@pytest.fixture
def dotenv_turns_loop_off(monkeypatch):
    """Stands in for a backend/.env that holds LEARNING_LOOP_ENABLED=false —
    post-launch (PKG-14b) the dangerous direction: the default is ON, so a
    .env that refills the variable would silently turn an "unset" case off.
    Like load_dotenv's default (override=False), it only fills a missing var."""

    def fake_load_dotenv(*args, **kwargs):
        if "LEARNING_LOOP_ENABLED" not in os.environ:
            monkeypatch.setenv("LEARNING_LOOP_ENABLED", "false")
        return True

    monkeypatch.setattr(dotenv, "load_dotenv", fake_load_dotenv)


def test_gate_reload_ignores_a_dotenv_that_turns_the_loop_off(monkeypatch, dotenv_turns_loop_off):
    """(Formerly ..._turns_the_loop_on: the build-phase default was OFF.)"""
    gate = gate_tests._reload(monkeypatch, None)
    assert gate.config.LEARNING_LOOP_ENABLED is True


def test_inv_11_holds_when_a_dotenv_turns_the_loop_off(dotenv_turns_loop_off):
    with pytest.MonkeyPatch.context() as mp:
        inv.test_inv_11_gate_false_when_env_unset(mp, None, True)


def test_gate_reload_restores_the_flag_afterwards(monkeypatch):
    import config

    monkeypatch.delenv("LEARNING_LOOP_ENABLED", raising=False)
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    with pytest.MonkeyPatch.context() as mp:
        gate_tests._reload(mp, "false")
    assert config.LEARNING_LOOP_ENABLED is True, "a 'false' case left the flag OFF"


@pytest.mark.parametrize("raw,expected", [(" False ", False), ("no", False), (None, True)])
def test_inv_11_restores_the_flag_afterwards(monkeypatch, raw, expected):
    """Whatever case inv_11 last ran, every later test sees the flag it found."""
    import config

    monkeypatch.delenv("LEARNING_LOOP_ENABLED", raising=False)
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", not expected)
    with pytest.MonkeyPatch.context() as mp:
        inv.test_inv_11_gate_false_when_env_unset(mp, raw, expected)
    assert config.LEARNING_LOOP_ENABLED is (not expected), "inv_11 leaked its case's flag"


def _learning_pkg(tmp_path, **files):
    pkg = tmp_path / "learning"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    for name, src in files.items():
        (pkg / f"{name}.py").write_text(src)
    return pkg


def test_imports_of_sees_every_alias(tmp_path):
    pkg = _learning_pkg(tmp_path, bkt="import math, db.connection\n")
    assert "db" in inv._imports_of(pkg / "bkt.py")


def test_imports_of_sees_imports_inside_functions(tmp_path):
    pkg = _learning_pkg(
        tmp_path, bkt="def f():\n    from agents.deps import SaplingDeps\n    return SaplingDeps\n"
    )
    assert "agents" in inv._imports_of(pkg / "bkt.py")


def test_imports_of_follows_learning_modules_to_their_imports(tmp_path):
    pkg = _learning_pkg(
        tmp_path,
        gate="from db.connection import table\n",
        state="import pydantic_ai\n",
        helper="from google import genai\n",
        policy=(
            "from learning.gate import learning_loop_active\n"
            "from .state import read_state\n"
            "from . import helper\n"
        ),
    )
    roots = set(inv._imports_of(pkg / "policy.py"))
    assert {"db", "pydantic_ai", "google"} <= roots, roots


def test_imports_of_follows_the_package_init(tmp_path):
    pkg = _learning_pkg(tmp_path, params="X = 1\n", bkt="from learning.params import X\n")
    (pkg / "__init__.py").write_text("from learning.gate import learning_loop_active\n")
    (pkg / "gate.py").write_text("from db.connection import table\n")
    assert "db" in inv._imports_of(pkg / "bkt.py")


def test_imports_of_survives_an_import_cycle(tmp_path):
    pkg = _learning_pkg(tmp_path, a="from learning import b\n", b="from learning import a\n")
    assert "db" not in inv._imports_of(pkg / "a.py")


def test_imports_of_passes_a_clean_pure_module(tmp_path):
    pkg = _learning_pkg(
        tmp_path,
        params="import config\nX = 1\n",
        ladder="from enum import IntEnum\n",
        policy=(
            "from __future__ import annotations\n"
            "import math\n"
            "from learning import params\n"
            "from learning.ladder import IntEnum\n"
        ),
    )
    roots = inv._imports_of(pkg / "policy.py")
    assert not [r for r in roots if r in inv.FORBIDDEN_IMPORT_ROOTS], roots


# --- inv_08 on a shallow clone: fail in CI, warn locally (CodeRabbit PR #673) ---
#
# A depth-1 checkout makes inv_08's never-modified half vacuous. CI now checks
# out full history (ci.yml fetch-depth: 0), and a shallow clone under CI=true
# fails instead of warning, so the check cannot silently stop biting there.


@pytest.fixture
def shallow_clone(monkeypatch):
    monkeypatch.setattr(inv, "_is_shallow_clone", lambda *a, **k: True)


@pytest.mark.parametrize("ci", ["true", "1", "TRUE"])
def test_inv_08_fails_on_a_shallow_clone_in_ci(monkeypatch, shallow_clone, ci):
    monkeypatch.setenv("CI", ci)
    with pytest.raises(pytest.fail.Exception, match="fetch-depth: 0"):
        inv.test_inv_08_series_migrations_named_and_never_modified()


@pytest.mark.parametrize("ci", [None, "", "false", "0"])
def test_inv_08_only_warns_on_a_shallow_local_clone(monkeypatch, shallow_clone, ci):
    if ci is None:
        monkeypatch.delenv("CI", raising=False)
    else:
        monkeypatch.setenv("CI", ci)
    with pytest.warns(UserWarning, match="shallow clone"):
        inv.test_inv_08_series_migrations_named_and_never_modified()


def test_inv_08_is_silent_on_a_full_clone_in_ci(monkeypatch):
    monkeypatch.setattr(inv, "_is_shallow_clone", lambda *a, **k: False)
    monkeypatch.setenv("CI", "true")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        inv.test_inv_08_series_migrations_named_and_never_modified()


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_is_shallow_clone_detects_a_depth_one_clone(tmp_path):
    full, shallow = tmp_path / "full", tmp_path / "shallow"
    full.mkdir()
    _git(full, "init", "-q")
    for i in range(2):
        (full / "f.txt").write_text(str(i))
        _git(full, "add", "f.txt")
        _git(full, "commit", "-q", "-m", f"c{i}")
    _git(tmp_path, "clone", "-q", "--depth", "1", full.as_uri(), str(shallow))
    assert inv._is_shallow_clone(full) is False
    assert inv._is_shallow_clone(shallow) is True
