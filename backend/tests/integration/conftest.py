"""Fixtures for the opt-in integration suite (#362) — real local Supabase.

Runs ONLY when RUN_INTEGRATION=1 and SUPABASE_URL is local. Loads backend/.env
with override so the seed's ENCRYPTION_KEY / SESSION_SECRET / SUPABASE_* win over
the root conftest's hermetic test defaults (else decryption silently mismatches).
"""
import base64
import hashlib
import hmac
import json
import os
import time
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
    """Mint a sapling_session token exactly as auth_guard._decode_session verifies."""
    from config import SESSION_SECRET
    payload = {"user_id": user_id, "exp": int(time.time()) + ttl}
    pb = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(SESSION_SECRET.encode(), pb.encode(), hashlib.sha256).digest()
    sb = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{pb}.{sb}"


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
