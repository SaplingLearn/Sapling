"""Fixtures for the opt-in integration suite (#362) — real local Supabase.

Runs ONLY when RUN_INTEGRATION=1 and SUPABASE_URL is local. Loads backend/.env
with override so the seed's ENCRYPTION_KEY / SESSION_SECRET / SUPABASE_* win over
the root conftest's hermetic test defaults (else decryption silently mismatches).
"""
import os
from pathlib import Path

import pytest

_RUN = os.getenv("RUN_INTEGRATION") == "1"

# Must happen BEFORE any config/db/services import so the real key is in place.
if _RUN:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)


def _is_local() -> bool:
    url = (os.getenv("SUPABASE_URL") or "").strip()
    return "127.0.0.1" in url or "localhost" in url


def mint_session(user_id: str, ttl: int = 3600) -> str:
    """Mint a sapling_session token via the canonical minter (#381).

    Thin wrapper, not a re-implementation: the import stays function-local so
    `config` is not imported at module scope, which would freeze SESSION_SECRET /
    ENCRYPTION_KEY before the `load_dotenv(override=True)` above has run.
    """
    from services.session_tokens import mint_session as _mint_session
    return _mint_session(user_id, ttl)


@pytest.fixture(scope="session", autouse=True)
def _require_local_stack():
    if not _RUN:
        pytest.skip("integration suite: set RUN_INTEGRATION=1 (with the local stack up)")
    if not _is_local():
        pytest.skip(f"integration suite: SUPABASE_URL is not local ({os.getenv('SUPABASE_URL')!r})")
    # Ensure the rich dataset is present (idempotent, additive).
    from db import seed_local_rich
    seed_local_rich.main()
    yield


@pytest.fixture
def client():
    from main import app
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def anon_client():
    from main import app
    from fastapi.testclient import TestClient
    return TestClient(app)
