"""db/backfill_encryption.py: the one-shot re-encryption of legacy plaintext.

It writes to every encrypted column in production and had no tests. These run
it against an in-memory table fake and pin what it targets to the ciphertext
oracle's manifest, so it cannot drift onto dropped columns again (it still
listed the `users` profile fields and `user_settings.bio/location` that the
0024 identity split removed).
"""

import json

import pytest

from db import backfill_encryption as bf
from e2e_oracles.gather import _CIPHERTEXT_MANIFEST
from services.encryption import decrypt, decrypt_json, encrypt, encrypt_json


class _FakeTable:
    def __init__(self, db, name):
        self.db, self.name = db, name

    def select(self, cols):
        self.db.selected.append((self.name, cols.split(",")))
        return [dict(r) for r in self.db.rows.get(self.name, [])]

    def update(self, values, *, filters):
        (pk, cond), = filters.items()
        key = cond.removeprefix("eq.")
        self.db.updates.append((self.name, key, dict(values)))
        for row in self.db.rows[self.name]:
            if str(row[pk]) == key:
                row.update(values)


class _FakeDB:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.selected = []
        self.updates = []

    def __call__(self, name):
        return _FakeTable(self, name)


@pytest.fixture
def db(monkeypatch):
    fake = _FakeDB()
    monkeypatch.setattr(bf, "table", fake)
    return fake


def test_dry_run_counts_but_never_writes(db):
    db.rows["messages"] = [{"id": 1, "content": "hello"}, {"id": 2, "content": encrypt("hi")}]
    counts = bf.backfill_messages(apply=False)
    assert counts == {"content": 1, "scanned": 2}
    assert db.updates == []


def test_apply_encrypts_plaintext_and_skips_ciphertext(db):
    already = encrypt("hi")
    db.rows["messages"] = [
        {"id": 1, "content": "hello"},
        {"id": 2, "content": already},
        {"id": 3, "content": None},
    ]
    bf.backfill_messages(apply=True)
    rows = {r["id"]: r for r in db.rows["messages"]}
    assert decrypt(rows[1]["content"]) == "hello"
    assert rows[2]["content"] == already
    assert rows[3]["content"] is None
    assert [u[1] for u in db.updates] == ["1"]


def test_second_run_is_a_no_op(db):
    db.rows["feedback"] = [{"id": 1, "comment": "slow", "topic": "quiz"}]
    bf.backfill_feedback(apply=True)
    db.updates.clear()
    assert bf.backfill_feedback(apply=True) == {"comment": 0, "topic": 0, "scanned": 1}
    assert db.updates == []


def test_json_column_round_trips_parsed_and_corrupt_values(db):
    db.rows["sessions"] = [
        {"id": 1, "summary_json": json.dumps({"a": 1})},
        {"id": 2, "summary_json": "{not json"},
        {"id": 3, "summary_json": encrypt_json({"b": 2})},
    ]
    counts = bf.backfill_sessions(apply=True)
    assert counts == {"summary_json": 2, "scanned": 3}
    rows = {r["id"]: r for r in db.rows["sessions"]}
    assert decrypt_json(rows[1]["summary_json"]) == {"a": 1}
    assert decrypt(rows[2]["summary_json"]) == "{not json"


def test_numeric_columns_are_stored_as_encrypted_strings(db):
    db.rows["assignments"] = [{"id": 1, "notes": None, "points_possible": 10, "points_earned": 7.5}]
    bf.backfill_assignments(apply=True)
    row = db.rows["assignments"][0]
    assert decrypt(row["points_possible"]) == "10"
    assert decrypt(row["points_earned"]) == "7.5"


def test_oauth_tokens_skip_empty_strings(db):
    db.rows["oauth_tokens"] = [{"user_id": "u", "access_token": "", "refresh_token": "r"}]
    assert bf.backfill_oauth_tokens(apply=True) == {
        "access_token": 0, "refresh_token": 1, "scanned": 1,
    }
    assert db.rows["oauth_tokens"][0]["access_token"] == ""


# Encrypted columns the ciphertext oracle does not sample (it cannot read the
# OAuth tokens' table in the E2E stack, and bio/location are optional profile
# fields the seed leaves empty), but which ARE encrypted at write.
_ENCRYPTED_OUTSIDE_MANIFEST = {
    ("oauth_tokens", "access_token"),
    ("oauth_tokens", "refresh_token"),
    ("user_profiles", "bio"),
    ("user_profiles", "location"),
}


def test_every_targeted_column_is_a_known_encrypted_column(db):
    for runner in bf.RUNNERS.values():
        runner(apply=False)
    targeted = {(t, c) for t, cols in db.selected for c in cols[1:]}
    known = {(t, c) for t, _pk, c in _CIPHERTEXT_MANIFEST} | _ENCRYPTED_OUTSIDE_MANIFEST
    assert targeted - known == set()


def test_main_keeps_going_when_one_table_fails(db, monkeypatch, capsys):
    def boom(apply):
        raise RuntimeError("PostgREST 400")

    monkeypatch.setattr(bf, "RUNNERS", {"broken": boom, "messages": bf.backfill_messages})
    db.rows["messages"] = [{"id": 1, "content": "x"}]
    monkeypatch.setattr("sys.argv", ["backfill_encryption"])
    assert bf.main() == 0
    out = capsys.readouterr().out
    assert "FAILED: PostgREST 400" in out
    assert "Would encrypt 1 cells total." in out
    assert db.updates == []


def test_plaintext_json_text_is_not_mistaken_for_ciphertext():
    """decrypt_json falls back to json.loads on plaintext, so using it as the
    detector made every legacy JSON-text row look encrypted and the backfill
    skipped exactly the rows it exists for."""
    assert bf._is_already_encrypted_json(json.dumps({"a": 1})) is False
    assert bf._is_already_encrypted_json(encrypt_json({"a": 1})) is True
