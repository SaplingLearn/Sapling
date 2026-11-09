"""scripts/mint_scope_token.py: the step-2d manual token check (#115).

Pinned: it refuses production (and an unset APP_ENV, which config.py reads as
production) without --allow-production; the token it prints is the real
db/user_jwt one; --show-key never prints a private member.
"""
from __future__ import annotations

import base64
import json

import pytest

from db import user_jwt
from scripts import mint_scope_token as script

SECRET = b"super-secret-jwt-token-with-at-least-32-characters-long"
OCT = json.dumps({"kty": "oct", "k": base64.urlsafe_b64encode(SECRET).rstrip(b"=").decode(),
                  "kid": "local-hs"})


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    user_jwt.clear_token_cache()
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT)
    yield
    user_jwt.clear_token_cache()


def _claims(token: str) -> dict:
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


@pytest.mark.parametrize("app_env", ["production", "PRODUCTION", None])
def test_refuses_production_without_the_flag(monkeypatch, capsys, app_env):
    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)
    assert script.main(["user_1"]) == 2
    out = capsys.readouterr()
    assert out.out == "" and "refusing" in out.err


def test_allow_production_overrides(monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "production")
    assert script.main(["--allow-production", "user_1"]) == 0
    assert _claims(capsys.readouterr().out.strip())["sub"] == "user_1"


def test_mints_the_real_user_scoped_token(monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "staging")
    assert script.main(["--decode", "user_42"]) == 0
    out = capsys.readouterr()
    token = out.out.strip()
    claims = _claims(token)
    assert claims["sub"] == "user_42" and claims["iss"] == user_jwt.ISSUER
    assert claims["role"] == "authenticated" and claims["exp"] - claims["iat"] == user_jwt.TOKEN_TTL_S
    assert '"kid": "local-hs"' in out.err and token not in out.err


def test_show_key_never_prints_a_private_member(monkeypatch, capsys):
    from cryptography.hazmat.primitives.asymmetric import ec

    def _b64(n: int) -> str:
        return base64.urlsafe_b64encode(n.to_bytes(32, "big")).rstrip(b"=").decode()
    priv = ec.generate_private_key(ec.SECP256R1())
    nums = priv.private_numbers()
    d = _b64(nums.private_value)
    jwk = {"kty": "EC", "crv": "P-256", "kid": "sapling-es-1", "d": d,
           "x": _b64(nums.public_numbers.x), "y": _b64(nums.public_numbers.y)}
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, json.dumps(jwk))
    monkeypatch.setenv("APP_ENV", "local")
    assert script.main(["--show-key"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["alg"] == "ES256" and shown["kid"] == "sapling-es-1"
    assert "d" not in shown["public_jwk"] and d not in json.dumps(shown)


def test_show_key_hides_an_hs256_secret(monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "local")
    assert script.main(["--show-key"]) == 0
    out = capsys.readouterr().out
    assert json.loads(OCT)["k"] not in out and json.loads(out)["alg"] == "HS256"


def test_missing_key_is_exit_1(monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv(user_jwt.SIGNING_KEY_ENV)
    assert script.main(["user_1"]) == 1
    assert "SUPABASE_JWT_SIGNING_KEY is not set" in capsys.readouterr().err


def test_env_file_is_read(tmp_path, monkeypatch, capsys):
    # setenv first so monkeypatch restores whatever load_dotenv overrides.
    monkeypatch.setenv("APP_ENV", "production")
    f = tmp_path / ".env.staging"
    f.write_text(f"APP_ENV=staging\n{user_jwt.SIGNING_KEY_ENV}='{OCT}'\n")
    assert script.main(["--env-file", str(f), "user_7"]) == 0
    assert _claims(capsys.readouterr().out.strip())["sub"] == "user_7"
