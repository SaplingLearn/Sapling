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

# The write-mode script guard is bypassed in the hermetic suite (conftest);
# this module tests it.
pytestmark = pytest.mark.real_script_key_guard


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


def test_read_only_check_never_seeds_an_empty_table():
    """seed=False is for ops scripts: one holding the wrong key must not write
    a canary that then locks the real backend out."""
    t = _tbl([])
    with patch("services.encryption_canary.table", return_value=t):
        assert encryption_canary.verify_encryption_key(seed=False) == "absent"
    t.upsert.assert_not_called()


def test_read_only_check_still_refuses_a_foreign_key():
    t = _tbl([{"canary": _foreign(encryption_canary.CANARY_PLAINTEXT)}])
    with patch("services.encryption_canary.table", return_value=t):
        with pytest.raises(encryption_canary.EncryptionKeyMismatch):
            encryption_canary.verify_encryption_key(seed=False)
    t.upsert.assert_not_called()


def test_lost_seed_race_to_another_key_refuses_to_boot():
    # Our DO NOTHING insert lost to a concurrent boot holding a different key.
    t = _tbl([], [{"canary": _foreign(encryption_canary.CANARY_PLAINTEXT)}])
    with patch("services.encryption_canary.table", return_value=t):
        with pytest.raises(encryption_canary.EncryptionKeyMismatch):
            encryption_canary.verify_encryption_key()


def test_two_replicas_booting_at_once_under_the_same_key_both_pass():
    """#117 two replicas: both read an empty table and both seed. The table
    keeps the first canary (DO NOTHING on conflict); the second replica's
    insert is a no-op and its re-read gets the first one's canary, which the
    same key opens. Neither refuses to boot, and nothing is overwritten."""
    import threading

    stored: dict = {}
    lock = threading.Lock()
    both_read = threading.Barrier(2)

    def select(*_a, **_k):
        with lock:
            rows = [{"canary": stored["canary"]}] if stored else []
        if not rows:
            both_read.wait(timeout=5)  # both boots see the empty table
        return rows

    def upsert(data, **kw):
        assert kw.get("ignore_duplicates") is True
        with lock:
            if not stored:
                stored.update(data)
        return []

    t = MagicMock()
    t.select.side_effect = select
    t.upsert.side_effect = upsert
    results, errors = [], []

    def boot():
        try:
            results.append(encryption_canary.verify_encryption_key())
        except Exception as e:  # pragma: no cover - the assertion reports it
            errors.append(e)

    with patch("services.encryption_canary.table", return_value=t):
        threads = [threading.Thread(target=boot) for _ in range(2)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=10)
    assert errors == [] and results == ["seeded", "seeded"]
    assert t.upsert.call_count == 2 and stored["id"] == 1


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


# ---------------------------------------------------------------------------
# Write-mode scripts (require_key_for_write): only a positive check passes.
# ---------------------------------------------------------------------------


def _status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "http://x/rest/v1/encryption_key_check")
    return httpx.HTTPStatusError(str(code), request=req, response=httpx.Response(code, request=req))


def test_script_guard_passes_a_matching_key():
    t = _tbl([{"canary": encrypt(encryption_canary.CANARY_PLAINTEXT)}])
    with patch("services.encryption_canary.table", return_value=t):
        assert encryption_canary.require_key_for_write("backfill") == "ok"


def test_script_guard_refuses_a_foreign_key():
    t = _tbl([{"canary": _foreign(encryption_canary.CANARY_PLAINTEXT)}])
    with patch("services.encryption_canary.table", return_value=t):
        with pytest.raises(encryption_canary.EncryptionKeyMismatch):
            encryption_canary.require_key_for_write("backfill")


@pytest.mark.parametrize(
    "failure",
    [_status_error(404), httpx.ConnectError("refused"), RuntimeError("SUPABASE_URL unset")],
    ids=["missing-table", "unreachable", "other"],
)
def test_script_guard_refuses_when_it_cannot_check(failure):
    """The server only warns here; a write-mode script must not proceed."""
    t = MagicMock()
    t.select.side_effect = failure
    with patch("services.encryption_canary.table", return_value=t):
        with pytest.raises(encryption_canary.EncryptionKeyUnverified):
            encryption_canary.require_key_for_write("backfill")
        with pytest.raises(encryption_canary.EncryptionKeyUnverified):
            encryption_canary.require_key_for_write("seed", allow_seed=True)


def test_script_guard_never_seeds_an_empty_canary_by_default():
    """A backfill over existing rows must not plant its own key's canary."""
    t = _tbl([])
    with patch("services.encryption_canary.table", return_value=t):
        with pytest.raises(encryption_canary.EncryptionKeyUnverified, match="no canary"):
            encryption_canary.require_key_for_write("backfill")
    t.upsert.assert_not_called()


def test_fresh_database_seeder_may_seed_the_canary():
    seeded: dict = {}
    t = MagicMock()
    t.upsert.side_effect = lambda data, **kw: seeded.update(data) or [data]
    t.select.side_effect = lambda *a, **k: [{"canary": seeded["canary"]}] if seeded else []
    with patch("services.encryption_canary.table", return_value=t):
        assert encryption_canary.require_key_for_write("seed", allow_seed=True) == "seeded"


def test_cli_form_exits_2_before_any_write(capsys):
    t = _tbl([{"canary": _foreign(encryption_canary.CANARY_PLAINTEXT)}])
    with patch("services.encryption_canary.table", return_value=t):
        with pytest.raises(SystemExit) as exc:
            encryption_canary.abort_unless_key_verified("backfill")
    assert exc.value.code == 2
    assert "ABORT" in capsys.readouterr().err


def test_backfill_encryption_apply_aborts_on_a_foreign_key(monkeypatch):
    """The 2026-10-21 failure, scripted: --apply under the wrong key must stop
    before reading, let alone re-encrypting, a single row."""
    from db import backfill_encryption

    runner = MagicMock()
    monkeypatch.setattr(backfill_encryption, "RUNNERS", {"users": runner})
    monkeypatch.setattr("sys.argv", ["backfill_encryption", "--apply"])
    t = _tbl([{"canary": _foreign(encryption_canary.CANARY_PLAINTEXT)}])
    with patch("services.encryption_canary.table", return_value=t):
        with pytest.raises(SystemExit) as exc:
            backfill_encryption.main()
    assert exc.value.code == 2
    runner.assert_not_called()


def test_backfill_encryption_dry_run_needs_no_check(monkeypatch):
    from db import backfill_encryption

    runner = MagicMock(return_value={"scanned": 0})
    monkeypatch.setattr(backfill_encryption, "RUNNERS", {"users": runner})
    monkeypatch.setattr("sys.argv", ["backfill_encryption"])
    with patch("services.encryption_canary.require_key_for_write") as guard:
        assert backfill_encryption.main() == 0
    guard.assert_not_called()
    runner.assert_called_once_with(apply=False)


# Every script that writes encrypted columns (or writes values it derived by
# decrypting them) calls the guard in its write mode.
WRITE_SCRIPTS = [
    "db/backfill_encryption.py",
    "db/seed_staging.py",
    "db/seed_showcase.py",
    "db/seed_local_rich.py",
    "db/seed_local_study.py",
    "db/seed_showcase_loop.py",
    "db/e2e_staging_http.py",
    "scripts/backfill_encrypt_chunk_text.py",
    "scripts/ingest_catalog.py",
    "scripts/backfill_document_chunks.py",
    "scripts/backfill_course_chunk_sources.py",
    "scripts/backfill_document_shareability.py",
    "scripts/dedupe_course_chunks.py",
    "scripts/move_unapproved_users_to_waitlist.py",
    "scripts/retire_gradescope_passwords.py",
    "scripts/seed_learning_close_beat.py",
    "scripts/seed_learning_goal_journey.py",
    "scripts/seed_learning_teach_prompts.py",
]


@pytest.mark.parametrize("path", WRITE_SCRIPTS)
def test_every_write_script_calls_the_guard(path):
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / path).read_text()
    assert "abort_unless_key_verified(" in src, f"{path} writes encrypted data without the key check"


def test_no_unguarded_encrypting_script():
    """A new script under db/ or scripts/ that encrypts must join WRITE_SCRIPTS."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    pattern = re.compile(r"\bencrypt(_if_present|_json|_numeric)?\(")
    found = set()
    for sub in ("db", "scripts"):
        for f in (root / sub).rglob("*.py"):
            rel = f.relative_to(root).as_posix()
            if rel.startswith("db/archive/") or "__pycache__" in rel:
                continue
            if "if __name__" in f.read_text() and pattern.search(f.read_text()):
                found.add(rel)
    assert found <= set(WRITE_SCRIPTS), sorted(found - set(WRITE_SCRIPTS))
