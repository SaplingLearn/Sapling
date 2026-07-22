import pytest

import db.seed_local_rich as rich


def test_guard_refuses_non_local(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://prod.supabase.co")
    with pytest.raises(SystemExit):
        rich._guard_local()


def test_guard_allows_local(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")
    rich._guard_local()  # no raise
