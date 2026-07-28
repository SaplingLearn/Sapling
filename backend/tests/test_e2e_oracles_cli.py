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


def test_unknown_check_name_rejected():
    with pytest.raises(SystemExit):
        cli.main(["--check", "nope"])
