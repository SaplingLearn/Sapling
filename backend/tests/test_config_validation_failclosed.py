"""
Regression tests for #174:
- validate_config() fails loudly at startup, naming every missing required key.
- the unsigned in-memory OAuth-state fallback is unreachable outside local dev.

The fail-closed test fails on pre-fix code, where _encode_oauth_cookie silently
fell back to the unsigned in-memory store whenever SESSION_SECRET was empty,
regardless of environment.
"""
import pytest

import config
from routes import auth as auth_mod


def _set_required(monkeypatch, **overrides):
    base = {
        "SUPABASE_URL": "https://x.supabase.co",
        "SUPABASE_SERVICE_KEY": "service-key",
        "GEMINI_API_KEY": "gemini-key",
        "SESSION_SECRET": "x" * 40,  # >= 32 bytes (strong)
        "IS_LOCAL": False,
    }
    base.update(overrides)
    for k, v in base.items():
        monkeypatch.setattr(config, k, v)


class TestValidateConfig:
    def test_passes_when_all_present(self, monkeypatch):
        _set_required(monkeypatch)
        config.validate_config()  # no raise

    def test_raises_naming_every_missing_key(self, monkeypatch):
        _set_required(
            monkeypatch,
            SUPABASE_URL="",
            SUPABASE_SERVICE_KEY="",
            GEMINI_API_KEY="",
            SESSION_SECRET="",
            IS_LOCAL=False,
        )
        with pytest.raises(RuntimeError) as exc:
            config.validate_config()
        msg = str(exc.value)
        for key in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "GEMINI_API_KEY", "SESSION_SECRET"):
            assert key in msg

    def test_session_secret_required_outside_local(self, monkeypatch):
        _set_required(monkeypatch, SESSION_SECRET="", IS_LOCAL=False)
        with pytest.raises(RuntimeError) as exc:
            config.validate_config()
        assert "SESSION_SECRET" in str(exc.value)

    def test_session_secret_relaxed_in_local(self, monkeypatch):
        _set_required(monkeypatch, SESSION_SECRET="", IS_LOCAL=True)
        config.validate_config()  # no raise — relaxed for local dev

    def test_weak_session_secret_rejected_outside_local(self, monkeypatch):
        # Present-but-weak must NOT pass: whitespace-only and a too-short secret
        # would become a weak HMAC key. >= 32 bytes is required (matches FE).
        for weak in ("   ", "short", "x" * 31):
            _set_required(monkeypatch, SESSION_SECRET=weak, IS_LOCAL=False)
            with pytest.raises(RuntimeError) as exc:
                config.validate_config()
            assert "SESSION_SECRET" in str(exc.value)

    def test_exactly_32_byte_secret_passes(self, monkeypatch):
        _set_required(monkeypatch, SESSION_SECRET="x" * 32, IS_LOCAL=False)
        config.validate_config()  # no raise — exactly at the 32-byte floor


class TestUnsignedOAuthFallbackFailsClosed:
    def test_fails_closed_in_production(self, monkeypatch):
        # No SESSION_SECRET + not local → must refuse (pre-fix: silently used
        # the unsigned in-memory store).
        monkeypatch.setattr(auth_mod, "SESSION_SECRET", "")
        monkeypatch.setattr(auth_mod, "IS_LOCAL", False)
        with pytest.raises(RuntimeError):
            auth_mod._encode_oauth_cookie({"n": "nonce-123", "v": "verifier"})

    def test_allowed_in_local(self, monkeypatch):
        monkeypatch.setattr(auth_mod, "SESSION_SECRET", "")
        monkeypatch.setattr(auth_mod, "IS_LOCAL", True)
        out = auth_mod._encode_oauth_cookie({"n": "nonce-123", "v": "verifier"})
        # Unsigned payload (no "." separator) is permitted only in local dev.
        assert isinstance(out, str) and "." not in out

    def test_signed_when_secret_present(self, monkeypatch):
        monkeypatch.setattr(auth_mod, "SESSION_SECRET", "supersecret-value")
        out = auth_mod._encode_oauth_cookie({"n": "nonce-123", "v": "verifier"})
        assert "." in out  # payload_b64.sig_b64

    def test_decode_refuses_unsigned_cookie_in_production(self, monkeypatch):
        # Symmetric decode-side guard: even a hand-built unsigned cookie must
        # not be honored outside local dev.
        import base64
        import json

        unsigned = base64.urlsafe_b64encode(
            json.dumps({"n": "x", "v": "y"}).encode()
        ).decode().rstrip("=")
        # Force the unsigned path (empty secret) in production mode.
        monkeypatch.setattr(auth_mod, "SESSION_SECRET", "")
        monkeypatch.setattr(auth_mod, "IS_LOCAL", False)
        assert auth_mod._decode_oauth_cookie(unsigned) is None
