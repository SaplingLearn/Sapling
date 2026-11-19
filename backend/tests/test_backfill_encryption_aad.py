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
        self.nested_swaps: list[dict] = []
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
                        elif f == "neq.{}" and r.get(col) in (None, {}):
                            ok = False
                        elif f.startswith("gt.") and not str(r[col]) > f[3:]:
                            ok = False
                    if ok:
                        out.append({c: r.get(c) for c in cols.split(",")})
                return out[:limit]

        return _T()

    def rpc(self, fn, params):
        if fn == bf.SWAP_NESTED_FN:
            return self.swap_nested(params)
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


    def swap_nested(self, params):
        """encryption_aad_swap_nested (20261118195701): one value inside the
        row's loop_state, compared by md5; sessions also bump loop_state_rev."""
        pk = {"sessions": "id", "tutor_pending_sessions": "session_id"}[params["p_table"]]
        for r in self.tables.get(params["p_table"], []):
            if str(r[pk]) != params["p_pk"]:
                continue
            if self.before_swap:
                self.before_swap(params)
            self.nested_swaps.append(params)
            *parents, last = params["p_path"]
            node = r["loop_state"]
            for key in parents:
                node = node.get(key) if isinstance(node, dict) else None
            cur = node.get(last) if isinstance(node, dict) else None
            if not isinstance(cur, str) or hashlib.md5(cur.encode()).hexdigest() != params["p_old_md5"]:
                return False
            node[last] = params["p_new"]
            if "loop_state_rev" in r:
                r["loop_state_rev"] += 1
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


# ── Nested ciphertexts (PR #866 C6) ─────────────────────────────────────────
#
# encryption.NESTED_CIPHERTEXTS: the loop's goal text and grade checkpoints,
# sealed inside sessions.loop_state (and a lazy session's
# tutor_pending_sessions.loop_state) and bound to the session.


def _goal(session_id: str, plain: str = "learn recursion", *, v2: bool = False) -> str:
    if v2:
        return encrypt(plain, bind=enc.nested_bind("sessions", "loop_state", "goal.text_encrypted", session_id))
    return _v1(plain)


def _loop_doc(session_id: str, *, v2: bool = False) -> dict:
    cp = enc.nested_bind("sessions", "loop_state", "grade_checkpoint", session_id)
    return {
        "phase": "teach",
        "goal": {"target_node_ids": ["n1"], "text_encrypted": _goal(session_id, v2=v2)},
        "steps": {
            "qh1": {"rung": 1, "grade_checkpoint": encrypt('{"cp":1}', bind=cp) if v2 else _v1('{"cp":1}')},
            "qh2": {"rung": 0},
        },
        "probe": {"current": {"question_hash": "qh9", "grade_checkpoint": _v1('{"cp":9}')}},
    }


def test_every_nested_ciphertext_has_a_holder_and_is_a_target():
    assert {(t, c) for t, c, _ in enc.NESTED_CIPHERTEXTS} <= set(bf.NESTED_HOLDERS)
    names = {(s.table, s.name) for s in bf._targets(None, None) if isinstance(s, bf.NestedSpec)}
    assert names == {
        (holder, f"{column}#{path}")
        for table, column, path in enc.NESTED_CIPHERTEXTS
        for holder, _pk in bf.NESTED_HOLDERS[(table, column)]
    }
    # selectable by column, or one path by its name
    assert {s.name for s in bf._targets(["sessions"], ["loop_state"])} == {
        "loop_state#goal.text_encrypted", "loop_state#grade_checkpoint"}
    (one,) = bf._targets(["sessions"], ["loop_state#grade_checkpoint"])
    assert one.path == "grade_checkpoint"


def test_apply_reseals_every_nested_value_in_place_and_a_second_run_is_a_noop(db):
    doc = _loop_doc("s1")
    db.tables["sessions"] = [{"id": "s1", "loop_state": doc, "loop_state_rev": 3},
                             {"id": "s0", "loop_state": {}, "loop_state_rev": 0}]
    db.tables["tutor_pending_sessions"] = [
        {"session_id": "p1", "loop_state": {"goal": {"text_encrypted": _goal("p1", "pending goal")}}},
        {"session_id": "p2", "loop_state": None},
    ]
    assert _run("--apply", "--column", "loop_state") == 0

    goal = enc.nested_bind("sessions", "loop_state", "goal.text_encrypted", "s1")
    cp = enc.nested_bind("sessions", "loop_state", "grade_checkpoint", "s1")
    assert doc["goal"]["text_encrypted"].startswith("enc2:0:")
    assert enc.decrypt(doc["goal"]["text_encrypted"], bind=goal) == "learn recursion"
    for entry in (doc["steps"]["qh1"], doc["probe"]["current"]):
        assert entry["grade_checkpoint"].startswith("enc2:0:")
        assert enc.decrypt(entry["grade_checkpoint"], bind=cp).startswith('{"cp":')
    # sealed for its own session's cell: another session's binding cannot open it
    other = enc.nested_bind("sessions", "loop_state", "goal.text_encrypted", "s2")
    assert decrypt_if_present(doc["goal"]["text_encrypted"], bind=other) is None
    # the rest of the document is untouched; the app's CAS revision moved
    assert doc["steps"]["qh2"] == {"rung": 0} and doc["phase"] == "teach"
    assert db.tables["sessions"][0]["loop_state_rev"] == 6
    # a lazy session's copy is sealed for the session it materialises into
    pending = db.tables["tutor_pending_sessions"][0]["loop_state"]["goal"]["text_encrypted"]
    p1 = enc.nested_bind("sessions", "loop_state", "goal.text_encrypted", "p1")
    assert enc.decrypt(pending, bind=p1) == "pending goal"
    assert sorted(tuple(s["p_path"]) for s in db.nested_swaps) == [
        ("goal", "text_encrypted"), ("goal", "text_encrypted"),
        ("probe", "current", "grade_checkpoint"), ("steps", "qh1", "grade_checkpoint"),
    ]
    n = len(db.nested_swaps)
    assert _run("--apply", "--column", "loop_state") == 0
    assert len(db.nested_swaps) == n  # nothing left to rewrite


def test_the_dry_run_counts_nested_values_and_writes_nothing(db, capsys):
    db.tables["sessions"] = [{"id": "s1", "loop_state": _loop_doc("s1"), "loop_state_rev": 0},
                             {"id": "s2", "loop_state": _loop_doc("s2", v2=True), "loop_state_rev": 0}]
    assert _run("--table", "sessions", "--column", "loop_state") == 1
    assert db.nested_swaps == []
    out = capsys.readouterr().out
    assert "sessions.loop_state#goal.text_encrypted" in out
    assert "bound as sessions.loop_state#grade_checkpoint" in out
    assert "v2 ok: 1   v1: 1" in out  # the goals
    # the checkpoints: s1's two, and s2's probe one (its step's is v2 already)
    assert "v2 ok: 1   v1: 3" in out
    assert "learn recursion" not in out


def test_a_concurrent_loop_write_is_never_overwritten(db, capsys):
    doc = _loop_doc("s1")
    db.tables["sessions"] = [{"id": "s1", "loop_state": doc, "loop_state_rev": 0}]
    fresh = _goal("s1", "a new goal", v2=True)

    def app_writes(params):
        if params["p_path"] == ["goal", "text_encrypted"]:
            doc["goal"]["text_encrypted"] = fresh

    db.before_swap = app_writes
    assert _run("--apply", "--table", "sessions", "--column", "loop_state#goal.text_encrypted") == 1
    assert doc["goal"]["text_encrypted"] == fresh
    assert "conflict: 1" in capsys.readouterr().out


def test_moved_nested_values_and_plaintext_are_reported_not_touched(db, capsys):
    moved = _goal("s-alice", "alice's goal", v2=True)  # copied into s1's document
    db.tables["sessions"] = [{"id": "s1", "loop_state": {"goal": {"text_encrypted": moved},
                                                          "steps": {"q": {"grade_checkpoint": "plain"}}},
                              "loop_state_rev": 0}]
    assert _run("--apply", "--table", "sessions", "--column", "loop_state") == 1
    assert db.nested_swaps == []
    out = capsys.readouterr().out
    assert "v2_bad: 1  id=s1" in out and "undecryptable: 1  id=s1" in out
    assert "alice" not in out


def test_apply_refuses_before_scanning_when_the_nested_swap_is_not_deployed(db, monkeypatch, capsys):
    import httpx

    db.tables["sessions"] = [{"id": "s1", "loop_state": _loop_doc("s1"), "loop_state_rev": 0}]
    real = db.rpc

    def rpc(fn, params):
        if fn == bf.SWAP_NESTED_FN:
            raise httpx.HTTPStatusError("404", request=httpx.Request("POST", "http://x"),
                                        response=httpx.Response(404))
        return real(fn, params)

    monkeypatch.setattr(bf, "rpc", rpc)
    assert _run("--apply", "--column", "loop_state") == 2
    assert "20261118195701_encryption_aad_swap_nested.sql" in capsys.readouterr().out
    assert db.selects == 0
