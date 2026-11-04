"""The boot-time ENCRYPTION_KEY canary (services/encryption_canary.py).

A backend whose key differs from the one its database was written with must
refuse to boot: on 2026-10-21 a laptop running a feature branch against prod's
SUPABASE_URL re-encrypted one account's email, name and OAuth tokens under the
laptop's key, and prod could no longer read them."""
import base64
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from services import encryption_canary
from services.encryption import encrypt


def _foreign(plaintext: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(os.urandom(32)).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def _tbl(*select_results):
    t = MagicMock()
    t.select.side_effect = list(select_results)
    return t


def test_matching_key_passes():
    t = _tbl([{"canary": encrypt(encryption_canary.CANARY_PLAINTEXT)}])
    with patch("services.encryption_canary.table", return_value=t):
        assert encryption_canary.verify_encryption_key() == "ok"
    t.upsert.assert_not_called()


def test_foreign_key_refuses_to_boot():
    t = _tbl([{"canary": _foreign(encryption_canary.CANARY_PLAINTEXT)}])
    with patch("services.encryption_canary.table", return_value=t):
        with pytest.raises(encryption_canary.EncryptionKeyMismatch, match="ENCRYPTION_KEY"):
            encryption_canary.verify_encryption_key()


def test_right_key_wrong_plaintext_refuses_to_boot():
    t = _tbl([{"canary": encrypt("something else")}])
    with patch("services.encryption_canary.table", return_value=t):
        with pytest.raises(encryption_canary.EncryptionKeyMismatch):
            encryption_canary.verify_encryption_key()


def test_empty_table_seeds_then_verifies():
    t = MagicMock()
    seeded = {}

    def upsert(data, **kw):
        seeded.update(data)
        assert kw.get("ignore_duplicates") is True  # never overwrite another key's canary
        return [data]

    t.upsert.side_effect = upsert
    t.select.side_effect = lambda *a, **k: [{"canary": seeded["canary"]}] if seeded else []
    with patch("services.encryption_canary.table", return_value=t):
        assert encryption_canary.verify_encryption_key() == "seeded"
    assert seeded["id"] == 1


def test_lost_seed_race_to_another_key_refuses_to_boot():
    # Our DO NOTHING insert lost to a concurrent boot holding a different key.
    t = _tbl([], [{"canary": _foreign(encryption_canary.CANARY_PLAINTEXT)}])
    with patch("services.encryption_canary.table", return_value=t):
        with pytest.raises(encryption_canary.EncryptionKeyMismatch):
            encryption_canary.verify_encryption_key()


def test_missing_table_is_skipped_not_fatal():
    # Code can deploy before its migration is applied; that must not brick boot.
    resp = httpx.Response(404, request=httpx.Request("GET", "http://x/rest/v1/encryption_key_check"))
    t = MagicMock()
    t.select.side_effect = httpx.HTTPStatusError("404", request=resp.request, response=resp)
    with patch("services.encryption_canary.table", return_value=t):
        assert encryption_canary.verify_encryption_key() == "skipped"


def test_unreachable_db_is_skipped_not_fatal():
    t = MagicMock()
    t.select.side_effect = httpx.ConnectError("refused")
    with patch("services.encryption_canary.table", return_value=t):
        assert encryption_canary.verify_encryption_key() == "skipped"


def test_lifespan_runs_the_check():
    from unittest.mock import AsyncMock
    with patch("main.ensure_bucket_exists", new=AsyncMock()), \
         patch("main.verify_encryption_key") as v:
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app):
            pass
    v.assert_called_once()
