"""Mint ONE user-scoped PostgREST token by hand, to check a project accepts it
(#115, RLS step 2d; docs/security/db-user-scope-rollout.md §2).

LOCAL / STAGING ONLY. The token is exactly what ``db/user_jwt.py`` sends under
``db_user_scope=enforce`` (``iss=sapling-api``, ``role=authenticated``, 5-minute
expiry), signed with ``SUPABASE_JWT_SIGNING_KEY``. Anyone holding it can read
and write as that student through PostgREST until it expires, so it is printed
to stdout for one curl and nowhere else.

Run from ``backend/``:

    # the env file is read explicitly; this script never loads backend/.env
    python scripts/mint_scope_token.py --env-file .env.staging user_123
    dotenv -f .env.staging run -- python scripts/mint_scope_token.py user_123

    # which key is configured (alg, kid, fingerprint, PUBLIC half only);
    # compare the kid with https://<ref>.supabase.co/auth/v1/.well-known/jwks.json
    python scripts/mint_scope_token.py --env-file .env.staging --show-key

    # header + claims of the minted token on stderr, the token on stdout
    python scripts/mint_scope_token.py --env-file .env.staging --decode user_123

Refuses to run when ``APP_ENV`` is ``production`` - including when ``APP_ENV``
is unset, which ``config.py`` also reads as production - unless
``--allow-production`` is passed. Exit codes: 0 ok, 2 refused / bad usage,
1 key problem.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))


def _app_env() -> str:
    # config.py's default: a deployment that sets nothing is production.
    return (os.getenv("APP_ENV") or "production").strip().lower()


def _b64d(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _public_view(key_raw: str) -> dict:
    """The configured JWK minus every private member (``d``, ``k``, ...)."""
    jwk = json.loads(key_raw)
    public = {k: v for k, v in jwk.items() if k in ("kty", "crv", "x", "y", "kid", "alg", "use")}
    if jwk.get("kty") == "oct":
        public["k"] = "<secret, not shown>"
    return public


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("user_id", nargs="?", help="users.id to mint for (e.g. user_1234)")
    ap.add_argument("--env-file", help="read SUPABASE_JWT_SIGNING_KEY / APP_ENV from this file")
    ap.add_argument("--show-key", action="store_true",
                    help="print the configured key's alg/kid/fingerprint and public half; mint nothing")
    ap.add_argument("--decode", action="store_true", help="also print header + claims to stderr")
    ap.add_argument("--allow-production", action="store_true",
                    help="run even when APP_ENV is production (or unset)")
    args = ap.parse_args(argv)

    if args.env_file:
        from dotenv import load_dotenv

        if not Path(args.env_file).is_file():
            print(f"no such env file: {args.env_file}", file=sys.stderr)
            return 2
        load_dotenv(args.env_file, override=True)

    env = _app_env()
    if env == "production" and not args.allow_production:
        print("refusing: APP_ENV is production (unset counts as production). This mints a "
              "token that acts as a student on the database. Use a local/staging env file, "
              "or pass --allow-production if you really mean prod.", file=sys.stderr)
        return 2

    from db import user_jwt

    try:
        key = user_jwt.signing_key()
    except user_jwt.SigningKeyError as exc:
        print(f"signing key problem: {exc}", file=sys.stderr)
        return 1

    if args.show_key:
        raw = os.environ[user_jwt.SIGNING_KEY_ENV]
        print(json.dumps({"alg": key.alg, "kid": key.kid, "fingerprint": key.fingerprint,
                          "app_env": env, "public_jwk": _public_view(raw)}, indent=2))
        return 0

    if not args.user_id:
        ap.error("user_id is required (or pass --show-key)")
    token = user_jwt.mint(args.user_id)
    if args.decode:
        header, claims, _ = token.split(".")
        print(json.dumps({"header": json.loads(_b64d(header)), "claims": json.loads(_b64d(claims))},
                         indent=2), file=sys.stderr)
    if user_jwt.config_problems():
        print("note: " + "; ".join(user_jwt.config_problems()), file=sys.stderr)
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
