"""
backend/services/gradescope/credentials.py

Stored Gradescope credentials (#118, moved from routes/gradescope.py): read and
decrypt them, log in with them, and record connection / sync-outcome state on
the ``gradescope_credentials`` row.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal

from gradescopeapi.classes.connection import GSConnection
from pydantic import BaseModel

from db.connection import table
from services.gradescope import client as gradescope_service
from services.encryption import decrypt, encrypt
from services.gradescope.errors import GradescopeCredsError

logger = logging.getLogger(__name__)


AuthMode = Literal["password", "cookies"]


class StoredCreds(BaseModel):
    auth_mode: AuthMode
    email: str | None = None
    password: str | None = None
    gradescope_session: str | None = None
    signed_token: str | None = None
    # Row metadata, not secrets: which saved version these are (the guard for
    # marking them stale) and whether they were already known to be rejected.
    updated_at: str | None = None
    needs_reauth: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_connection_state(user_id: str, fields: dict[str, Any], *, only_version: str | None = None) -> None:
    """Persist connection/sync-outcome columns on the credentials row. Never
    raises: the state is bookkeeping, and a failed write must not turn a
    finished sync (or its real error) into a 500.

    ``only_version`` pins the write to the credential version that produced the
    outcome (``updated_at`` as read with the creds): marking credentials stale
    must not land on a newer set the user saved while this request was running.
    """
    filters = {"user_id": f"eq.{user_id}"}
    if only_version:
        filters["updated_at"] = f"eq.{only_version}"
    try:
        table("gradescope_credentials").update(fields, filters=filters)
    except Exception:
        logger.warning("Failed to record Gradescope connection state for user_id=%s", user_id, exc_info=True)


def _load_creds(user_id: str) -> StoredCreds | None:
    """Fetch and decrypt stored Gradescope credentials for user_id. Returns None if none saved."""
    rows = table("gradescope_credentials").select(
        "auth_mode,email_encrypted,password_encrypted,cookies_encrypted,updated_at,needs_reauth",
        filters={"user_id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        return None
    row = rows[0]
    mode: AuthMode = row.get("auth_mode") or "password"
    meta = {"updated_at": row.get("updated_at"), "needs_reauth": bool(row.get("needs_reauth"))}
    try:
        if mode == "password":
            return StoredCreds(
                auth_mode="password",
                email=decrypt(row["email_encrypted"]) if row.get("email_encrypted") else None,
                password=decrypt(row["password_encrypted"]) if row.get("password_encrypted") else None,
                **meta,
            )
        else:  # cookies
            raw = decrypt(row["cookies_encrypted"]) if row.get("cookies_encrypted") else None
            payload = json.loads(raw) if raw else {}
            return StoredCreds(
                auth_mode="cookies",
                gradescope_session=payload.get("_gradescope_session"),
                signed_token=payload.get("signed_token"),
                **meta,
            )
    except Exception:
        logger.exception("Failed to decrypt Gradescope creds for user_id=%s", user_id)
        raise GradescopeCredsError("Stored credentials could not be read.")


def _establish_connection(creds: StoredCreds) -> GSConnection:
    """Re-establish an authenticated Gradescope session from stored creds.
    Picks the right login path based on the user's chosen mode."""
    if creds.auth_mode == "password":
        if not creds.email or not creds.password:
            raise GradescopeCredsError("Password-mode creds missing email/password")
        return gradescope_service.login(creds.email, creds.password)
    else:
        return gradescope_service.login_with_cookies(
            signed_token=creds.signed_token,
            gradescope_session=creds.gradescope_session,
        )


def connection_status(user_id: str) -> dict:
    """GET /status's answer: the connection state and the last sync outcome
    (see the route's docstring for the fields)."""
    rows = table("gradescope_credentials").select(
        "auth_mode,last_synced_at,updated_at,needs_reauth,last_attempt_at,last_sync_error",
        filters={"user_id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        return {
            "state": "disconnected",
            "connected": False,
            "has_credentials": False,
            "needs_reauth": False,
            "auth_mode": None,
            "last_synced_at": None,
            "last_attempt_at": None,
            "last_sync_error": None,
        }
    row = rows[0]
    needs_reauth = bool(row.get("needs_reauth"))
    return {
        "state": "needs_reauth" if needs_reauth else "connected",
        "connected": not needs_reauth,
        "has_credentials": True,
        "needs_reauth": needs_reauth,
        "auth_mode": row.get("auth_mode") or "password",
        "last_synced_at": row.get("last_synced_at"),
        "last_attempt_at": row.get("last_attempt_at"),
        "last_sync_error": row.get("last_sync_error"),
        "credentials_updated_at": row.get("updated_at"),
    }


def _save_creds(payload: dict[str, Any]) -> None:
    """Upsert a verified credentials row (the caller tested the login)."""
    payload["updated_at"] = _now_iso()
    # Fresh, verified credentials: whatever marked the old ones stale is moot.
    payload["needs_reauth"] = False
    payload["last_sync_error"] = None
    table("gradescope_credentials").upsert(payload, on_conflict="user_id")


def save_password_creds(user_id: str, email: str, password: str) -> None:
    """Encrypt and save password-mode credentials that just logged in."""
    payload: dict[str, Any] = {
        "user_id": user_id,
        "auth_mode": "password",
        "email_encrypted": encrypt(email),
        "password_encrypted": encrypt(password),
        "cookies_encrypted": None,
    }
    _save_creds(payload)


def save_cookie_creds(user_id: str, gradescope_session: str | None, signed_token: str | None) -> None:
    """Encrypt and save session cookies that just logged in (pasted by the
    user, or captured by the BU SSO flow), as auth_mode='cookies'."""
    cookie_blob = json.dumps(
        {
            "_gradescope_session": gradescope_session,
            "signed_token": signed_token or None,
        }
    )
    payload = {
        "user_id": user_id,
        "auth_mode": "cookies",
        "email_encrypted": None,
        "password_encrypted": None,
        "cookies_encrypted": encrypt(cookie_blob),
    }
    _save_creds(payload)
