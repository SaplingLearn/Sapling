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
from tests.split_patches import set_auth_session_secret


def _set_required(monkeypatch, **overrides):
    base = {
        "SUPABASE_URL": "https://x.supabase.co",
        "SUPABASE_SERVICE_KEY": "service-key",
        "GEMINI_API_KEY": "gemini-key",
        "ANTHROPIC_API_KEY": "anthropic-key",
        "SESSION_SECRET": "x" * 40,  # >= 32 bytes (strong)
        "IS_LOCAL": False,
        "APP_ENV": "production",
        "FRONTEND_URL": "http://localhost:3000",
        "GOOGLE_AUTH_REDIRECT_URI": "http://localhost:5000/api/auth/google/callback",
        "SECURE_COOKIES_EXPLICIT": False,
    }
    base.update(overrides)
    # A fresh key, not conftest's committed all-zero test key (refused outside
    # local, see TestCommittedDemoSecrets).
    monkeypatch.setenv("ENCRYPTION_KEY", base.pop("ENCRYPTION_KEY", "ab" * 32))
    for name in config._PLATFORM_MARKERS:
        monkeypatch.delenv(name, raising=False)
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
            ANTHROPIC_API_KEY="",
            SESSION_SECRET="",
            IS_LOCAL=False,
        )
        with pytest.raises(RuntimeError) as exc:
            config.validate_config()
        msg = str(exc.value)
        for key in (
            "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "GEMINI_API_KEY",
            "ANTHROPIC_API_KEY", "SESSION_SECRET",
        ):
            assert key in msg

    def test_session_secret_required_outside_local(self, monkeypatch):
        _set_required(monkeypatch, SESSION_SECRET="", IS_LOCAL=False)
        with pytest.raises(RuntimeError) as exc:
            config.validate_config()
        assert "SESSION_SECRET" in str(exc.value)

    def test_session_secret_relaxed_in_local(self, monkeypatch):
        _set_required(monkeypatch, SESSION_SECRET="", IS_LOCAL=True)
        config.validate_config()  # no raise — relaxed for local dev

    def test_anthropic_key_optional_in_local(self, monkeypatch):
        _set_required(monkeypatch, ANTHROPIC_API_KEY="", IS_LOCAL=True)
        config.validate_config()

    def test_anthropic_key_required_outside_local(self, monkeypatch):
        _set_required(monkeypatch, ANTHROPIC_API_KEY="", IS_LOCAL=False)
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            config.validate_config()

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


class TestLocalModeOnARealDeployment:
    """APP_ENV local/test arms POST /api/auth/test-login (a session for ANY
    user id) and relaxes SESSION_SECRET: a process that looks deployed must
    refuse to boot in those modes."""

    @pytest.mark.parametrize("app_env", ["local", "test", "dev", "development"])
    def test_local_modes_boot_on_a_developer_machine(self, monkeypatch, app_env):
        _set_required(monkeypatch, APP_ENV=app_env, IS_LOCAL=True, SESSION_SECRET="")
        config.validate_config()  # the E2E stack / pytest / local dev shape

    @pytest.mark.parametrize("url", [
        "http://127.0.0.1:3101", "https://localhost:3000", "https://app.localhost",
        "http://frontend:3000", "http://staging.saplinglearn.com",
    ])
    def test_local_or_plain_http_frontend_is_not_a_marker(self, monkeypatch, url):
        _set_required(monkeypatch, APP_ENV="local", IS_LOCAL=True, FRONTEND_URL=url)
        config.validate_config()

    @pytest.mark.parametrize("app_env", ["local", "test"])
    def test_public_https_frontend_refuses(self, monkeypatch, app_env):
        _set_required(monkeypatch, APP_ENV=app_env, IS_LOCAL=True,
                      FRONTEND_URL="https://saplinglearn.com")
        with pytest.raises(RuntimeError, match="Refusing to start") as exc:
            config.validate_config()
        assert "FRONTEND_URL" in str(exc.value)

    def test_public_https_oauth_redirect_refuses(self, monkeypatch):
        _set_required(monkeypatch, APP_ENV="local", IS_LOCAL=True,
                      GOOGLE_AUTH_REDIRECT_URI="https://api.saplinglearn.com/api/auth/google/callback")
        with pytest.raises(RuntimeError, match="GOOGLE_AUTH_REDIRECT_URI"):
            config.validate_config()

    def test_explicit_secure_cookies_refuses(self, monkeypatch):
        _set_required(monkeypatch, APP_ENV="test", IS_LOCAL=True, SECURE_COOKIES_EXPLICIT=True)
        with pytest.raises(RuntimeError, match="SECURE_COOKIES"):
            config.validate_config()

    def test_hosting_platform_marker_refuses(self, monkeypatch):
        _set_required(monkeypatch, APP_ENV="local", IS_LOCAL=True)
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
        with pytest.raises(RuntimeError, match="RAILWAY_ENVIRONMENT_NAME"):
            config.validate_config()

    def test_production_on_a_real_deployment_boots(self, monkeypatch):
        _set_required(monkeypatch, FRONTEND_URL="https://saplinglearn.com",
                      SECURE_COOKIES_EXPLICIT=True)
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
        config.validate_config()


class TestCommittedDemoSecrets:
    """The SESSION_SECRET / ENCRYPTION_KEY values committed to the repo (local
    examples, the frontend's start:test, CI) are refused outside local, and
    the error never carries the value."""

    @pytest.mark.parametrize("secret", sorted(config.KNOWN_DEMO_SESSION_SECRETS))
    def test_demo_session_secret_refused_outside_local(self, monkeypatch, secret):
        _set_required(monkeypatch, SESSION_SECRET=secret)
        with pytest.raises(RuntimeError) as exc:
            config.validate_config()
        assert "SESSION_SECRET" in str(exc.value)
        assert secret not in str(exc.value)

    @pytest.mark.parametrize("key", sorted(config.KNOWN_DEMO_ENCRYPTION_KEYS))
    def test_demo_encryption_key_refused_outside_local(self, monkeypatch, key):
        _set_required(monkeypatch, ENCRYPTION_KEY=key.upper())
        with pytest.raises(RuntimeError) as exc:
            config.validate_config()
        assert "ENCRYPTION_KEY" in str(exc.value)
        assert key not in str(exc.value).lower()

    def test_demo_values_still_boot_local(self, monkeypatch):
        _set_required(
            monkeypatch, APP_ENV="local", IS_LOCAL=True,
            SESSION_SECRET="sapling-local-dev-session-secret-change-only-if-you-know-why",
            ENCRYPTION_KEY="0123456789abcdef" * 4,
        )
        config.validate_config()

    def test_the_lists_match_the_committed_files(self):
        """The refusal lists track the files that commit the values."""
        from pathlib import Path

        repo = Path(__file__).resolve().parents[2]
        committed = "\n".join(
            (repo / p).read_text()
            for p in ("backend/.env.local.example", "frontend/.env.local.example",
                      "frontend/package.json", "frontend/.env.example")
        )
        for secret in config.KNOWN_DEMO_SESSION_SECRETS:
            assert secret in committed
        assert "0123456789abcdef" * 4 in committed


class TestUnsignedOAuthFallbackFailsClosed:
    def test_fails_closed_in_production(self, monkeypatch):
        # No SESSION_SECRET + not local → must refuse (pre-fix: silently used
        # the unsigned in-memory store).
        set_auth_session_secret(monkeypatch, "")
        monkeypatch.setattr("services.auth.oauth_state.IS_LOCAL", False)
        with pytest.raises(RuntimeError):
            auth_mod._encode_oauth_cookie({"n": "nonce-123", "v": "verifier"})

    def test_allowed_in_local(self, monkeypatch):
        set_auth_session_secret(monkeypatch, "")
        monkeypatch.setattr("services.auth.oauth_state.IS_LOCAL", True)
        out = auth_mod._encode_oauth_cookie({"n": "nonce-123", "v": "verifier"})
        # Unsigned payload (no "." separator) is permitted only in local dev.
        assert isinstance(out, str) and "." not in out

    def test_signed_when_secret_present(self, monkeypatch):
        set_auth_session_secret(monkeypatch, "supersecret-value")
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
        set_auth_session_secret(monkeypatch, "")
        monkeypatch.setattr("services.auth.oauth_state.IS_LOCAL", False)
        assert auth_mod._decode_oauth_cookie(unsigned) is None
