"""PR #866 Z15: the AAD backfill re-seals an append-only table's 🔒 cells, and
one refused swap never ends the run.

learning_prequestions is append-only (spec §13 A138): service_role holds
SELECT and INSERT only, so `encryption_aad_swap` (SECURITY INVOKER, run as
service_role) is refused on it with 42501. The backfill did not catch that:
the run crashed at learning_prequestions.guess_json, the columns after it
were never reached, and its dry run never reached the exit-0 gate for
ENCRYPTION_LEGACY_READS=refuse. A guess is now re-sealed through
`learning_prequestion_guess_reseal` (migration 20261120055827), and a swap
that raises is counted for its cell (`swap_failed`)."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re

import httpx
import pytest

from db import backfill_encryption_aad as bf
from services import encryption as enc
from services.encryption import bind, decrypt_json, encrypt
from tests.test_backfill_encryption_aad import FakeDB

MIGRATIONS = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"
RESEAL = "learning_prequestion_guess_reseal"
#: The append-only tables where service_role holds no UPDATE (20261109032302,
#: pinned by tests/integration/test_rls_lockdown_db.py::SERVICE_ROLE_NARROWED).
NO_UPDATE = {"learning_evidence_voids", "misconception_attempts", "learning_prequestions"}


def _denied(fn: str) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", f"http://db/rest/v1/rpc/{fn}")
    return httpx.HTTPStatusError("42501", request=req, response=httpx.Response(403, request=req))


class GrantsDB(FakeDB):
    """FakeDB with the grants: the generic swap runs as service_role and is
    refused on a table it may not UPDATE; the re-seal function is the
    owner's compare-and-swap of one guess."""

    def __init__(self, tables, *, refuse=NO_UPDATE):
        super().__init__(tables)
        self.refuse = set(refuse)
        self.reseals: list[dict] = []

    def rpc(self, fn, params):
        if fn == RESEAL:
            assert params["p_new"].startswith("enc2:")
            if not params["p_id"]:
                return False  # _probe_swap: no such row
            self.reseals.append(params)
            for r in self.tables.get("learning_prequestions", []):
                if r["id"] == params["p_id"] and r["guess_json"] is not None:
                    if hashlib.md5(r["guess_json"].encode()).hexdigest() != params["p_old_md5"]:
                        return False
                    r["guess_json"] = params["p_new"]
                    return True
            return False
        if fn == bf.SWAP_FN and params["p_table"] in self.refuse:
            raise _denied(fn)
        return super().rpc(fn, params)


def _guess(i: int) -> dict:
    return {
        "id": f"p{i}", "user_id": "u1", "session_id": "s1", "node_id": f"n{i}",
        # a v1 guess, as written while ENCRYPTION_WRITE_V2 was off
        "guess_json": encrypt(json.dumps({"answer": f"guess {i}"}), v2=False),
    }


@pytest.fixture
def db(monkeypatch):
    fake = GrantsDB({})
    monkeypatch.setattr(bf, "table", fake.table)
    monkeypatch.setattr(bf, "rpc", fake.rpc)
    from services import encryption_canary

    monkeypatch.setattr(encryption_canary, "verify_encryption_key", lambda **_kw: "ok")
    return fake


def test_a_prequestion_guess_is_resealed_bound_to_its_row(db):
    db.tables["learning_prequestions"] = [_guess(1), _guess(2)]

    code = bf.main(["--apply", "--table", "learning_prequestions"])

    assert code == 0 and len(db.reseals) == 2
    for row in db.tables["learning_prequestions"]:
        assert row["guess_json"].startswith("enc2:")
        cell = bind("learning_prequestions", "guess_json", (row["user_id"], row["session_id"], row["node_id"]))
        assert decrypt_json(row["guess_json"], bind=cell)["answer"].startswith("guess ")
    assert bf.main(["--table", "learning_prequestions"]) == 0  # the dry run's gate passes


def test_a_refused_swap_is_counted_and_the_run_goes_on(db, capsys):
    """A swap the database refuses is that cell's: the next column still runs."""
    db.refuse.add("notes")
    db.tables["notes"] = [{"id": "n1", "body": encrypt("hello", v2=False)}]
    db.tables["learning_self_explanations"] = [
        {"id": "e1", "reply_text": encrypt("because", v2=False)},
    ]

    code = bf.main(["--apply", "--table", "notes", "--table", "learning_self_explanations"])

    out = capsys.readouterr().out
    assert code == 1  # the refused cell is still v1
    assert "swap_failed: 1  id=n1" in out and "HTTPStatusError" in out
    assert db.tables["learning_self_explanations"][0]["reply_text"].startswith("enc2:")
    assert "hello" not in out and "because" not in out


def test_apply_aborts_before_any_write_when_the_reseal_function_is_missing(db, capsys, monkeypatch):
    db.tables["learning_prequestions"] = [_guess(1)]

    def missing(fn, params):
        if fn == RESEAL:
            raise _denied(fn)
        return db.rpc(fn, params)

    monkeypatch.setattr(bf, "rpc", missing)
    assert bf.main(["--apply", "--table", "learning_prequestions"]) == 2
    assert f"{RESEAL} is not callable" in capsys.readouterr().out
    assert not db.tables["learning_prequestions"][0]["guess_json"].startswith("enc2:")


def test_every_append_only_cell_has_its_own_reseal():
    cells = {(s.table, s.column) for s in enc.ENCRYPTED_COLUMNS if s.backfill and s.table in NO_UPDATE}
    assert cells == set(bf.APPEND_ONLY_SWAPS)


def test_the_reseal_function_only_reseals():
    (path,) = MIGRATIONS.glob("*_learning_prequestion_guess_reseal.sql")
    sql = path.read_text()
    body = sql[sql.index("CREATE OR REPLACE FUNCTION learning_prequestion_guess_reseal"):]
    assert "SECURITY DEFINER" in body and "SET search_path = public, pg_temp" in body
    assert re.search(r"left\(p_new, 5\) <> 'enc2:'", body)  # a v2 ciphertext only
    assert "guess_json IS NOT NULL" in body and "md5(guess_json) = p_old_md5" in body
    assert "REVOKE ALL ON FUNCTION learning_prequestion_guess_reseal(text, text, text) FROM PUBLIC" in sql
    assert "GRANT EXECUTE ON FUNCTION learning_prequestion_guess_reseal(text, text, text) TO service_role" in sql
    assert not re.search(r"GRANT\s+UPDATE", sql, re.I)  # the table stays append-only
