"""Shared helpers for the one-off staging ops scripts in this directory:
copy_courses_to_staging, grant_staging_admin, approve_staging_users.

Those scripts span two Supabase projects and so deliberately bypass
db/connection.py::table() (which is single-environment) — see each script's module
docstring. The common bits live here to keep them from diverging: dotenv reading, a
safe-by-default write guard, the staging-key setup, and the decrypt-email→user index.

Credentials are read from gitignored dotenv files (never argv/process env), so the
DSN/keys don't leak into shell history or logs.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse


def dotenv_value(path: str | Path, key: str) -> str:
    p = Path(path)
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"ERROR: {key} not found in {p}")


def set_encryption_key(staging_env: str | Path = ".env.staging") -> None:
    """Put the staging ENCRYPTION_KEY in the process env. MUST be called before
    importing services.encryption, which loads the key at import time."""
    os.environ["ENCRYPTION_KEY"] = dotenv_value(staging_env, "ENCRYPTION_KEY")


def target_host(db_url: str) -> str:
    return urlparse(db_url).hostname or "<unknown>"


def confirm_write(db_url: str, apply: bool, action: str) -> bool:
    """Safe-by-default guard against pointing a write at the wrong project.

    Prints the destination host. Returns True only when --yes (apply=True) was
    passed; otherwise prints a preview notice and returns False so the caller can
    report what it *would* do without mutating anything.
    """
    print(f"Write target: {target_host(db_url)}")
    if not apply:
        print(f"  PREVIEW ONLY — re-run with --yes to {action}. No changes made.")
    return apply


def user_email_index(cur) -> dict[str, tuple[str, bool]]:
    """Map decrypted plaintext email -> (user_id, is_approved) for all users.

    users.email is AES-GCM encrypted with a random nonce (non-deterministic), so
    matching requires decrypting each row. Imports decrypt lazily so callers can
    call set_encryption_key() first.
    """
    from services.encryption import decrypt_if_present

    cur.execute("SELECT id, email, is_approved FROM users")
    index: dict[str, tuple[str, bool]] = {}
    for uid, email_ct, approved in cur.fetchall():
        plain = (decrypt_if_present(email_ct) or "").strip().lower()
        if plain:
            index[plain] = (uid, approved)
    return index
