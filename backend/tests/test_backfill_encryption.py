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

    def select_with_count(self, cols, *, filters=None, order, limit, offset):
        # PostgREST's contract: at most `limit` rows from `offset`, in `order`.
        if offset == 0:
            self.db.selected.append((self.name, cols.split(",")))
        self.db.pages.append((self.name, offset))
        rows = sorted(self.db.rows.get(self.name, []), key=lambda r: str(r[order]))
        return [dict(r) for r in rows[offset:offset + limit]], len(rows)

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
        self.pages = []
        self.updates = []

    def __call__(self, name):
        return _FakeTable(self, name)


@pytest.fixture
def db(monkeypatch):
    fake = _FakeDB()
    monkeypatch.setattr(bf, "table", fake)
    # main() checks the key canary first; these tests have no canary table.
    monkeypatch.setattr(bf, "verify_encryption_key", lambda *, seed: "ok")
    bf.UNDECRYPTABLE.clear()
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
    # The other tables still run, but the run is not a success: the dropped-
    # column runners failed on every run for months behind an exit 0.
    assert bf.main() == 1
    out = capsys.readouterr().out
    assert "FAILED: PostgREST 400" in out
    assert "FAILED tables (not backfilled): broken" in out
    assert "Would encrypt 1 cells total." in out
    assert db.updates == []


def test_main_exits_zero_when_every_table_ran(db, monkeypatch):
    monkeypatch.setattr(bf, "RUNNERS", {"messages": bf.backfill_messages})
    db.rows["messages"] = [{"id": 1, "content": "x"}]
    monkeypatch.setattr("sys.argv", ["backfill_encryption"])
    assert bf.main() == 0


def test_a_table_larger_than_one_page_is_backfilled_whole(db):
    """One unpaged select returns PostgREST's first 1,000 rows. The script
    encrypted those, and every later run saw only that page, already
    encrypted, and reported nothing left to do."""
    db.rows["messages"] = [{"id": f"m{i:05d}", "content": f"text {i}"} for i in range(2500)]
    counts = bf.backfill_messages(apply=True)
    assert counts == {"content": 2500, "scanned": 2500}
    assert [offset for _name, offset in db.pages] == [0, 1000, 2000]
    assert all(bf._is_already_encrypted(r["content"]) for r in db.rows["messages"])

    db.updates.clear()
    assert bf.backfill_messages(apply=True) == {"content": 0, "scanned": 2500}
    assert db.updates == []


def _sealed_under_another_key(text: str) -> str:
    import base64
    import os

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(b"\x07" * 32).encrypt(nonce, text.encode(), None)).decode()


def test_ciphertext_under_another_key_is_left_alone_and_reported(db, monkeypatch, capsys):
    """A cell that fails to decrypt is not always plaintext. Encrypting one
    written under another key buries it a layer deeper, and the read helpers
    then hand ciphertext back as the value."""
    foreign = _sealed_under_another_key("someone@example.com")
    foreign_json = _sealed_under_another_key('{"a":1}')
    db.rows["messages"] = [{"id": 1, "content": foreign}, {"id": 2, "content": "plain text"}]
    db.rows["sessions"] = [{"id": 1, "summary_json": foreign_json}]
    db.rows["assignments"] = [{"id": 1, "notes": None, "points_possible": foreign, "points_earned": 1000}]
    db.rows["oauth_tokens"] = [{"user_id": "u", "access_token": foreign, "refresh_token": "1//0g-plain_token"}]
    monkeypatch.setattr(bf, "RUNNERS", {
        "messages": bf.backfill_messages, "sessions": bf.backfill_sessions,
        "assignments": bf.backfill_assignments, "oauth_tokens": bf.backfill_oauth_tokens,
    })
    monkeypatch.setattr("sys.argv", ["backfill_encryption", "--apply"])

    assert bf.main() == 0
    assert db.rows["messages"][0]["content"] == foreign
    assert decrypt(db.rows["messages"][1]["content"]) == "plain text"
    assert db.rows["sessions"][0]["summary_json"] == foreign_json
    assert db.rows["assignments"][0]["points_possible"] == foreign
    assert decrypt(db.rows["assignments"][0]["points_earned"]) == "1000"
    assert db.rows["oauth_tokens"][0]["access_token"] == foreign
    assert decrypt(db.rows["oauth_tokens"][0]["refresh_token"]) == "1//0g-plain_token"
    out = capsys.readouterr().out
    for cell in ("messages.content: 1", "sessions.summary_json: 1",
                 "assignments.points_possible: 1", "oauth_tokens.access_token: 1"):
        assert cell in out


def test_ordinary_plaintext_never_looks_like_ciphertext():
    for value in ("hello there", "Ada", "7.5", "1000", '{"a": 1}', "ya29.a0AfH6-token_value",
                  "a" * 36, 12, None):
        assert bf._looks_like_ciphertext(value) is False, value
    assert bf._looks_like_ciphertext(encrypt("x")) is True


def test_main_refuses_to_run_with_the_wrong_key(db, monkeypatch, capsys):
    """With the wrong key EVERY cell fails to decrypt, which is what legacy
    plaintext looks like; --apply would wrap the whole database a second time."""
    def mismatch(*, seed):
        assert seed is False  # an ops script must never write the canary
        raise bf.EncryptionKeyMismatch("ENCRYPTION_KEY does not match the database")

    monkeypatch.setattr(bf, "verify_encryption_key", mismatch)
    db.rows["messages"] = [{"id": 1, "content": "x"}]
    monkeypatch.setattr("sys.argv", ["backfill_encryption", "--apply"])
    assert bf.main() == 2
    assert "REFUSING to run" in capsys.readouterr().out
    assert db.selected == [] and db.updates == []


def test_plaintext_json_text_is_not_mistaken_for_ciphertext(db):
    """decrypt_json falls back to json.loads on plaintext, so using it as the
    detector made every legacy JSON-text row look encrypted and the backfill
    skipped exactly the rows it exists for."""
    already = encrypt_json({"b": 2})
    db.rows["quiz_context"] = [
        {"id": 1, "context_json": json.dumps({"a": 1})},
        {"id": 2, "context_json": already},
    ]
    assert bf.backfill_quiz_context(apply=True) == {"context_json": 1, "scanned": 2}
    rows = {r["id"]: r for r in db.rows["quiz_context"]}
    assert json.loads(decrypt(rows[1]["context_json"])) == {"a": 1}
    assert rows[2]["context_json"] == already


def test_corrupt_json_row_is_encrypted_once_not_on_every_run(db):
    """A row whose JSON does not parse is stored as encrypt(raw). The detector
    used to also require the decrypted text to parse, so the next --apply saw
    that row as plaintext and encrypted the ciphertext again, and readers got
    ciphertext back from decrypt."""
    db.rows["sessions"] = [{"id": 1, "summary_json": "{not json"}]
    bf.backfill_sessions(apply=True)
    once = db.rows["sessions"][0]["summary_json"]
    db.updates.clear()

    assert bf.backfill_sessions(apply=True) == {"summary_json": 0, "scanned": 1}
    assert db.updates == []
    assert db.rows["sessions"][0]["summary_json"] == once
    assert decrypt(once) == "{not json"
