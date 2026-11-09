"""Hermetic tests for the #400 CLI: registry wiring, guards, exit codes."""

import pytest

from e2e_oracles import __main__ as cli
from e2e_oracles.findings import Finding
from e2e_oracles.gather import require_local


def test_require_local_accepts_loopback_hosts():
    require_local("postgresql://postgres:postgres@127.0.0.1:54322/postgres", "db")
    require_local("http://localhost:5000", "base-url")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@db.abcdef.supabase.co:5432/postgres",
        "postgresql://u:p@127.0.0.1.evil.com/postgres",
        "http://sapling.example.com",
    ],
)
def test_require_local_rejects_non_loopback(url):
    with pytest.raises(RuntimeError):
        require_local(url, "db")


@pytest.fixture(autouse=True)
def _stack_adopted(request, monkeypatch):
    """The exit-code tests judge fake checks, not a stack: skip the stack
    lookup, which would otherwise refuse on any laptop (no slot, not CI) and,
    with a held stack, write its URLs into this process's environment."""
    if "adopt" not in request.node.name:
        monkeypatch.setattr(cli, "_adopt_e2e_stack", lambda argv: None)


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
    import os

    assert os.environ["E2E_BACKEND_URL"] == "http://localhost:5101"
    assert os.environ["SUPABASE_DB_URL"].endswith(":54422/postgres")


def _fake_check(findings, suppressed=0):
    def run(args):
        return findings, suppressed

    return run


def test_exit_zero_when_all_checks_clean(monkeypatch, capsys):
    monkeypatch.setattr(cli, "CHECKS", {"logscan": _fake_check([])})
    assert cli.main(["--check", "logscan"]) == 0
    assert "0 finding" in capsys.readouterr().out


def test_exit_one_with_findings_and_json_output(monkeypatch, capsys):
    f = Finding(oracle="graph", summary="node count 18 != 17", evidence={"payload": 18})
    monkeypatch.setattr(cli, "CHECKS", {"graph": _fake_check([f])})
    assert cli.main(["--check", "graph", "--json"]) == 1
    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["findings"][0]["summary"].startswith("node count")


def test_exit_two_when_a_check_raises(monkeypatch, capsys):
    def boom(args):
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(cli, "CHECKS", {"orphans": boom})
    assert cli.main(["--check", "orphans"]) == 2
    assert "oracle-error" in capsys.readouterr().out


def test_exit_two_when_a_check_returns_oracle_error_finding(monkeypatch, capsys):
    # A check can RETURN an oracle-error finding (e.g. logscan's missing-log-
    # file case) instead of raising. That must force exit 2 too — an
    # oracle-error means the run's other results can't be trusted, whether
    # the check signaled it via an exception or via its own return value.
    f = Finding(oracle="oracle-error", summary="logscan: log file not found (is the stack up?)")
    monkeypatch.setattr(cli, "CHECKS", {"logscan": _fake_check([f])})
    assert cli.main(["--check", "logscan"]) == 2
    assert "oracle-error" in capsys.readouterr().out


def test_unknown_check_name_rejected():
    with pytest.raises(SystemExit):
        cli.main(["--check", "nope"])
