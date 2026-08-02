"""/api/health must report the deployed commit (#516).

The promotion runner polls this to tell "not deployed yet" from "deployed and
broken". A short SHA is no more sensitive than the model_mode already exposed.
"""
import pytest
from fastapi.testclient import TestClient

from config import build_commit
import main


@pytest.fixture
def client():
    return TestClient(main.app)


def test_build_commit_reads_railway_env(monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc1234567890def")
    assert build_commit() == "abc1234"


def test_build_commit_is_unknown_when_unset(monkeypatch):
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.delenv("GIT_COMMIT_SHA", raising=False)
    assert build_commit() == "unknown"


def test_build_commit_falls_back_to_generic_env(monkeypatch):
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.setenv("GIT_COMMIT_SHA", "0f1e2d3c4b5a")
    assert build_commit() == "0f1e2d3"


def test_build_commit_ignores_blank_value(monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "   ")
    monkeypatch.delenv("GIT_COMMIT_SHA", raising=False)
    assert build_commit() == "unknown"


def test_health_reports_commit(client, monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "deadbeefcafe")
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["commit"] == "deadbee"


def test_health_keeps_existing_keys(client):
    body = client.get("/api/health").json()
    assert body["service"] == "sapling-backend"
    assert "model_mode" in body
