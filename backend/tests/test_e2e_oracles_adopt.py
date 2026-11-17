"""The oracle CLI's stack lookup (`_adopt_e2e_stack`): which E2E stack the
judges run against, and the refusal that keeps them off the dev database."""

import os

import pytest

from e2e_oracles import __main__ as cli


@pytest.fixture
def _no_stack(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_STACK_MANIFEST", tmp_path / "stack.json")
    for var in ("E2E_BACKEND_URL", "SUPABASE_DB_URL", "CI"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path / "stack.json"


def test_adopt_refuses_without_a_stack_outside_ci(_no_stack):
    assert "no E2E stack" in cli._adopt_e2e_stack([])


def test_adopt_refusal_is_exit_two(_no_stack, capsys):
    assert cli.main(["--check", "logscan"]) == 2
    assert "no E2E stack" in capsys.readouterr().err


def test_adopt_allows_ci_and_an_explicit_base_url(_no_stack, monkeypatch):
    assert cli._adopt_e2e_stack(["--base-url", "http://127.0.0.1:5101"]) is None
    monkeypatch.setenv("CI", "true")
    assert cli._adopt_e2e_stack([]) is None


def test_adopt_keeps_an_exported_slot(_no_stack, monkeypatch):
    monkeypatch.setenv("E2E_BACKEND_URL", "http://localhost:5102")
    assert cli._adopt_e2e_stack([]) is None


def test_adopt_reads_the_manifest(_no_stack, monkeypatch):
    _no_stack.write_text(
        '{"backendUrl": "http://localhost:5101", '
        '"dbUrl": "postgresql://postgres:postgres@127.0.0.1:54422/postgres"}'
    )
    # setenv first so monkeypatch restores both vars after the test.
    monkeypatch.setenv("E2E_BACKEND_URL", "")
    monkeypatch.setenv("SUPABASE_DB_URL", "")
    assert cli._adopt_e2e_stack([]) is None
    assert os.environ["E2E_BACKEND_URL"] == "http://localhost:5101"
    assert os.environ["SUPABASE_DB_URL"].endswith(":54422/postgres")
