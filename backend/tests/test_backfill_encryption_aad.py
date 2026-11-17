"""db/backfill_encryption_aad.py on an in-memory PostgREST fake (finding M13)."""
from __future__ import annotations

import hashlib

import pytest

from db import backfill_encryption_aad as bf
from services import encryption as enc
from services.encryption import bind, decrypt_if_present, encrypt, encrypt_bytes


def _v1(plain: str) -> str:
    return encrypt(plain, v2=False)


class FakeDB:
    """Just enough PostgREST for the backfill: keyset select + the swap RPC."""

    def __init__(self, tables: dict[str, list[dict]]):
        self.tables = tables
        self.selects = 0
        self.swaps: list[dict] = []
        self.before_swap = None  # hook: simulate a concurrent app write

    def table(self, name):
        db = self

        class _T:
            def select(self, cols, filters=None, order=None, limit=None):
                db.selects += 1
                rows = db.tables.get(name, [])
                pk = order.split(".")[0]
                out = []
                for r in sorted(rows, key=lambda r: str(r[pk])):
                    ok = True
                    for col, f in (filters or {}).items():
                        if f == "not.is.null" and r.get(col) is None:
                            ok = False
                        elif f.startswith("gt.") and not str(r[col]) > f[3:]:
                            ok = False
                    if ok:
                        out.append({c: r.get(c) for c in cols.split(",")})
                return out[:limit]

        return _T()

    def rpc(self, fn, params):
        assert fn == bf.SWAP_FN
        if params["p_table"] == "encryption_key_check":
            self.probes = getattr(self, "probes", 0) + 1  # _probe_swap: no such row
            return False
        if self.before_swap:
            self.before_swap(params)
        self.swaps.append(params)
        for r in self.tables.get(params["p_table"], []):
            if str(r[params["p_pk_column"]]) == params["p_pk"]:
                cur = r[params["p_column"]]
                if hashlib.md5(str(cur).encode()).hexdigest() != params["p_old_md5"]:
                    return False
                r[params["p_column"]] = params["p_new"]
                return True
        return False


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB({})
    monkeypatch.setattr(bf, "table", fake.table)
    monkeypatch.setattr(bf, "rpc", fake.rpc)
    from services import encryption_canary
    monkeypatch.setattr(encryption_canary, "verify_encryption_key", lambda **_kw: "ok")
    return fake


def _run(*argv):
    return bf.main(list(argv))


def test_dry_run_writes_nothing_and_reports(db, capsys):
    db.tables["notes"] = [{"id": "n1", "body": _v1("hello")},
                          {"id": "n2", "body": encrypt("bound", bind=bind("notes", "body", "n2"))}]
    assert _run("--table", "notes", "--column", "body") == 1  # v1 remains
    assert db.swaps == []
    out = capsys.readouterr().out
    assert "v2 ok: 1" in out and "v1: 1" in out and "would rewrite: 1" in out
    assert "hello" not in out


def test_apply_reseals_v1_bound_to_its_row_and_a_second_run_is_a_noop(db):
    db.tables["notes"] = [{"id": f"n{i}", "body": _v1(f"body {i}")} for i in range(5)]
    assert _run("--apply", "--table", "notes", "--column", "body", "--batch", "2") == 0
    for i, row in enumerate(db.tables["notes"]):
        assert row["body"].startswith("enc2:0:")
        # The app's own reader opens it in place ...
        assert decrypt_if_present(row["body"], bind=bind("notes", "body", row)) == f"body {i}"
        # ... and nowhere else.
        assert decrypt_if_present(row["body"], bind=bind("notes", "title", row)) is None
    n = len(db.swaps)
    assert _run("--apply", "--table", "notes", "--column", "body") == 0
    assert len(db.swaps) == n  # nothing left to rewrite


def test_a_concurrent_app_write_is_never_overwritten(db, capsys):
    row = {"id": "n1", "body": _v1("stale")}
    db.tables["notes"] = [row]
    fresh = encrypt("fresh", bind=bind("notes", "body", "n1"))

    def app_writes(_params):
        row["body"] = fresh

    db.before_swap = app_writes
    assert _run("--apply", "--table", "notes", "--column", "body") == 1
    assert row["body"] == fresh
    assert "conflict: 1" in capsys.readouterr().out


def test_key_guard_aborts_before_reading(db, monkeypatch):
    from services import encryption_canary

    db.tables["notes"] = [{"id": "n1", "body": _v1("x")}]

    def wrong_key(**_kw):
        raise encryption_canary.EncryptionKeyMismatch("wrong key")

    monkeypatch.setattr(encryption_canary, "verify_encryption_key", wrong_key)
    assert _run("--apply") == 2
    monkeypatch.setattr(encryption_canary, "verify_encryption_key", lambda **_kw: "absent")
    assert _run("--apply") == 2
    assert db.selects == 0 and db.swaps == []


def test_plaintext_and_moved_values_are_reported_not_touched(db, capsys):
    moved = encrypt("alice's", bind=bind("notes", "body", "n_alice"))
    db.tables["notes"] = [
        {"id": "n1", "body": "legacy plaintext"},
        {"id": "n2", "body": moved},   # copied into n2 by someone without the key
        {"id": "n3", "body": None},
    ]
    assert _run("--apply", "--table", "notes", "--column", "body") == 1
    assert db.swaps == []
    assert db.tables["notes"][0]["body"] == "legacy plaintext"
    out = capsys.readouterr().out
    assert "undecryptable: 1  id=n1" in out
    assert "v2_bad: 1  id=n2" in out
    assert "legacy plaintext" not in out and "alice" not in out


def test_composite_keys_redirected_cells_json_and_bytes(db):
    db.tables["quiz_responses"] = [
        {"id": "r1", "attempt_id": "att", "question_index": 2, "answer_text": _v1('{"text":"42"}')}]
    db.tables["tutor_pending_sessions"] = [{"session_id": "s1", "assistant_reply": _v1("hi there")}]
    db.tables["document_uploads"] = [{"id": "u1", "file_data": encrypt_bytes(b"%PDF", v2=False),
                                      "result": None}]
    assert _run("--apply", "--table", "quiz_responses", "--table", "tutor_pending_sessions",
                "--table", "document_uploads") == 0
    r = db.tables["quiz_responses"][0]
    assert enc.decrypt_json_column(
        r["answer_text"], bind=bind("quiz_responses", "answer_text", r)) == {"text": "42"}
    # Sealed for the messages row materialize_tutor_session copies it into.
    p = db.tables["tutor_pending_sessions"][0]
    assert decrypt_if_present(p["assistant_reply"], bind=bind("messages", "content", "s1")) == "hi there"
    u = db.tables["document_uploads"][0]
    assert enc.decrypt_bytes(u["file_data"], bind=bind("document_uploads", "file_data", "u1")) == b"%PDF"


def test_start_after_resumes_one_column_and_max_rows_caps(db):
    db.tables["notes"] = [{"id": f"n{i}", "body": _v1(str(i))} for i in range(4)]
    assert _run("--apply", "--table", "notes", "--column", "body", "--start-after", "n1") == 0  # its range is done
    bodies = [r["body"] for r in db.tables["notes"]]
    assert not bodies[0].startswith("enc2:") and not bodies[1].startswith("enc2:")
    assert bodies[2].startswith("enc2:") and bodies[3].startswith("enc2:")
    assert _run("--apply", "--table", "notes", "--column", "body", "--max-rows", "1") == 1
    assert sum(r["body"].startswith("enc2:") for r in db.tables["notes"]) == 3


def test_the_canary_is_never_backfilled():
    assert all(s.table != "encryption_key_check" for s in bf._targets(None, None))
    with pytest.raises(bf.Abort):
        bf._targets(["encryption_key_check"], None)
