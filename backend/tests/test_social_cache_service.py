"""#518: room_summaries.summary is ciphertext at rest; cache keys on member_hash."""
from unittest.mock import patch

from services.encryption import decrypt, encrypt
from services.social_cache_service import get_cached_summary, save_summary, _compute_hash


class FakeTable:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.upserted = []

    def select(self, *a, **k):
        return list(self.rows)

    def upsert(self, data, on_conflict=None):
        self.upserted.append(data)
        return [data]


def test_save_summary_encrypts():
    fake = FakeTable()
    with patch("services.social_cache_service.table", return_value=fake):
        save_summary("room1", ["s1", "s2"], "Everyone is stuck on recursion")
    row = fake.upserted[0]
    assert row["summary"] != "Everyone is stuck on recursion"
    assert decrypt(row["summary"]) == "Everyone is stuck on recursion"
    assert row["member_hash"] == _compute_hash(["s1", "s2"])  # hash stays comparable


def test_get_cached_summary_decrypts_on_hash_hit():
    members = ["s1", "s2"]
    fake = FakeTable(rows=[{
        "summary": encrypt("Everyone is stuck on recursion"),
        "member_hash": _compute_hash(members),
    }])
    with patch("services.social_cache_service.table", return_value=fake):
        assert get_cached_summary("room1", members) == "Everyone is stuck on recursion"


def test_get_cached_summary_tolerates_legacy_plaintext():
    members = ["s1"]
    fake = FakeTable(rows=[{"summary": "plain", "member_hash": _compute_hash(members)}])
    with patch("services.social_cache_service.table", return_value=fake):
        assert get_cached_summary("room1", members) == "plain"


def test_get_cached_summary_miss_on_stale_hash():
    fake = FakeTable(rows=[{"summary": encrypt("old"), "member_hash": "stale"}])
    with patch("services.social_cache_service.table", return_value=fake):
        assert get_cached_summary("room1", ["new"]) is None
