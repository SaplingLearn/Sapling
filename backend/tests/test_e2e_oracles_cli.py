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


def test_ciphertext_manifest_covers_every_column_a_document_upload_encrypts():
    """The manifest is what enforces the encrypted-column set at rest on every
    lane run, so a column encrypted by the app but absent here is a regression
    the lane cannot see — a later change writing it in plaintext would ship
    undetected. `agent_result` (#507) was exactly that gap.

    Derived from the row `_persist_document` actually inserts rather than from a
    second hardcoded list: every value that decrypts is ciphertext at rest, and
    every such column must be named in the manifest.
    """
    from unittest.mock import patch

    from agents.classifier import DocumentClassification
    from agents.concept_extraction import Concept, ConceptList
    from agents.document import DocumentProcessingResult
    from agents.summary import Summary
    from e2e_oracles.gather import _CIPHERTEXT_MANIFEST
    from routes.documents import _persist_document
    from services.encryption import decrypt

    result = DocumentProcessingResult(
        classification=DocumentClassification(
            category="slides", is_syllabus=False, confidence=0.9, rationale="r",
        ),
        summary=Summary(headline="h", abstract="a", key_points=["1", "2", "3"]),
        concepts=ConceptList(
            concepts=[Concept(name="Mitosis", description="d", importance=0.5)],
        ),
    )
    with patch("routes.documents.table") as t:
        t.return_value.insert.side_effect = lambda row: [dict(row)]
        _persist_document(
            user_id="u1", offering_id="off-1", filename="x.pdf", result=result,
            request_id="req-1", file_hash="abc123",
            extracted_text="the extracted text of a lecture deck",
        )
        row = t.return_value.insert.call_args[0][0]

    manifested = {c for table_name, _pk, c in _CIPHERTEXT_MANIFEST if table_name == "documents"}
    encrypted = set()
    for column, value in row.items():
        if not isinstance(value, str):
            continue
        try:
            decrypt(value)
        except Exception:
            continue
        encrypted.add(column)

    assert encrypted, "the fixture stopped encrypting anything — the check is vacuous"
    assert encrypted <= manifested, (
        f"documents columns encrypted at the insert boundary but missing from "
        f"_CIPHERTEXT_MANIFEST: {sorted(encrypted - manifested)}"
    )
