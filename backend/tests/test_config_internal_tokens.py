"""validate_config() refuses a SET internal bearer token under 32 bytes.

CANOPY_METRICS_TOKEN, ACCOUNT_SYNC_INBOUND_TOKEN and ACCOUNT_SYNC_PEER_TOKEN
are each the whole gate of a server-to-server route (the inbound account-sync
token alone admits plaintext export and overwrite of any account). Unset or
blank stays fine — that is "feature off". The error names the variable, never
the value.
"""
import pytest

import config
from tests.test_config_validation_failclosed import _set_required

TOKENS = ("CANOPY_METRICS_TOKEN", "ACCOUNT_SYNC_INBOUND_TOKEN", "ACCOUNT_SYNC_PEER_TOKEN")


@pytest.fixture
def strict(monkeypatch):
    _set_required(monkeypatch)
    for name in TOKENS:
        monkeypatch.delenv(name, raising=False)


def test_unset_tokens_boot(strict):
    config.validate_config()


@pytest.mark.parametrize("name", TOKENS)
@pytest.mark.parametrize("value", ["", "   ", " \n\t"])
def test_blank_token_is_unset_and_boots(strict, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    config.validate_config()


@pytest.mark.parametrize("name", TOKENS)
def test_short_token_refuses_boot_naming_the_variable_not_the_value(strict, monkeypatch, name):
    value = "s3cr3t-short-token-0123456789ab"  # 31 bytes
    assert len(value.encode()) == 31
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError) as exc:
        config.validate_config()
    msg = str(exc.value)
    assert name in msg and "32 bytes" in msg
    assert value not in msg
    assert [t for t in TOKENS if t in msg] == [name]


@pytest.mark.parametrize("name", TOKENS)
def test_32_byte_token_boots(strict, monkeypatch, name):
    monkeypatch.setenv(name, "a" * 32)
    config.validate_config()


@pytest.mark.parametrize("name", TOKENS)
def test_length_is_measured_after_strip(strict, monkeypatch, name):
    # Padding does not count: 31 real bytes plus whitespace is still too short.
    monkeypatch.setenv(name, "  " + "a" * 31 + "\n")
    with pytest.raises(RuntimeError, match=name):
        config.validate_config()


def test_length_is_utf8_bytes(strict, monkeypatch):
    monkeypatch.setenv("ACCOUNT_SYNC_INBOUND_TOKEN", "é" * 16)  # 16 chars, 32 bytes
    config.validate_config()
    monkeypatch.setenv("ACCOUNT_SYNC_INBOUND_TOKEN", "é" * 15 + "a")  # 31 bytes
    with pytest.raises(RuntimeError, match="ACCOUNT_SYNC_INBOUND_TOKEN"):
        config.validate_config()


def test_every_weak_token_is_named(strict, monkeypatch):
    for name in TOKENS:
        monkeypatch.setenv(name, "short")
    with pytest.raises(RuntimeError) as exc:
        config.validate_config()
    assert all(name in str(exc.value) for name in TOKENS)
    assert "short" not in str(exc.value).replace("shorter", "")


def test_local_mode_also_refuses(monkeypatch):
    # A token is a deliberate opt-in on any environment, local included.
    _set_required(monkeypatch, IS_LOCAL=True, APP_ENV="local", SESSION_SECRET="")
    monkeypatch.setenv("CANOPY_METRICS_TOKEN", "short")
    with pytest.raises(RuntimeError, match="CANOPY_METRICS_TOKEN"):
        config.validate_config()


def test_openssl_hex_32_token_boots(strict, monkeypatch):
    # `openssl rand -hex 32` -> 64 hex chars.
    for name in TOKENS:
        monkeypatch.setenv(name, "0f" * 32)
    config.validate_config()
